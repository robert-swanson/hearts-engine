from typing import List, Optional, NamedTuple

from clients.python.api.types.Card import Suit, Card
from clients.python.api.types.PlayerTagSession import PlayerTagSession


class Move(NamedTuple):
    player: PlayerTagSession
    card: Card

    def __repr__(self):
        return self.card.__repr__()


class Trick:
    def __init__(self, trick_idx: int, player_order: List[PlayerTagSession]):
        self.trick_idx = trick_idx
        self.player_order = player_order

        self.moves: List[Move] = []
        self.winner: Optional[PlayerTagSession] = None

    def __repr__(self):
        if self.winner is None:
            return f"[{self.moves}]"
        else:
            return f"[{self.moves}] won by {self.winner}"

    def get_suit(self) -> Optional[Suit]:
        if len(self.moves) == 0:
            return None
        else:
            return self.moves[0].card.suit

    def get_current_point_value(self) -> int:
        return sum(move.card.get_point_value() for move in self.moves)
