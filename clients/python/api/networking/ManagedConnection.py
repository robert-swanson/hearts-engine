import json
import threading
from collections import defaultdict
from concurrent.futures._base import LOGGER
from datetime import datetime, timedelta
from typing import Dict, Optional, Set, List

from clients.python.api.networking.Connection import Connection
from clients.python.util.Constants import Tags, ServerMsgTypes, ServerStatus, MACRO_TIMEOUT
from clients.python.util.Env import SERVER_IP, SERVER_PORT

SessionID = int
UNASSIGNED_SESSION: SessionID = -1


class MessageStore:
    def __init__(self):
        self._id_to_received_messages: Dict[SessionID, list] = defaultdict(list)
        self._modify_lock = threading.Lock()

    def remove_session(self, session_id: SessionID):
        with self._modify_lock:
            assert self.get_all(session_id) == [], f"Session {session_id} still had unread messages when removed"
            self._id_to_received_messages.pop(session_id)

    def get_all(self, session_id: SessionID) -> list:
        return self._id_to_received_messages[session_id]

    def get_next(self, session_id: SessionID) -> json:
        return self._id_to_received_messages[session_id][0]

    def pop_next(self, session_id: SessionID) -> json:
        with self._modify_lock:
            return self._id_to_received_messages[session_id].pop(0)

    def peek_next(self, session_id: SessionID) -> json:
        return self._id_to_received_messages[session_id][0]

    def append(self, session_id: SessionID, msg: json):
        with self._modify_lock:
            self._id_to_received_messages[session_id].append(msg)


class ManagedConnection(Connection):
    def __init__(self, ip=SERVER_IP, port=SERVER_PORT):
        super().__init__(ip, port)

        # Threading
        self.session_lock = threading.Lock()
        self.receiver_thread_lock = threading.Lock()

        self.game_finished_condition = threading.Condition()
        self.num_running_sessions = 0
        self.num_running_sessions_lock = threading.Lock()

        # Session management
        self.message_store = MessageStore()
        self.last_msg_time = datetime.now()
        self.message_received_condition = threading.Condition()
        self.waiting_sessions: Set[SessionID] = set()
        self.receiver_thread: Optional[threading.Thread] = None

    def request_session(self, request: json) -> json:
        with self.session_lock:
            self.send(request)
            game_session_response = self.receive_from_session(UNASSIGNED_SESSION)
            assert game_session_response[Tags.TYPE] == ServerMsgTypes.GAME_SESSION_RESPONSE
            assert game_session_response[Tags.STATUS] == ServerStatus.SUCCESS
            return game_session_response

    def end_session(self, session_id: SessionID):
        self.message_store.remove_session(session_id)

    def _retrieve_next_message_for_session(self, session_id: SessionID):
        assert session_id not in self.waiting_sessions, f"Session {session_id} already waiting for message"
        self.waiting_sessions.add(session_id)
        self._start_receiver_thread()
        with self.message_received_condition:  # TODO: does this check once in case its waiting?
            while len(self.message_store.get_all(session_id)) == 0:
                self.message_received_condition.wait()
        self.waiting_sessions.remove(session_id)

    def receive_from_session(self, session_id: SessionID) -> json:
        self._retrieve_next_message_for_session(session_id)
        msg = self.message_store.pop_next(session_id)
        self.logger.log(f"Sending message with seqnum {msg[Tags.SEQ_NUM]} to session {session_id}")
        return msg

    def get_next_message_type_for_session(self, session_id: SessionID) -> str:
        self._retrieve_next_message_for_session(session_id)
        return self.message_store.peek_next(session_id)["type"]

    def _receive_loop(self):
        self.logger.log("Starting receiver thread")
        with self.receiver_thread_lock:
            while len(self.waiting_sessions) > 0:
                message = self.receive()
                if message is None:
                    if len(self.waiting_sessions) == 0:
                        break
                    elif MACRO_TIMEOUT is None or (datetime.now() - self.last_msg_time) < timedelta(seconds=MACRO_TIMEOUT):
                        continue
                    else:
                        raise ConnectionError(f"Timeout while waiting for message, waiting for {self.waiting_sessions}")
                else:
                    self.last_msg_time = datetime.now()

                self._handle_msg(message)

            self.receiver_thread = None
        self.logger.log("Ending receiver thread")

    def _handle_msg(self, message: json):
        session_id = message[Tags.SESSION_ID]
        with self.message_received_condition:
            if message[Tags.TYPE] == ServerMsgTypes.GAME_SESSION_RESPONSE:
                session_id = UNASSIGNED_SESSION
            self.message_store.append(session_id, message)
            self.message_received_condition.notify_all()
            self.logger.log(f"Appended message for session {session_id} (num pending: {len(self.message_store.get_all(session_id))})")

    def _start_receiver_thread(self):
        if self.receiver_thread is not None:
            return
        self.receiver_thread = threading.Thread(target=self._receive_loop)
        self.receiver_thread.start()

    def send_to_session(self, session_id: SessionID, json_data: json) -> None:
        json_data["session_id"] = session_id
        self.send(json_data)

    def increment_num_running_games(self):
        with self.num_running_sessions_lock:
            self.num_running_sessions += 1

    def decrement_num_running_games(self):
        with self.num_running_sessions_lock:
            self.num_running_sessions -= 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.receiver_thread is not None:
            self.receiver_thread.join()
        self.client_socket.close()
        return False
