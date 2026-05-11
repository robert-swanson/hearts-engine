"""
Tim-Claude with look-ahead — determinized playout search on top of the
TimClaudePlayer heuristic.

For each non-trivial decision:
  1. Sample plausible opponent hands consistent with observed state:
       - exclude played cards and our hand
       - respect observed voids (don't deal a void suit to that opponent)
       - match each opponent's known hand size
  2. For each legal move, play out the rest of the round using a fast
     uniform heuristic policy for all 4 players (including moon-flip
     accounting at end of playout).
  3. Repeat playouts until time budget (default 5s, via TIM_SEARCH_BUDGET
     env var) is exhausted, splitting across legal moves round-robin.
  4. Pick the move with the lowest mean effective points taken by us.

STATUS (as of 2026-05-10): this implementation UNDERPERFORMS the pure
TimClaudePlayer heuristic against itself (~15% vs 25% chance baseline).
The dominant problem is rollout-policy mismatch: the cheap rollout
policy in `_rollout_choose` doesn't model TimClaudePlayer-level smart
defense, so MCTS optimizes for fictional weak opponents. Fixing this
properly would require either (a) using full TimClaudePlayer logic as
the rollout policy (slow, needs careful state replay) or (b) far more
playouts per candidate (budget × 10) so noise gets averaged out.

Kept in the repo as infrastructure for future work — the determinized
sampling + moon-flip-aware scoring + time-budgeted search are reusable.
"""
from __future__ import annotations
import random
import sys
import time
from typing import Dict, List, Optional, Set, Tuple

from clients.python.api.Game import Game
from clients.python.api.Player import Player
from clients.python.api.Round import Round
from clients.python.api.Trick import Trick
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.SessionHelpers import RunMultipleGames
from clients.python.api.types.Card import (
    Card,
    Rank,
    SortCardsByRank,
    Suit,
)
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession
from clients.python.players.random_player import RandomPlayer
from clients.python.players.tim_claude_player import TimClaudePlayer
from clients.python.util.Constants import GameType


QS = Card("QS")


# Pre-built deck cache for fast sampling
_ALL_CARDS: List[Card] = None


def _all_cards() -> List[Card]:
    global _ALL_CARDS
    if _ALL_CARDS is None:
        ranks = [r.value for r in Rank]
        suits = ["C", "D", "H", "S"]
        _ALL_CARDS = [Card(f"{r}{s}") for r in ranks for s in suits]
    return _ALL_CARDS


def _card_point(c: Card) -> int:
    if c.suit == Suit.HEARTS:
        return 1
    if c == QS:
        return 13
    return 0


class TimMCTSPlayer(TimClaudePlayer):
    player_tag = "tim_mcts_player"

    def __init__(self, player_tag_session):
        super().__init__(player_tag_session)
        # Track our own plays separately — framework's `self.hand` is NOT
        # decremented during ActiveGameFlow, so we need our own.
        self._my_played: Set[Card] = set()

    def handle_new_round(self, round):
        super().handle_new_round(round)
        self._my_played = set()

    def handle_move(self, player, card):
        super().handle_move(player, card)
        if player == self.player_tag_session:
            self._my_played.add(card)

    def _current_hand(self) -> List[Card]:
        """Compute our true current hand. The framework's `self.hand` is
        not decremented during play, so we infer current cards from the
        intersection of original-hand and not-yet-played.

        Uses self.played_cards (maintained by parent via handle_move for ALL
        moves) rather than _my_played (which has shown undercount issues in
        some game flows).
        """
        return [c for c in self.hand if c not in self.played_cards]

    # Tunable: total seconds spent on look-ahead per decision. 5.0 is the
    # quoted tournament budget; default lowered to 1.0 for bench speed.
    search_time_budget: float = float(__import__("os").environ.get(
        "TIM_SEARCH_BUDGET", "1.0"
    ))
    # Don't search if we're too early in the round (heuristic does fine).
    min_played_cards_for_search: int = 8
    # Don't search the last 2 tricks — outcome is forced.
    min_hand_size_for_search: int = 3

    def get_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
        try:
            return self._mcts_or_heuristic(trick, legal_moves)
        except Exception:
            return super().get_move(trick, legal_moves)

    def _mcts_or_heuristic(
        self, trick: Trick, legal_moves: List[Card]
    ) -> Card:
        if len(legal_moves) == 1:
            return legal_moves[0]
        # Defer to heuristic if shoot-committed or moon-blocking — those
        # modes have specific policies that don't search well.
        if self.shoot_committed or self._should_block_moon():
            return super().get_move(trick, legal_moves)
        # Skip search at edges of the round.
        if len(self.played_cards) < self.min_played_cards_for_search:
            return super().get_move(trick, legal_moves)
        if len(self._current_hand()) <= self.min_hand_size_for_search:
            return super().get_move(trick, legal_moves)

        # Determinized playout search.
        deadline = time.perf_counter() + self.search_time_budget
        results: Dict[Card, List[float]] = {c: [] for c in legal_moves}
        playouts = 0
        # Cycle through legal moves so each gets balanced rollouts.
        move_idx = 0
        while time.perf_counter() < deadline:
            try:
                opp_hands = self._sample_opponent_hands()
            except _SampleError:
                # Can happen when voids are very constraining; bail out.
                break
            move = legal_moves[move_idx % len(legal_moves)]
            move_idx += 1
            pts = self._playout(move, opp_hands, trick)
            results[move].append(pts)
            playouts += 1

        if playouts == 0 or all(len(v) == 0 for v in results.values()):
            return super().get_move(trick, legal_moves)

        def avg(card: Card) -> float:
            vals = results[card]
            if not vals:
                return float("inf")
            return sum(vals) / len(vals)

        best = min(legal_moves, key=avg)
        return best

    # ── opponent hand sampling ─────────────────────────────────────────────
    def _sample_opponent_hands(self) -> Dict[PlayerTagSession, List[Card]]:
        """Randomly deal unknown cards to opponents, respecting voids and
        each opponent's known hand size. Returns a dict
        opponent_session -> List[Card].
        """
        current_hand = self._current_hand()
        unknown: List[Card] = []
        for c in _all_cards():
            if c in current_hand:
                continue
            if c in self.played_cards:
                continue
            unknown.append(c)

        # Each opponent's remaining hand size = how many cards they have left.
        # Tracked by: total cards dealt (13) minus cards they've already played.
        opp_played_count: Dict[PlayerTagSession, int] = {}
        for p in self.player_order:
            if p == self.player_tag_session:
                continue
            opp_played_count[p] = 0
        # Reconstruct per-opponent card-played count from round.tricks.
        # The framework appends each trick BEFORE running it, so the current
        # (partial) trick is already in round.tricks[-1]; no need to add it
        # separately (would double-count).
        if self.current_round is not None:
            for t in getattr(self.current_round, "tricks", []):
                for m in t.moves:
                    if m.player in opp_played_count:
                        opp_played_count[m.player] += 1

        opps = list(opp_played_count.keys())
        sizes = {p: 13 - opp_played_count[p] for p in opps}

        # Sanity check: unknown deck size must match total sizes.
        if sum(sizes.values()) != len(unknown):
            raise _SampleError(
                f"size mismatch: deck={len(unknown)} sizes={sum(sizes.values())}"
            )
        # Constraint: each opponent must receive cards not in their void
        # suits. Retry up to 5 times respecting voids; fall back to
        # unconstrained random dealing if all retries fail.
        for attempt in range(5):
            try:
                return self._deal_respecting_voids(unknown, sizes)
            except _SampleError:
                continue
        # Fallback: ignore voids, just deal sizes randomly.
        return self._deal_random(unknown, sizes)

    def _deal_random(
        self, cards: List[Card], sizes: Dict[PlayerTagSession, int],
    ) -> Dict[PlayerTagSession, List[Card]]:
        deck = list(cards)
        random.shuffle(deck)
        result: Dict[PlayerTagSession, List[Card]] = {}
        idx = 0
        for p, sz in sizes.items():
            result[p] = deck[idx:idx + sz]
            idx += sz
        return result

    def _deal_respecting_voids(
        self,
        cards: List[Card],
        sizes: Dict[PlayerTagSession, int],
    ) -> Dict[PlayerTagSession, List[Card]]:
        """Deal cards to opponents matching `sizes` and respecting
        `self.opponent_voids`. Raises _SampleError on infeasibility.
        """
        deck = list(cards)
        random.shuffle(deck)
        result: Dict[PlayerTagSession, List[Card]] = {p: [] for p in sizes}
        # For each card in shuffled deck, place into a random opponent that
        # is (a) not full and (b) not void in this card's suit.
        for c in deck:
            candidates = [
                p for p, h in result.items()
                if len(h) < sizes[p]
                and c.suit not in self.opponent_voids.get(p, set())
            ]
            if not candidates:
                # No valid opponent for this card — try assigning to any
                # opponent with space, ignoring void (sample was bad).
                candidates = [p for p, h in result.items() if len(h) < sizes[p]]
                if not candidates:
                    raise _SampleError("ran out of slots")
            chosen = random.choice(candidates)
            result[chosen].append(c)
        # Verify all sizes met
        for p, s in sizes.items():
            if len(result[p]) != s:
                raise _SampleError(f"size mismatch for {p}: {len(result[p])}/{s}")
        return result

    # ── playout ────────────────────────────────────────────────────────────
    def _playout(
        self,
        my_first_card: Card,
        opp_hands: Dict[PlayerTagSession, List[Card]],
        trick: Trick,
    ) -> float:
        """Simulate the rest of the round starting from this trick.
        Returns the EFFECTIVE round score for me (lower = better) including
        moon flip:
          - If a single player took all 26 points: that player gets 0,
            everyone else gets +26.
          - Otherwise each player gets their raw points.

        Adds round-points already taken before this trick to compute the
        full round-score for accurate moon-flip detection.
        """
        hands: Dict[PlayerTagSession, List[Card]] = {
            self.player_tag_session: self._current_hand(),
        }
        for p, cards in opp_hands.items():
            hands[p] = list(cards)

        # Current trick state: which cards have been played, by whom.
        cur_trick_moves: List[Tuple[PlayerTagSession, Card]] = [
            (m.player, m.card) for m in trick.moves
        ]
        # Determine whose turn it is to play. Our (my_first_card) play is
        # this turn. After that, play continues until trick complete.
        if my_first_card not in hands[self.player_tag_session]:
            return 0.0  # shouldn't happen — bail out cheaply
        hands[self.player_tag_session].remove(my_first_card)
        cur_trick_moves.append((self.player_tag_session, my_first_card))

        hearts_broken = self.hearts_broken or (my_first_card.suit == Suit.HEARTS) or my_first_card == QS

        # Who plays next in this trick?
        player_order = self.player_order
        my_idx = player_order.index(self.player_tag_session)
        first_seat_idx = (my_idx - len(trick.moves)) % len(player_order)
        played_in_trick = len(cur_trick_moves)
        # Per-player points taken in remaining tricks (for moon-flip).
        points: Dict[PlayerTagSession, float] = {p: 0.0 for p in player_order}
        # Add points already taken in this round (from completed tricks).
        if self.current_round is not None:
            already_taken = self.current_round.get_round_points()
            for p, pts in already_taken.items():
                if p in points:
                    points[p] += pts

        # Loop tricks
        while True:
            # Finish current trick
            while played_in_trick < 4:
                seat_idx = (first_seat_idx + played_in_trick) % 4
                next_player = player_order[seat_idx]
                card = self._rollout_choose(
                    next_player, hands[next_player], cur_trick_moves, hearts_broken
                )
                hands[next_player].remove(card)
                cur_trick_moves.append((next_player, card))
                played_in_trick += 1
                if card.suit == Suit.HEARTS or card == QS:
                    hearts_broken = True

            # Tally trick
            lead_suit = cur_trick_moves[0][1].suit
            winner = max(
                cur_trick_moves,
                key=lambda pc: (
                    pc[1].rank.to_int() if pc[1].suit == lead_suit else -1
                ),
            )[0]
            trick_pts = sum(_card_point(c) for _, c in cur_trick_moves)
            points[winner] += trick_pts

            # End of round?
            if not hands[self.player_tag_session]:
                break

            # Start next trick — winner leads
            first_seat_idx = player_order.index(winner)
            cur_trick_moves = []
            played_in_trick = 0
            if winner == self.player_tag_session:
                # OUR turn to lead — use rollout policy
                card = self._rollout_choose(
                    self.player_tag_session,
                    hands[self.player_tag_session],
                    [],
                    hearts_broken,
                )
                hands[self.player_tag_session].remove(card)
                cur_trick_moves.append((self.player_tag_session, card))
                played_in_trick = 1
                if card.suit == Suit.HEARTS or card == QS:
                    hearts_broken = True

        # Apply moon-flip: if exactly one player has all 26 of round's pts,
        # they shot the moon → flip (shooter=0, others=+26).
        shooters = [p for p, v in points.items() if v >= 26]
        zeros = [p for p, v in points.items() if v == 0]
        my_score = points[self.player_tag_session]
        if len(shooters) == 1 and len(zeros) == 3:
            shooter = shooters[0]
            if shooter == self.player_tag_session:
                my_score = 0.0  # I shot the moon — best outcome
            else:
                my_score = 26.0  # someone else shot — I get +26
        return my_score

    @staticmethod
    def _rollout_choose(
        player: PlayerTagSession,
        hand: List[Card],
        trick_moves: List[Tuple[PlayerTagSession, Card]],
        hearts_broken: bool,
    ) -> Card:
        """Fast heuristic rollout policy. Same for all players.
        - Leading: lead lowest non-heart (or heart if forced/broken).
        - Following: highest below winner (duck); smallest forced winner.
        - Off-suit: dump highest non-points card; QS first opportunity.
        """
        if not hand:
            raise _SampleError("empty hand in rollout — sampling produced wrong sizes")
        if not trick_moves:
            # Lead — prefer lowest non-heart
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
            # forced winner — smallest
            return SortCardsByRank(on_suit)[0]
        # Off-suit dump
        if QS in hand:
            return QS  # dump it whenever possible
        non_pts = [c for c in hand if c.suit != Suit.HEARTS and c != QS]
        if non_pts:
            return SortCardsByRank(non_pts, reverse=True)[0]
        return SortCardsByRank(hand, reverse=True)[0]


class _SampleError(Exception):
    pass


if __name__ == "__main__":
    import sys
    config = sys.argv[1] if len(sys.argv) > 1 else "config.env"
    sys.argv = [sys.argv[0], config]
    with ManagedConnection() as conn:
        games = RunMultipleGames(
            conn, GameType.ANY,
            [TimMCTSPlayer, RandomPlayer, RandomPlayer, RandomPlayer],
            num_games=4,
        )
        wins = sum(1 for g in games if "tim_mcts" in str(g.winner))
        print(f"TimMCTSPlayer vs 3x Random: {wins}/4 wins")
