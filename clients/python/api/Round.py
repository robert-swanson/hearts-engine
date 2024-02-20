from abc import ABC, abstractmethod
from typing import List, Dict, Set, Optional, Tuple

from clients.python.api.Trick import Trick
from clients.python.api.types.Card import Card
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession


class RoundShared(ABC):
    def __init__(self, round_idx: int, pass_direction: PassDirection, player_order: List[PlayerTagSession]):
        self.round_idx = round_idx
        self.pass_direction = pass_direction
        self.player_order = player_order
        self.tricks: List[Trick] = []


class Round(RoundShared):
    def __init__(self, round_idx: int, pass_direction: PassDirection, player_order: List[PlayerTagSession], cards_in_hand: List[Card]):
        super().__init__(round_idx, pass_direction, player_order)

        self.cards_in_hand = cards_in_hand
        self.donating_cards: List[Card] = []
        self.received_cards: List[Card] = []
        self.receiving_player: Optional[PlayerTagSession] = None
        self.donating_player: Optional[PlayerTagSession] = None

    def get_round_points(self) -> Dict[PlayerTagSession, int]:
        player_to_points = {player: 0 for player in self.player_order}
        for trick in self.tricks:
            if trick.winner is not None:
                player_to_points[trick.winner] += trick.get_current_point_value()
        return player_to_points

    def get_played_cards(self) -> Set[Card]:
        return {move.card for trick in self.tricks for move in trick.moves}


class ObjectiveRound(RoundShared):
    def __init__(self, player_rounds: List[Tuple[PlayerTagSession, Round]]):
        p1 = player_rounds[0][1]
        super().__init__(p1.round_idx, p1.pass_direction, p1.player_order)
        self.player_info: Dict[PlayerTagSession, Optional[Round]] = {player: None for player in p1.player_order}

        for player, info in player_rounds:
            self.player_info[player] = info
            assert info.round_idx == self.round_idx, "All player rounds must have the same round index"
            assert info.pass_direction == self.pass_direction, "All player rounds must have the same pass direction"
            assert info.player_order == self.player_order, "All player rounds must have the same player order"
            self.player_info[player] = info

