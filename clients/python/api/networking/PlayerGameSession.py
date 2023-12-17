import json
import threading

from clients.python.api.networking.ManagedConnection import SessionID, ManagedConnection
from clients.python.api.Game import ActiveGame
from clients.python.api.networking.Messenger import Messenger
from clients.python.players.Player import Player
from clients.python.types.Constants import GameType, Tags, ClientMsgTypes, ServerStatus, ServerMsgTypes


class GameSession(Messenger):
    def __init__(self, connection: ManagedConnection, game_type: GameType, player: Player):
        self.connection = connection
        self.game_type = game_type
        self.player = player

        session_request = {
            Tags.TYPE: ClientMsgTypes.REQUEST_GAME_SESSION,
            Tags.GAME_TYPE: self.game_type.value
        }
        self.session_id = connection.request_session(session_request)

        self.current_round = None

    def __del__(self):
        if hasattr(self, "session_id") and self.session_id is not None:
            self.connection.end_session(self.session_id)

    @staticmethod
    def SpawnNewGameSessionThread(connection: ManagedConnection, game_type: GameType, player: Player) \
            -> threading.Thread:
        session = GameSession(connection, game_type, player)
        return threading.Thread(target=session.run_game)

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
            f"Expected mStatus {expected_status}, got {response[Tags.STATUS]}"
        return response

    def get_next_message_type(self) -> str:
        return self.connection.get_next_message_type_for_session(self.session_id)

    def send(self, json_data: json):
        self.connection.send_to_session(self.session_id, json_data)

    def run_game(self):
        game = ActiveGame(self, self.player)
        game.run_game(self.player)

