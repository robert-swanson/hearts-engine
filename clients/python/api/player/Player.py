from abc import ABC
from typing import List

from clients.python.api.Round import Round
from clients.python.api.Trick import Trick
from clients.python.types.Card import Card
from clients.python.types.PassDirection import PassDirection
from clients.python.types.PlayerTag import PlayerTag


class Player(ABC):
    def __init__(self, player_tag: PlayerTag):
        self.player_tag = player_tag

    # Round
    def handle_new_round(self, round: Round) -> None:
        pass

    def handle_finished_round(self, round: Round) -> None:
        pass

    def get_cards_to_pass(self, pass_dir: PassDirection, receiving_player: PlayerTag) -> List[Card]:
        pass

    def receive_passed_cards(self, cards: List[Card], pass_dir: PassDirection, donating_player: PlayerTag) -> None:
        pass

    # Trick
    def handle_new_trick(self, trick: Trick) -> None:
        pass

    def handle_finished_trick(self, trick: Trick) -> None:
        pass

    # Moves
    def handle_move(self, player: PlayerTag, card: Card) -> None:
        """Handle a move from any player (including this one)"""
        pass

    def get_move(self, trick: Trick) -> Card:
        pass
