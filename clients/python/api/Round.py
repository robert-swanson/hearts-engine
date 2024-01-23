from typing import List, Dict, Set, Optional

from clients.python.api.Trick import Trick
from clients.python.api.types.Card import Card
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession


class Round:
    def __init__(self, round_idx: int, pass_direction: PassDirection, player_order: List[PlayerTagSession], cards_in_hand: List[Card]):
        self.round_idx = round_idx
        self.pass_direction = pass_direction
        self.player_order = player_order
        self.cards_in_hand = cards_in_hand

        self.donating_cards: List[Card] = []
        self.received_cards: List[Card] = []
        self.receiving_player: Optional[PlayerTagSession] = None
        self.donating_player: Optional[PlayerTagSession] = None
        self.tricks: List[Trick] = []

    def get_round_points(self) -> Dict[PlayerTagSession, int]:
        player_to_points = {player: 0 for player in self.player_order}
        for trick in self.tricks:
            if trick.winner is not None:
                player_to_points[trick.winner] += trick.get_current_point_value()
        return player_to_points

    def get_played_cards(self) -> Set[Card]:
        return {move.card for trick in self.tricks for move in trick.moves}


