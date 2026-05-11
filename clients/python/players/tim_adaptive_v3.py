"""
TimAdaptive v3 — same strategy as TimAdaptivePlayer, but uses the
bitfield rollout engine (`fast_rollout.py`) for the playout hot path.

Empirical speedup: ~4× over the list-based Card-object playout
(23K vs 6K playouts/sec). Same correctness — moon-flip-aware scoring,
same policy selection logic, same trust/effect/p-value gates.

Wins from speedup:
  - More paired samples per decision → tighter t-test
  - OR same samples in ~25% the budget → can run within tournament limit
"""
from __future__ import annotations
import time
from typing import Dict, List, Tuple

from clients.python.api.Trick import Trick
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.SessionHelpers import RunMultipleGames
from clients.python.api.types.Card import Card, Suit
from clients.python.api.types.PlayerTagSession import PlayerTagSession
from clients.python.players.random_player import RandomPlayer
from clients.python.players.tim_adaptive_player import (
    TimAdaptivePlayer, _SampleError,
)
from clients.python.players.fast_rollout import (
    card_to_bit, hand_to_bits, playout_bitfield,
)
from clients.python.util.Constants import GameType


QS = Card("QS")
POLICY_NAME_TO_IDX = {"max_duck": 0, "min_duck": 1, "strategic": 2}


class TimAdaptiveV3(TimAdaptivePlayer):
    player_tag = "tim_adaptive_v3"

    # We're 4× faster — can afford more samples for same wall time.
    search_budget_s: float = 0.5

    def _playout(
        self,
        my_first: Card,
        opp_hands: Dict[PlayerTagSession, List[Card]],
        trick: Trick,
    ) -> float:
        """Bitfield-based playout. Hands as 52-bit ints, no Card-object
        allocations in the hot loop."""
        # Build per-seat bitfields. Seat order matches player_order.
        my_seat = self.player_order.index(self.player_tag_session)
        seat_hands: List[int] = []
        for p in self.player_order:
            if p == self.player_tag_session:
                seat_hands.append(hand_to_bits(self._current_hand()))
            else:
                seat_hands.append(hand_to_bits(opp_hands[p]))

        if not (seat_hands[my_seat] & (1 << card_to_bit(my_first))):
            raise _SampleError("missing card")

        # Current trick (moves so far, by seat index).
        trick_moves: List[Tuple[int, int]] = []
        for m in trick.moves:
            seat = self.player_order.index(m.player)
            trick_moves.append((seat, card_to_bit(m.card)))

        first_seat_idx = (my_seat - len(trick.moves)) % 4

        # Prior round points (from completed tricks).
        prior_points: List[float] = [0.0] * 4
        if self.current_round is not None:
            rp = self.current_round.get_round_points()
            for p, pts in rp.items():
                if p in self.player_order:
                    idx = self.player_order.index(p)
                    prior_points[idx] = pts

        # Per-seat policy index.
        opp_policies: List[int] = []
        for p in self.player_order:
            if p == self.player_tag_session:
                opp_policies.append(POLICY_NAME_TO_IDX["strategic"])
            else:
                name, _ = self._best_policy_for(p)
                opp_policies.append(POLICY_NAME_TO_IDX.get(name, 2))

        hearts_broken = self.hearts_broken or (
            my_first.suit == Suit.HEARTS or my_first == QS
        )

        score = playout_bitfield(
            my_seat=my_seat,
            seat_hands=seat_hands,
            trick_moves=trick_moves,
            first_seat_idx=first_seat_idx,
            hearts_broken=hearts_broken,
            prior_points=prior_points,
            my_first_bit=card_to_bit(my_first),
            opp_policies=opp_policies,
            me_policy=POLICY_NAME_TO_IDX["strategic"],
        )
        if score >= 999:
            raise _SampleError("playout invalid state")
        return score


if __name__ == "__main__":
    import sys
    config = sys.argv[1] if len(sys.argv) > 1 else "config.env"
    sys.argv = [sys.argv[0], config]
    with ManagedConnection() as conn:
        games = RunMultipleGames(
            conn, GameType.ANY,
            [TimAdaptiveV3, RandomPlayer, RandomPlayer, RandomPlayer],
            num_games=5,
        )
        wins = sum(1 for g in games if "tim_adaptive_v3" in str(g.winner))
        print(f"TimAdaptiveV3 vs 3x Random: {wins}/5")
