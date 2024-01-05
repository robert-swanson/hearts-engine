import json
import threading
from typing import Dict, TypeVar, Type, List, Optional, Union

from clients.python.api.Game import ActiveGame
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.Messenger import Messenger
from clients.python.players.Player import Game
from clients.python.types.Constants import GameType, Tags, ClientMsgTypes
from clients.python.types.PlayerTagSession import PlayerTagSession, PlayerTag
from clients.python.types.logger import log_message, log

Player_T = TypeVar('Player_T', bound='Player')


class GameSession(Messenger):
    def __init__(self, connection: ManagedConnection, player_tag: Union[PlayerTag, str], game_type: GameType, player_cls: Type[Player_T]):
        self.connection = connection
        self.game_type = game_type
        self.player_tag = player_tag if type(player_tag) is PlayerTag else PlayerTag(str(player_tag))

        self._next_seqnum = 0
        self._usage_lock = threading.Lock()
        self._seqnum_to_pending_received_message: Dict[int, json] = {}

        session_request = {
            Tags.TYPE: ClientMsgTypes.REQUEST_GAME_SESSION,
            Tags.PLAYER_TAG: self.player_tag,
            Tags.SEQ_NUM: self._get_seqnum_and_increment(),
            Tags.GAME_TYPE: self.game_type.value
        }
        response = connection.request_session(session_request)
        assert response[Tags.SEQ_NUM] == self._get_seqnum_and_increment()
        self.session_id = response[Tags.SESSION_ID]

        self.current_round = None
        self.player_session = PlayerTagSession(self.player_tag, self.session_id)
        self.player = player_cls(self.player_session)
        self.game_results: Optional[Game] = None

    def _get_seqnum_and_increment(self) -> int:
        next_seq_num = self._next_seqnum
        self._next_seqnum += 1
        return next_seq_num

    def __del__(self):
        if hasattr(self, "session_id") and self.session_id is not None:
            self.connection.end_session(self.session_id)

    def receive(self) -> json:
        if self._next_seqnum in self._seqnum_to_pending_received_message:
            return self._seqnum_to_pending_received_message.pop(self._next_seqnum)
        with self._usage_lock:
            while True:
                msg = self.connection.receive_from_session(self.session_id)
                msg_seqnum = msg[Tags.SEQ_NUM]
                if msg_seqnum == self._next_seqnum:
                    self._next_seqnum += 1
                    log_message("Processed", msg, True)
                    return msg
                else:
                    assert msg_seqnum > self._next_seqnum and msg_seqnum not in self._seqnum_to_pending_received_message, \
                        f"Received duplicate message with seqnum {msg_seqnum}"
                    log(
                        f"Queuing message {self.session_id}.{msg_seqnum} while waiting for {self.session_id}.{self._next_seqnum}")
                    self._seqnum_to_pending_received_message[msg_seqnum] = msg

    def receive_type(self, expected_msg_type: str) -> json:
        msg = self.receive()
        assert msg[Tags.TYPE] == expected_msg_type, \
            f"{self.session_id}.{msg[Tags.SEQ_NUM]} expected message type '{expected_msg_type}', but got '{msg[Tags.TYPE]}'"
        return msg

    def receive_status(self, expected_status: str, expected_msg_type: str) -> json:
        response = self.receive_type(expected_msg_type)
        assert response[Tags.STATUS] == expected_status, \
            f"Expected mStatus {expected_status}, got {response[Tags.STATUS]}"
        return response

    def get_next_message_type(self) -> str:
        return self.connection.get_next_message_type_for_session(self.session_id)

    def send(self, json_data: json):
        with self._usage_lock:
            json_data[Tags.SEQ_NUM] = self._get_seqnum_and_increment()
            self.connection.send_to_session(self.session_id, json_data)

    def run_game(self):
        game = ActiveGame(self, self.player)
        game.run_game(self.player)
        self.game_results = game

    def get_results(self) -> Game:
        return self.game_results

    def __repr__(self):
        return f"{self.player_session} (next {self.session_id}.{self._next_seqnum})"
