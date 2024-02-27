import time
from random import shuffle
from typing import List, Dict

from clients.python.api.Trick import Trick
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.PlayerGameSession import ObjectiveGameFromSessions, ObjectiveGamesFromSessions
from clients.python.api.networking.SessionHelpers import MakeAndRunMultipleSessions, WaitForAllSessionsToFinish, RunGame, RunMultipleGames
from clients.python.api.Player import Player
from clients.python.api.Round import Round
from clients.python.api.Game import Game, ObjectiveGame
from clients.python.api.types.Card import Card
from clients.python.util.Constants import GameType
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession


class RandomPlayer(Player):
    player_tag = "random_player"

    def __init__(self, player_tag_session: PlayerTagSession):
        super().__init__(player_tag_session)
        self.hand = []

    # Game
    def initialize_for_game(self, game: Game) -> None:
        pass

    def handle_end_game(self, players_to_points: dict[PlayerTagSession, int], winner: PlayerTagSession) -> None:
        pass

    # Round
    def handle_new_round(self, round: Round) -> None:
        self.hand = round.cards_in_hand

    def handle_finished_round(self, round: Round, round_points: Dict[PlayerTagSession, int]) -> None:
        pass

    def get_cards_to_pass(self, pass_dir: PassDirection, receiving_player: PlayerTagSession) -> List[Card]:
        shuffle(self.hand)
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
        shuffle(legal_moves)
        return legal_moves[0]


if __name__ == '__main__':
    player_clss = [RandomPlayer, RandomPlayer, RandomPlayer, RandomPlayer]
    with ManagedConnection() as connection:
        game_results = RunMultipleGames(connection, GameType.ANY, player_clss, 4)
        for result in game_results:
            result.print_results()

# if __name__ == '__main__':
#     with (ManagedConnection(timeout_s=30) as connection):
#         game_sessions = MakeAndRunMultipleSessions(connection, GameType.ANY, RandomPlayer, 11, timeout_s=2)
#         WaitForAllSessionsToFinish()
#         games = ObjectiveGamesFromSessions(game_sessions)
#         for game in games:
#             game.print_results()
#
