"""
TimEndgamePlayer — TimClaudePlayer + exact endgame solver.

In the last 2-3 tricks of each round, the state space becomes small
enough to solve exactly. This player:

  1. Uses the TimClaudePlayer heuristic for the first 10-11 tricks.
  2. Switches to an exact solver when hand_size ≤ ENDGAME_MAX.
  3. The solver enumerates all opponent hand assignments consistent with
     observed voids, plays out each one to round-end with myself
     optimizing and opponents using a fixed heuristic policy, then
     picks the move with the lowest mean effective score (moon-flip
     adjusted).

For hand_size ≤ 2 the search is trivial (≤ 90 deals × small tree).
For hand_size = 3 we have ~1680 deals × ~50-node tree per deal —
still solvable in well under 1s.

The solver is strictly safe: if no valid deals are found, or if any
internal step fails, it falls back to the heuristic.
"""
from __future__ import annotations
import itertools
import time
from typing import Dict, List, Optional, Set, Tuple

from clients.python.api.Trick import Trick
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.SessionHelpers import RunMultipleGames
from clients.python.api.types.Card import (
    Card,
    Rank,
    SortCardsByRank,
    Suit,
)
from clients.python.api.types.PlayerTagSession import PlayerTagSession
from clients.python.players.random_player import RandomPlayer
from clients.python.players.tim_claude_player import TimClaudePlayer
from clients.python.util.Constants import GameType


QS = Card("QS")


def _card_point(c: Card) -> int:
    if c.suit == Suit.HEARTS:
        return 1
    if c == QS:
        return 13
    return 0


# Card pool cache (52 cards)
_ALL_CARDS: List[Card] = None


def _all_cards() -> List[Card]:
    global _ALL_CARDS
    if _ALL_CARDS is None:
        ranks = [r.value for r in Rank]
        suits = ["C", "D", "H", "S"]
        _ALL_CARDS = [Card(f"{r}{s}") for r in ranks for s in suits]
    return _ALL_CARDS


class TimEndgamePlayer(TimClaudePlayer):
    player_tag = "tim_endgame_player"

    # Solve exactly when our current-hand size is at most this many.
    # ENDGAME_MAX=3 fires earlier (more decisions) at modest extra cost.
    ENDGAME_MAX: int = 3
    # Cap deal enumeration to keep per-decision under ~2s.
    MAX_DEALS: int = 1200

    def __init__(self, player_tag_session):
        super().__init__(player_tag_session)

    def _current_hand(self) -> List[Card]:
        """True current hand (framework doesn't decrement self.hand)."""
        return [c for c in self.hand if c not in self.played_cards]

    def get_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
        try:
            return self._endgame_or_heuristic(trick, legal_moves)
        except Exception:
            return super().get_move(trick, legal_moves)

    def _endgame_or_heuristic(self, trick: Trick, legal_moves: List[Card]) -> Card:
        if len(legal_moves) == 1:
            return legal_moves[0]
        if self.shoot_committed or self._should_block_moon():
            return super().get_move(trick, legal_moves)
        hand = self._current_hand()
        if len(hand) > self.ENDGAME_MAX:
            return super().get_move(trick, legal_moves)
        # Endgame: exact solve.
        choice = self._solve_endgame(trick, legal_moves, hand)
        if choice is None:
            return super().get_move(trick, legal_moves)
        return choice

    # ── exact endgame solver ──────────────────────────────────────────────
    def _solve_endgame(
        self,
        trick: Trick,
        legal_moves: List[Card],
        current_hand: List[Card],
    ) -> Optional[Card]:
        """Enumerate all void-consistent opponent hand assignments, play
        each out to round end with myself optimal and opps heuristic.
        Return the legal_move minimizing mean effective score."""
        # 1. Compute the unknown card pool (everything not in my hand or
        #    already played).
        unknown = [
            c for c in _all_cards()
            if c not in current_hand and c not in self.played_cards
        ]

        # 2. Compute each opponent's remaining hand size.
        opp_play_count = self._opp_play_counts()
        opps = list(opp_play_count.keys())
        sizes = {p: 13 - opp_play_count[p] for p in opps}

        # Total unknowns must equal total opp slots.
        if sum(sizes.values()) != len(unknown):
            return None

        # 3. Enumerate void-consistent deals (cap to avoid explosion).
        deals = self._enumerate_deals(unknown, sizes, max_deals=self.MAX_DEALS)
        if not deals:
            return None

        # 4. For each legal move × each deal, simulate to round end.
        candidate_scores: Dict[Card, List[float]] = {c: [] for c in legal_moves}
        for deal in deals:
            for move in legal_moves:
                try:
                    score = self._simulate(move, deal, trick, current_hand)
                except _BadStateError:
                    continue
                candidate_scores[move].append(score)

        # 5. Pick lowest mean (with at least 1 sample).
        viable = {c: vs for c, vs in candidate_scores.items() if vs}
        if not viable:
            return None
        means = {c: sum(vs) / len(vs) for c, vs in viable.items()}
        return min(viable.keys(), key=lambda c: means[c])

    # ── helpers ───────────────────────────────────────────────────────────
    def _opp_play_counts(self) -> Dict[PlayerTagSession, int]:
        counts: Dict[PlayerTagSession, int] = {}
        for p in self.player_order:
            if p != self.player_tag_session:
                counts[p] = 0
        if self.current_round is not None:
            for t in getattr(self.current_round, "tricks", []):
                for m in t.moves:
                    if m.player in counts:
                        counts[m.player] += 1
        return counts

    def _enumerate_deals(
        self,
        unknown: List[Card],
        sizes: Dict[PlayerTagSession, int],
        max_deals: int = 2000,
    ) -> List[Dict[PlayerTagSession, Tuple[Card, ...]]]:
        """Enumerate all assignments of `unknown` cards to opponents respecting
        sizes and observed voids. Caps at `max_deals` (uses first that-many).
        """
        opps = list(sizes.keys())
        # Assign cards to opps in order. We pick C(unknown, sizes[opp0])
        # cards for opp0, then C(remaining, sizes[opp1]) for opp1, etc.
        results: List[Dict[PlayerTagSession, Tuple[Card, ...]]] = []
        voids = self.opponent_voids

        def recurse(remaining_cards: Tuple[Card, ...], idx: int, partial: Dict):
            if len(results) >= max_deals:
                return
            if idx == len(opps):
                results.append(dict(partial))
                return
            opp = opps[idx]
            size = sizes[opp]
            # Only consider cards not in opp's void suits.
            opp_voids = voids.get(opp, set())
            eligible = [c for c in remaining_cards if c.suit not in opp_voids]
            if len(eligible) < size:
                return  # can't satisfy this opp without ignoring voids
            for combo in itertools.combinations(eligible, size):
                if len(results) >= max_deals:
                    return
                rest = tuple(c for c in remaining_cards if c not in combo)
                partial[opp] = combo
                recurse(rest, idx + 1, partial)
                del partial[opp]

        recurse(tuple(unknown), 0, {})
        return results

    def _simulate(
        self,
        my_first_card: Card,
        deal: Dict[PlayerTagSession, Tuple[Card, ...]],
        trick: Trick,
        current_hand: List[Card],
    ) -> float:
        """Play out the round from this point with PROPER minimax over
        my future moves and heuristic for opponents. Returns my best-case
        effective score (moon-flip adjusted) for the given starting move.
        """
        hands: Dict[PlayerTagSession, List[Card]] = {
            self.player_tag_session: list(current_hand),
        }
        for opp, cards in deal.items():
            hands[opp] = list(cards)

        cur_trick_moves: List[Tuple[PlayerTagSession, Card]] = [
            (m.player, m.card) for m in trick.moves
        ]
        if my_first_card not in hands[self.player_tag_session]:
            raise _BadStateError("first card not in hand")
        hands[self.player_tag_session].remove(my_first_card)
        cur_trick_moves.append((self.player_tag_session, my_first_card))
        hearts_broken = self.hearts_broken or (
            my_first_card.suit == Suit.HEARTS or my_first_card == QS
        )

        my_idx = self.player_order.index(self.player_tag_session)
        first_seat_idx = (my_idx - len(trick.moves)) % len(self.player_order)

        points: Dict[PlayerTagSession, float] = {p: 0.0 for p in self.player_order}
        if self.current_round is not None:
            for p, pts in self.current_round.get_round_points().items():
                if p in points:
                    points[p] += pts

        return self._minimax(
            hands, cur_trick_moves, hearts_broken, points,
            len(cur_trick_moves), first_seat_idx,
        )

    def _minimax(
        self,
        hands: Dict[PlayerTagSession, List[Card]],
        cur_trick: List[Tuple[PlayerTagSession, Card]],
        hearts_broken: bool,
        points: Dict[PlayerTagSession, float],
        played_in_trick: int,
        first_seat_idx: int,
    ) -> float:
        """Recursive minimax. For my turns: try all my legal cards, pick
        the one minimizing my final score. For opp turns: heuristic.
        """
        # Trick complete? Tally and continue.
        if played_in_trick == 4:
            lead_suit = cur_trick[0][1].suit
            winner = max(
                cur_trick,
                key=lambda pc: pc[1].rank.to_int() if pc[1].suit == lead_suit else -1,
            )[0]
            trick_pts = sum(_card_point(c) for _, c in cur_trick)
            new_points = dict(points)
            new_points[winner] += trick_pts
            # End of round?
            if not hands[self.player_tag_session]:
                return self._effective_score(new_points)
            # Start next trick — winner leads.
            new_first_idx = self.player_order.index(winner)
            return self._minimax(
                hands, [], hearts_broken, new_points, 0, new_first_idx,
            )

        # Whose turn?
        seat_idx = (first_seat_idx + played_in_trick) % 4
        player = self.player_order[seat_idx]

        if player == self.player_tag_session:
            # MY turn — try every legal move, pick min final score.
            legal = self._legal_for(hands[player], cur_trick, hearts_broken)
            if not legal:
                raise _BadStateError("no legal move for me")
            best = float("inf")
            for card in legal:
                # Apply move
                hands[player].remove(card)
                new_trick = cur_trick + [(player, card)]
                new_broken = hearts_broken or card.suit == Suit.HEARTS or card == QS
                score = self._minimax(
                    hands, new_trick, new_broken, points,
                    played_in_trick + 1, first_seat_idx,
                )
                # Undo
                hands[player].append(card)
                if score < best:
                    best = score
            return best
        else:
            # Opp turn — use heuristic (deterministic).
            card = self._choose_card(
                player, hands[player], cur_trick, hearts_broken, is_me=False,
            )
            hands[player].remove(card)
            new_trick = cur_trick + [(player, card)]
            new_broken = hearts_broken or card.suit == Suit.HEARTS or card == QS
            score = self._minimax(
                hands, new_trick, new_broken, points,
                played_in_trick + 1, first_seat_idx,
            )
            hands[player].append(card)
            return score

    def _legal_for(
        self,
        hand: List[Card],
        cur_trick: List[Tuple[PlayerTagSession, Card]],
        hearts_broken: bool,
    ) -> List[Card]:
        """Legal moves from `hand` given the current trick state."""
        if not hand:
            return []
        if cur_trick:
            lead_suit = cur_trick[0][1].suit
            on_suit = [c for c in hand if c.suit == lead_suit]
            return on_suit if on_suit else list(hand)
        # Leading: can't lead hearts if not broken (unless hand is all hearts).
        if not hearts_broken:
            non_hearts = [c for c in hand if c.suit != Suit.HEARTS]
            if non_hearts:
                return non_hearts
        return list(hand)

    def _effective_score(self, points: Dict[PlayerTagSession, float]) -> float:
        shooters = [p for p, v in points.items() if v >= 26]
        zeros = [p for p, v in points.items() if v == 0]
        my_score = points[self.player_tag_session]
        if len(shooters) == 1 and len(zeros) == 3:
            return 0.0 if shooters[0] == self.player_tag_session else 26.0
        return my_score

    def _choose_card(
        self,
        player: PlayerTagSession,
        hand: List[Card],
        trick_moves: List[Tuple[PlayerTagSession, Card]],
        hearts_broken: bool,
        is_me: bool,
    ) -> Card:
        """Card choice for a player during simulation. For me (`is_me`),
        currently uses the SAME heuristic as opponents — meaning we don't
        re-optimize my future moves within the simulation. This is the
        "expected play" approach: I evaluate by what happens if everyone
        (including future-me) plays per a fixed heuristic, with the only
        free variable being the CURRENT decision (encoded by `my_first_card`).
        """
        if not hand:
            raise _BadStateError("empty hand during simulation")
        if not trick_moves:
            non_hearts = [c for c in hand if c.suit != Suit.HEARTS]
            if non_hearts and not hearts_broken:
                return SortCardsByRank(non_hearts)[0]
            return SortCardsByRank(hand)[0]
        lead_suit = trick_moves[0][1].suit
        on_suit = [c for c in hand if c.suit == lead_suit]
        if on_suit:
            cur_max = max(
                m.rank.to_int() for _, m in trick_moves if m.suit == lead_suit
            )
            below = [c for c in on_suit if c.rank.to_int() < cur_max]
            if below:
                return SortCardsByRank(below, reverse=True)[0]
            return SortCardsByRank(on_suit)[0]
        # Off-suit
        if QS in hand:
            return QS
        non_pts = [c for c in hand if c.suit != Suit.HEARTS and c != QS]
        if non_pts:
            return SortCardsByRank(non_pts, reverse=True)[0]
        return SortCardsByRank(hand, reverse=True)[0]


class _BadStateError(Exception):
    pass


if __name__ == "__main__":
    import sys
    config = sys.argv[1] if len(sys.argv) > 1 else "config.env"
    sys.argv = [sys.argv[0], config]
    with ManagedConnection() as conn:
        games = RunMultipleGames(
            conn, GameType.ANY,
            [TimEndgamePlayer, RandomPlayer, RandomPlayer, RandomPlayer],
            num_games=10,
        )
        wins = sum(1 for g in games if "tim_endgame" in str(g.winner))
        print(f"TimEndgamePlayer vs 3x Random: {wins}/10")
