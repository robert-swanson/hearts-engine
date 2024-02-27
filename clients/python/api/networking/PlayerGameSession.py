import json
import threading
from typing import Dict, TypeVar, Type, Optional, Union, List, Set, Tuple

from clients.python.api.Game import Game, ObjectiveGame
from clients.python.ActiveGameFlow import ActiveGame
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.Messenger import Messenger
from clients.python.api.types.PlayerTagSession import PlayerTag, PlayerTagSession
from clients.python.util.Constants import GameType, Tags, ClientMsgTypes, LOG_SESSIONS
from clients.python.util.Logging import SessionLogger

Player_T = TypeVar('Player_T', bound='Player')


class GameSession(Messenger):
    def __init__(self, connection: ManagedConnection, player_tag: Union[PlayerTag, str], game_type: GameType, player_cls: Type[Player_T],
                 lobby_code: str = "", timeout_s: int = 10):
        self.connection = connection
        self.game_type = game_type
        self.player_tag = player_tag if type(player_tag) is PlayerTag else PlayerTag(str(player_tag))
        self.lobby_code = lobby_code

        self._next_seqnum = 0
        self._usage_lock = threading.Lock()
        self._seqnum_to_pending_received_message: Dict[int, json] = {}

        session_request = {
            Tags.TYPE: ClientMsgTypes.REQUEST_GAME_SESSION,
            Tags.PLAYER_TAG: self.player_tag,
            Tags.LOBBY_CODE: lobby_code,
            Tags.SEQ_NUM: self._get_seqnum_and_increment(),
            Tags.GAME_TYPE: self.game_type.value
        }
        response = connection.request_session(session_request)
        assert response[Tags.SEQ_NUM] == self._get_seqnum_and_increment()
        self.session_id = response[Tags.SESSION_ID]
        self.message_print_logging_enabled = player_cls.message_print_logging_enabled
        self.logger = SessionLogger(self.player_tag, self.session_id) if LOG_SESSIONS else None
        self.timeout_s = timeout_s

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
                msg = self.connection.receive_from_session(self.session_id, self.timeout_s)
                msg_seqnum = msg[Tags.SEQ_NUM]
                if msg_seqnum == self._next_seqnum:
                    self._next_seqnum += 1
                    if self.logger is not None:
                        self.logger.log_message("Received", msg, True, also_print=self.message_print_logging_enabled)
                    return msg
                else:
                    assert msg_seqnum > self._next_seqnum and msg_seqnum not in self._seqnum_to_pending_received_message, \
                        f"Received duplicate message with seqnum {msg_seqnum}"
                    self.logger.log(
                        f"Queuing message {self.session_id}.{msg_seqnum} while waiting for {self.session_id}.{self._next_seqnum}", also_print=True)
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
        return self.connection.get_next_message_type_for_session(self.session_id, self.timeout_s)

    def send(self, json_data: json):
        with self._usage_lock:
            json_data[Tags.SEQ_NUM] = self._get_seqnum_and_increment()
            self.connection.send_to_session(self.session_id, json_data)
            if self.logger is not None:
                self.logger.log_message("Sent", json_data, True, also_print=self.message_print_logging_enabled)

    def run_game(self):
        self.connection.increment_num_running_games()
        game = None

        try:
            game = ActiveGame(self, self.player)
            game.run_game(self.player)
        except ConnectionError as e:
            print(f"Session {self.session_id} encountered a connection error: {e}")

        self.game_results = game

        self.connection.decrement_num_running_games()
        with self.connection.game_finished_condition:
            self.connection.game_finished_condition.notify_all()

    def get_results(self) -> Game:
        return self.game_results

    def __repr__(self):
        return f"{self.player_session} (next {self.session_id}.{self._next_seqnum})"


def ObjectiveGameFromSessions(player_game_sessions: List[GameSession]) -> ObjectiveGame:
    assert 0 < len(player_game_sessions) <= 4, f"Expected 1-4 player game sessions, got {len(player_game_sessions)}"
    return ObjectiveGame([(player_game_session.player_session, player_game_session.game_results) for player_game_session in player_game_sessions])


def ObjectiveGamesFromSessions(player_game_sessions: List[GameSession]) -> List[ObjectiveGame]:
    """
    Given a list of game sessions (that may include incomplete sessions and sessions from different games), return a list of ObjectiveGame objects
    :param player_game_sessions: List of GameSession objects
    :return: List of ObjectiveGame objects constructed as best possible from the information gathered from the game sessions

    Example:
        > with (ManagedConnection(timeout_s=30) as connection):
        >     game_sessions = MakeAndRunMultipleSessions(connection, GameType.ANY, RandomPlayer, 3, timeout_s=30)
        >     WaitForAllSessionsToFinish()
        >     games = ObjectiveGamesFromSessions(game_sessions)
        >     for game in games:
        >         game.print_results()
    """

    players_to_game_sessions: List[Tuple[List[PlayerTagSession], List[GameSession]]] = []

    for player_game_session in player_game_sessions:
        player_session = player_game_session.player_session
        for player_set, game_sessions in players_to_game_sessions:
            if player_session in player_set:
                game_sessions.append(player_game_session)
                break
        else:
            if player_game_session.game_results is None:
                continue
            players_to_game_sessions.append((player_game_session.game_results.player_order, [player_game_session]))

    return [ObjectiveGameFromSessions(game_sessions) for _, game_sessions in players_to_game_sessions]
