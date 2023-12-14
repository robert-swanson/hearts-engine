import json
import threading

from clients.python.api.ManagedConnection import SessionID, ManagedConnection
from clients.python.player.Game import Game, ActiveGame
from clients.python.player.Messenger import Messenger
from clients.python.player.Round import Round
from clients.python.player.Player import Player
from clients.python.types.Constants import GameType, Tags, ClientMsgTypes, ServerStatus, ServerMsgTypes
from clients.python.types.PassDirection import PassDirection


class GameSession(Messenger):
    def __init__(self, connection: ManagedConnection, game_type: GameType, player: Player):
        self.connection = connection
        self.game_type = game_type
        self.player = player
        self.session_id = self.setup()
        connection.add_session(self.session_id)

        self.current_round = None

    def __del__(self):
        if hasattr(self, "session_id") and self.session_id is not None:
            self.connection.end_session(self.session_id)

    @staticmethod
    def SpawnNewGameSessionThread(connection: ManagedConnection, game_type: GameType, player: Player) \
            -> threading.Thread:
        session = GameSession(connection, game_type, player)
        return threading.Thread(target=session.run_game)

    def setup(self) -> SessionID:
        session_request = {
            Tags.TYPE: ClientMsgTypes.REQUEST_GAME_REQUEST,
            Tags.GAME_TYPE: self.game_type.value
        }

        self.connection.send(session_request)
        setup = self.connection.receive_status(ServerStatus.SUCCESS, ServerMsgTypes.GAME_SESSION_RESPONSE)
        return setup[Tags.SESSION_ID]

    def receive(self) -> json:
        return self.connection.receive_from_session(self.session_id)

    def receive_type(self, expected_msg_type: str) -> json:
        response = self.receive()
        assert response[Tags.TYPE] == expected_msg_type, \
            f"Expected message type {expected_msg_type}, got {response[Tags.TYPE]}"
        return response

    def receive_status(self, expected_status: str, expected_msg_type: str) -> json:
        response = self.receive_type(expected_msg_type)
        assert response[Tags.STATUS] == expected_status, \
            f"Expected status {expected_status}, got {response[Tags.STATUS]}"
        return response

    def get_next_message_type(self) -> str:
        return self.connection.get_next_message_type_for_session(self.session_id)

    def send(self, json_data: json):
        self.connection.send_to_session(self.session_id, json_data)

    def run_game(self):
        game = ActiveGame(self, self.player)
        game.run_game(self.player)

