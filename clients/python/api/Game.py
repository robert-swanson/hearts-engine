from abc import ABC
from typing import List, Optional, Tuple

from clients.python.api.Round import Round, ObjectiveRound
from clients.python.api.types.PlayerTagSession import PlayerTagSession


class GameShared(ABC):
    def __init__(self, player_order: List[PlayerTagSession]):
        self.player_order = player_order
        self.winner: Optional[PlayerTagSession] = None
        self.players_to_points: dict[PlayerTagSession, int] = {}


class Game(GameShared):
    def __init__(self, player_order: List[PlayerTagSession]):
        super().__init__(player_order)
        self.rounds: List[Round] = []


class ObjectiveGame(Game):
    def __init__(self, player_games: List[Tuple[PlayerTagSession, Game]]):
        players = [player for player, _ in player_games]
        player_games = [(player, game) for player, game in player_games if game is not None and game.winner is not None]
        if len(player_games) == 0:
            self.winner = None
            self.player_order = players
            self.players_to_points = {player: None for player in self.player_order}
            self.rounds = []
            return
        fist_game = player_games[0][1]

        super().__init__(fist_game.player_order)

        self.winner: PlayerTagSession = fist_game.winner
        self.players_to_points: dict[PlayerTagSession, int] = fist_game.players_to_points
        self.rounds: List[ObjectiveRound] = []

        num_rounds = len(fist_game.rounds)
        round_to_player_rounds: List[List[Tuple[PlayerTagSession, Round]]] = [[] for i in range(len(fist_game.rounds))]

        for player, game in player_games:
            assert game.winner == self.winner, f"All player games must have the same winner but got {self.winner} and {game.winner}"
            assert game.player_order == self.player_order, "All player games must have the same player order"
            assert game.players_to_points == self.players_to_points, "All player games must have the same players to points"
            assert len(game.rounds) == num_rounds, "All player games must have the same number of rounds"

            for i, round in enumerate(game.rounds):
                round_to_player_rounds[i].append((player, round))
        self.rounds = [ObjectiveRound(player_rounds) for player_rounds in round_to_player_rounds]

    def print_results(self):
        if self.winner is None:
            print(f"All players failed to complete the game: {self.players_to_points}")
            return

        rankings = sorted(self.players_to_points, key=self.players_to_points.get, reverse=True)
        print("Game Results:")
        for i, player in enumerate(rankings):
            print(f"{i + 1}. {player} with {self.players_to_points[player]} points")
