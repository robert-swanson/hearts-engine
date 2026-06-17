import sys
from pathlib import Path
from typing import List, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from clients.python.api.Player import Player
from clients.python.api.Round import Round
from clients.python.api.Trick import Trick
from clients.python.api.Game import Game
from clients.python.api.types.Card import Card
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession


class DeterministicPlayer(Player):
    """Always plays/passes the alphabetically smallest legal card."""
    player_tag = "deterministic_player"

    def __init__(self, player_tag_session: PlayerTagSession):
        super().__init__(player_tag_session)
        self.hand = []

    def initialize_for_game(self, game: Game) -> None:
        pass

    def handle_end_game(self, players_to_points: dict[PlayerTagSession, int], winner: PlayerTagSession) -> None:
        pass

    def handle_new_round(self, round: Round) -> None:
        self.hand = round.cards_in_hand

    def handle_finished_round(self, round: Round, round_points: Dict[PlayerTagSession, int]) -> None:
        pass

    def get_cards_to_pass(self, pass_dir: PassDirection, receiving_player: PlayerTagSession) -> List[Card]:
        return sorted(self.hand, key=repr)[:3]

    def receive_passed_cards(self, cards: List[Card], pass_dir: PassDirection, donating_player: PlayerTagSession) -> None:
        pass

    def handle_new_trick(self, trick: Trick) -> None:
        pass

    def handle_finished_trick(self, trick: Trick, winning_player: PlayerTagSession) -> None:
        pass

    def handle_move(self, trick: Trick, player: PlayerTagSession, card: Card,
                    report_latency_ms=None, decided_move_latency_ms=None) -> None:
        pass

    def get_move(self, trick: Trick, legal_moves: List[Card], move_request_latency_ms=None) -> Card:
        return min(legal_moves, key=repr)
