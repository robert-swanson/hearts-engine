from clients.python.Connection import Connection
from clients.python.constants import GameType


class GameSession:
    def __init__(self, connection: Connection, game_type: GameType):
        self.connection = connection
        self.game_type = game_type

        self.setup()

    def setup(self):
        pass
