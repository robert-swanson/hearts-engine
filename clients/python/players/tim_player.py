import time
from random import shuffle
from typing import List, Dict

from clients.python.api.Trick import Trick
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.SessionHelpers import MakeAndRunMultipleSessions, RunGame, MakeSession, MakeAndRunSession, WaitForAllSessionsToFinish, \
    RunMultipleGames
from clients.python.api.Player import Player
from clients.python.api.Round import Round
from clients.python.api.Game import Game
from clients.python.api.types.Card import Card
from clients.python.players.random_player import RandomPlayer
from clients.python.util.Constants import GameType
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession


class TimPlayer(Player):
    player_tag = "tim_ai"

    def __init__(self, player_tag_session: PlayerTagSession):
        super().__init__(player_tag_session)
        self.hand = []

    # Game
    def initialize_for_game(self, game: Game) -> None:
        print("New Game", game.player_order)
        pass

    def handle_end_game(self, players_to_points: dict[PlayerTagSession, int], winner: PlayerTagSession) -> None:
        print("Game end:",players_to_points)
        pass

    # Round
    def handle_new_round(self, round: Round) -> None:
        print(f"New Round: {round.round_idx}")
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


# if __name__ == '__main__':
#     players = [TimPlayer, RandomPlayer, RandomPlayer, RandomPlayer]
#     total_games = 0
#     games_won = 0
#     start_time = time.time()

#     with ManagedConnection("rob_player") as connection:
#         games = RunMultipleGames(connection, GameType.ANY, players, 100)
#         for game_result in games:
#             if "tim_ai" in str(game_result[0].winner):
#                 games_won += 1
#             total_games += 1

#     print(f"Games won: {games_won}/{total_games} ({games_won / total_games * 100}%)")
#     print(f"Time: {time.time() - start_time}")

# To play against another computer
if __name__ == '__main__':
    with ManagedConnection() as connection:
        for i in range(10):
            sessions = MakeAndRunMultipleSessions(connection, GameType.ANY, TimPlayer, 2)
            time.sleep(3)
        WaitForAllSessionsToFinish()
        print(sessions[0].game_results.winner)