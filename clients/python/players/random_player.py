from typing import List, Dict

from clients.python.api.Trick import Trick
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.PlayerGameSession import GameSession
from clients.python.api.networking.SessionHelpers import MakeAndRunMultipleSessions, WaitForAllSessionsToFinish
from clients.python.players.Player import Player, Game, Round
from clients.python.types.Card import Card
from clients.python.types.Constants import GameType
from clients.python.types.PassDirection import PassDirection
from clients.python.types.PlayerTagSession import PlayerTagSession
from clients.python.types.logger import log


class RandomPlayer(Player):
    def __init__(self, player_tag: PlayerTagSession):
        super().__init__(player_tag)
        self.hand = []

    # Game
    def initialize_for_game(self, game: Game) -> None:
        log(f"Starting game for {self.player_tag}")

    def handle_end_game(self, players_to_points: dict[PlayerTagSession, int], winner: PlayerTagSession) -> None:
        log(f"Ending game for {self.player_tag}")

    # Round
    def handle_new_round(self, round: Round) -> None:
        self.hand = round.cards_in_hand

    def handle_finished_round(self, round: Round, round_points: Dict[PlayerTagSession, int]) -> None:
        pass

    def get_cards_to_pass(self, pass_dir: PassDirection, receiving_player: PlayerTagSession) -> List[Card]:
        return self.hand[:3]

    def receive_passed_cards(self, cards: List[Card], pass_dir: PassDirection, donating_player: PlayerTagSession) -> None:
        pass

    # Trick
    def handle_new_trick(self, trick: Trick) -> None:
        pass

    def handle_finished_trick(self, trick: Trick, winning_player: PlayerTagSession) -> None:
        pass

    # Moves
    def handle_move(self, player: PlayerTagSession, card: Card) -> None:
        pass

    def get_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
        return legal_moves[0]


if __name__ == '__main__':
    for g in range(2):
        with ManagedConnection("random_player") as connection:
            MakeAndRunMultipleSessions(connection, GameType.ANY, RandomPlayer, 4)
            MakeAndRunMultipleSessions(connection, GameType.ANY, RandomPlayer, 4)

