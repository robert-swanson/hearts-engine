"""
TimAdaptivePlayer — TimClaudePlayer with look-ahead as one selectively-used
heuristic signal, weighted by observed opponent predictability.

The fundamental issue with prior MCTS attempts: blindly trusting search
output. Look-ahead optimizes against a fictional opp policy; when reality
matches that policy, search wins. When it doesn't, search loses. So:

  1. Fire look-ahead ONLY on pivotal decisions where its predictions are
     likely to matter and the heuristic has weak signal. Pivotal here =
     hand contains QS, or QS still live and could land on me, or hearts
     broken and the trick already has points.
  2. Track our rollout policy's accuracy: every time an opponent plays,
     compare against what our policy predicted given the visible state.
     This builds a per-opponent "trust score" for our rollout fidelity.
  3. Only override the heuristic when:
       - the pivotal-decision gate fires
       - the average trust score is above a threshold
       - the look-ahead pick beats the heuristic by a meaningful margin
         (statistical significance via paired-t-test, like augment mode).

Otherwise: heuristic decides. The look-ahead is a CONSULTANT, not the boss.
"""
from __future__ import annotations
import random
import time
from typing import Dict, List, Optional, Set, Tuple

from clients.python.api.Trick import Trick
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.SessionHelpers import RunMultipleGames
from clients.python.api.types.Card import (
    Card,
    GroupCardsBySuit,
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


_ALL_CARDS: List[Card] = None
def _all_cards() -> List[Card]:
    global _ALL_CARDS
    if _ALL_CARDS is None:
        ranks = [r.value for r in Rank]
        suits = ["C", "D", "H", "S"]
        _ALL_CARDS = [Card(f"{r}{s}") for r in ranks for s in suits]
    return _ALL_CARDS


class _SampleError(Exception):
    pass


class TimAdaptiveV1(TimClaudePlayer):
    player_tag = "tim_adaptive_v1"

    # Tunables — exposed as class attrs so tuner can sweep them later.
    search_budget_s: float = 0.5  # per pivotal decision
    min_trust_to_override: float = 0.50  # opp-prediction accuracy ≥ this
    min_predict_samples: int = 8  # need at least N opp moves observed
    override_effect_threshold: float = 1.0  # MCTS pick must save ≥ this many pts
    override_pvalue_t: float = -1.65  # one-sided t ≤ this (p<0.05)
    max_candidates: int = 3
    # Pivotal-decision gates
    min_played_for_pivotal: int = 8

    def __init__(self, player_tag_session):
        super().__init__(player_tag_session)
        # Per-opp prediction tracking — populated in handle_move.
        self._opp_pred_correct: Dict[PlayerTagSession, int] = {}
        self._opp_pred_total: Dict[PlayerTagSession, int] = {}

    def handle_new_round(self, round):
        super().handle_new_round(round)
        # Trust signal persists across rounds within a game.

    def handle_move(self, player, card):
        # Predict opp's move using our rollout policy, then check accuracy.
        # IMPORTANT: predict BEFORE recording the move (so played_cards
        # state is what we'd have used in our search).
        if player != self.player_tag_session and self.current_trick is not None:
            self._record_opp_prediction(player, card)
        super().handle_move(player, card)

    def _record_opp_prediction(self, player: PlayerTagSession, actual: Card) -> None:
        """Compare our rollout-policy prediction to what they actually played."""
        # Reconstruct opp's plausible hand at this moment: we don't know
        # their hand exactly, but we know what suits they MIGHT have.
        # Predict their card via the rollout policy applied to a plausible
        # set — specifically, the set of all live cards in the trick's
        # lead suit that we haven't seen played and aren't in our hand.
        trick_moves = [(m.player, m.card) for m in self.current_trick.moves
                       if m.card != actual]  # exclude the card they just played
        # Only score predictions where opp had a real choice.
        if not trick_moves:
            return  # opp was leading — too many options to score fairly
        lead_suit = trick_moves[0][1].suit
        # Build candidate set: all live cards in lead-suit (could be in their hand)
        # OR — if they played off-suit, they were void in lead-suit.
        candidates: List[Card] = []
        for c in _all_cards():
            if c in self.played_cards:
                continue
            if c in self.hand:
                continue
            if c == actual:
                candidates.append(c)
                continue
            candidates.append(c)
        if not candidates:
            return
        on_suit = [c for c in candidates if c.suit == lead_suit]
        # Heuristic guess: if opp has lead-suit in their plausible set,
        # they should follow suit; predict using policy on on-suit candidates.
        # If they played off-suit, they were forced (void).
        if actual.suit == lead_suit:
            if not on_suit:
                return
            # Predict the highest-below-winner from on_suit set
            cur_max = max(m.rank.to_int() for _, m in trick_moves
                          if m.suit == lead_suit)
            below = [c for c in on_suit if c.rank.to_int() < cur_max]
            if below:
                predicted = SortCardsByRank(below, reverse=True)[0]
            else:
                predicted = SortCardsByRank(on_suit)[0]
        else:
            # Opp dumped off-suit (was void) — predict highest non-points
            non_pts = [c for c in candidates
                       if c.suit != lead_suit and c.suit != Suit.HEARTS and c != QS]
            if QS in candidates and any(_card_point(c) > 0 for _, c in trick_moves):
                predicted = QS
            elif non_pts:
                predicted = SortCardsByRank(non_pts, reverse=True)[0]
            else:
                return  # can't make a reliable prediction
        self._opp_pred_total[player] = self._opp_pred_total.get(player, 0) + 1
        if predicted == actual:
            self._opp_pred_correct[player] = self._opp_pred_correct.get(player, 0) + 1

    def _opp_trust(self) -> float:
        """Average prediction accuracy across all observed opponents.
        Returns 0.0 if not enough data yet."""
        if not self._opp_pred_total:
            return 0.0
        total = sum(self._opp_pred_total.values())
        correct = sum(self._opp_pred_correct.values())
        if total < self.min_predict_samples:
            return 0.0
        return correct / total

    # ── pivotal decision detection ─────────────────────────────────────────
    def _is_pivotal(self, trick: Trick, legal_moves: List[Card]) -> bool:
        """Should we even bother with look-ahead for this decision?"""
        if len(legal_moves) < 2:
            return False
        if len(self.played_cards) < self.min_played_for_pivotal:
            return False
        # QS-related: I hold QS, or QS is still live and could land on me.
        current_hand = self._current_hand()
        if QS in current_hand:
            return True
        if QS not in self.played_cards and QS not in current_hand:
            # QS is in someone else's hand — opp may dump on me
            return True
        # Hearts broken and trick already has points
        if self.hearts_broken:
            trick_pts = sum(m.card.get_point_value() for m in trick.moves)
            if trick_pts > 0:
                return True
        return False

    def _current_hand(self) -> List[Card]:
        return [c for c in self.hand if c not in self.played_cards]

    # ── main move logic ────────────────────────────────────────────────────
    def get_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
        # Heuristic always picks first — it's the default.
        heuristic_move = super().get_move(trick, legal_moves)
        try:
            return self._maybe_override(trick, legal_moves, heuristic_move)
        except Exception:
            return heuristic_move

    def _maybe_override(
        self,
        trick: Trick,
        legal_moves: List[Card],
        heuristic_move: Card,
    ) -> Card:
        # Gate 1: trivial / shoot / block — no override.
        if len(legal_moves) == 1:
            return heuristic_move
        if self.shoot_committed or self._should_block_moon():
            return heuristic_move
        # Gate 2: pivotal-decision check.
        if not self._is_pivotal(trick, legal_moves):
            return heuristic_move
        # Gate 3: trust signal — has our rollout policy been accurate?
        trust = self._opp_trust()
        if trust < self.min_trust_to_override:
            return heuristic_move
        # All gates passed. Run paired look-ahead with CRN.
        return self._look_ahead_override(trick, legal_moves, heuristic_move)

    def _look_ahead_override(
        self,
        trick: Trick,
        legal_moves: List[Card],
        heuristic_move: Card,
    ) -> Card:
        # Top-K by rank low to high, plus heuristic move
        if len(legal_moves) <= self.max_candidates:
            candidates = list(legal_moves)
        else:
            sorted_by_rank = SortCardsByRank(legal_moves)
            candidates = list(sorted_by_rank[: self.max_candidates])
            if heuristic_move not in candidates:
                candidates[-1] = heuristic_move
        if heuristic_move not in candidates:
            candidates.append(heuristic_move)

        # Paired-CRN MCTS over candidates
        deadline = time.perf_counter() + self.search_budget_s
        samples: Dict[Card, List[float]] = {c: [] for c in candidates}
        while time.perf_counter() < deadline:
            try:
                opp_hands = self._sample_opps()
            except _SampleError:
                continue
            ok = True
            sample_scores: Dict[Card, float] = {}
            for c in candidates:
                try:
                    sample_scores[c] = self._playout(c, opp_hands, trick)
                except _SampleError:
                    ok = False
                    break
            if not ok:
                continue
            for c, s in sample_scores.items():
                samples[c].append(s)
        # Confirm sufficient data
        n = min(len(v) for v in samples.values())
        if n < 8:
            return heuristic_move

        means = {c: sum(samples[c]) / len(samples[c]) for c in candidates}
        mcts_pick = min(candidates, key=lambda c: means[c])
        if mcts_pick == heuristic_move:
            return heuristic_move

        # Paired t-test
        deltas = [samples[mcts_pick][i] - samples[heuristic_move][i] for i in range(n)]
        mean_d = sum(deltas) / n
        if mean_d >= -self.override_effect_threshold:
            return heuristic_move
        var = sum((d - mean_d) ** 2 for d in deltas) / max(1, n - 1)
        se = (var / n) ** 0.5
        if se == 0:
            return mcts_pick
        t = mean_d / se
        if t > self.override_pvalue_t:
            return heuristic_move
        return mcts_pick

    # ── sampling + playout ────────────────────────────────────────────────
    def _sample_opps(self) -> Dict[PlayerTagSession, List[Card]]:
        current_hand = self._current_hand()
        unknown = [c for c in _all_cards()
                   if c not in current_hand and c not in self.played_cards]
        opp_play_count: Dict[PlayerTagSession, int] = {}
        for p in self.player_order:
            if p != self.player_tag_session:
                opp_play_count[p] = 0
        if self.current_round is not None:
            for t in getattr(self.current_round, "tricks", []):
                for m in t.moves:
                    if m.player in opp_play_count:
                        opp_play_count[m.player] += 1
        sizes = {p: 13 - opp_play_count[p] for p in opp_play_count}
        if sum(sizes.values()) != len(unknown):
            raise _SampleError("size mismatch")
        # Random with void respect, fallback to ignore-voids.
        for _ in range(3):
            try:
                return self._deal_voids(unknown, sizes)
            except _SampleError:
                continue
        return self._deal_random(unknown, sizes)

    def _deal_voids(self, cards, sizes):
        deck = list(cards)
        random.shuffle(deck)
        result = {p: [] for p in sizes}
        voids = self.opponent_voids
        for c in deck:
            choices = [p for p, h in result.items()
                       if len(h) < sizes[p] and c.suit not in voids.get(p, set())]
            if not choices:
                choices = [p for p, h in result.items() if len(h) < sizes[p]]
                if not choices:
                    raise _SampleError("no slot")
            result[random.choice(choices)].append(c)
        return result

    def _deal_random(self, cards, sizes):
        deck = list(cards)
        random.shuffle(deck)
        result = {}
        idx = 0
        for p, s in sizes.items():
            result[p] = deck[idx:idx + s]
            idx += s
        return result

    def _playout(
        self,
        my_first: Card,
        opp_hands: Dict[PlayerTagSession, List[Card]],
        trick: Trick,
    ) -> float:
        hands = {self.player_tag_session: self._current_hand()}
        for p, cs in opp_hands.items():
            hands[p] = list(cs)
        cur_moves = [(m.player, m.card) for m in trick.moves]
        if my_first not in hands[self.player_tag_session]:
            raise _SampleError("missing card")
        hands[self.player_tag_session].remove(my_first)
        cur_moves.append((self.player_tag_session, my_first))
        hearts_broken = self.hearts_broken or my_first.suit == Suit.HEARTS or my_first == QS
        my_idx = self.player_order.index(self.player_tag_session)
        first_seat_idx = (my_idx - len(trick.moves)) % 4
        points = {p: 0.0 for p in self.player_order}
        if self.current_round is not None:
            for p, pts in self.current_round.get_round_points().items():
                if p in points:
                    points[p] += pts
        played_in_trick = len(cur_moves)
        while True:
            while played_in_trick < 4:
                seat = (first_seat_idx + played_in_trick) % 4
                player = self.player_order[seat]
                if not hands[player]:
                    raise _SampleError("empty in playout")
                card = self._policy_pick(hands[player], cur_moves, hearts_broken)
                hands[player].remove(card)
                cur_moves.append((player, card))
                played_in_trick += 1
                if card.suit == Suit.HEARTS or card == QS:
                    hearts_broken = True
            lead_suit = cur_moves[0][1].suit
            winner = max(cur_moves, key=lambda pc: pc[1].rank.to_int() if pc[1].suit == lead_suit else -1)[0]
            trick_pts = sum(_card_point(c) for _, c in cur_moves)
            points[winner] += trick_pts
            if not hands[self.player_tag_session]:
                break
            first_seat_idx = self.player_order.index(winner)
            cur_moves = []
            played_in_trick = 0
            if winner == self.player_tag_session:
                if not hands[winner]:
                    raise _SampleError("empty winner")
                card = self._policy_pick(hands[winner], [], hearts_broken)
                hands[winner].remove(card)
                cur_moves.append((winner, card))
                played_in_trick = 1
                if card.suit == Suit.HEARTS or card == QS:
                    hearts_broken = True
        # Moon flip
        shooters = [p for p, v in points.items() if v >= 26]
        zeros = [p for p, v in points.items() if v == 0]
        my_s = points[self.player_tag_session]
        if len(shooters) == 1 and len(zeros) == 3:
            return 0.0 if shooters[0] == self.player_tag_session else 26.0
        return my_s

    @staticmethod
    def _policy_pick(hand, trick_moves, hearts_broken):
        if not hand:
            raise _SampleError("empty")
        if not trick_moves:
            non_h = [c for c in hand if c.suit != Suit.HEARTS]
            if non_h and not hearts_broken:
                return SortCardsByRank(non_h)[0]
            return SortCardsByRank(hand)[0]
        lead = trick_moves[0][1].suit
        on_suit = [c for c in hand if c.suit == lead]
        if on_suit:
            cur_max = max(m.rank.to_int() for _, m in trick_moves if m.suit == lead)
            below = [c for c in on_suit if c.rank.to_int() < cur_max]
            if below:
                return SortCardsByRank(below, reverse=True)[0]
            return SortCardsByRank(on_suit)[0]
        if QS in hand:
            return QS
        non_pts = [c for c in hand if c.suit != Suit.HEARTS and c != QS]
        if non_pts:
            return SortCardsByRank(non_pts, reverse=True)[0]
        return SortCardsByRank(hand, reverse=True)[0]


if __name__ == "__main__":
    import sys
    config = sys.argv[1] if len(sys.argv) > 1 else "config.env"
    sys.argv = [sys.argv[0], config]
    with ManagedConnection() as conn:
        games = RunMultipleGames(
            conn, GameType.ANY,
            [TimAdaptivePlayer, RandomPlayer, RandomPlayer, RandomPlayer],
            num_games=10,
        )
        wins = sum(1 for g in games if "tim_adaptive" in str(g.winner))
        print(f"TimAdaptivePlayer vs 3x Random: {wins}/10")
