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
        p1 = player_games[0][1]
        super().__init__(p1.player_order)

        self.winner: PlayerTagSession = p1.winner
        self.players_to_points: dict[PlayerTagSession, int] = p1.players_to_points
        self.rounds: List[ObjectiveRound] = []

        num_rounds = len(p1.rounds)
        round_to_player_rounds: List[List[Tuple[PlayerTagSession, Round]]] = [[] for i in range(len(p1.rounds))]

        for player, game in player_games:
            assert game.winner == self.winner, "All player games must have the same winner"
            assert game.player_order == self.player_order, "All player games must have the same player order"
            assert game.players_to_points == self.players_to_points, "All player games must have the same players to points"
            assert len(game.rounds) == num_rounds, "All player games must have the same number of rounds"

            for i, round in enumerate(game.rounds):
                round_to_player_rounds[i].append((player, round))
        self.rounds = [ObjectiveRound(player_rounds) for player_rounds in round_to_player_rounds]
