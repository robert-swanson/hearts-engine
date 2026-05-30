import json
import threading
from collections import defaultdict
from concurrent.futures._base import LOGGER
from datetime import datetime, timedelta
from typing import Dict, Optional, Set, List

from clients.python.api.networking.Connection import Connection
from clients.python.util.Constants import Tags, ServerMsgTypes, ServerStatus, MACRO_TIMEOUT, MICRO_TIMEOUT
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

    def pop_next(self, session_id: SessionID) -> Optional["json"]:
        with self._modify_lock:
            received_msgs = self._id_to_received_messages[session_id]
            return None if len(received_msgs) == 0 else received_msgs.pop(0)

    def peek_next(self, session_id: SessionID) -> json:
        return self._id_to_received_messages[session_id][0]

    def append(self, session_id: SessionID, msg: json):
        with self._modify_lock:
            self._id_to_received_messages[session_id].append(msg)


class ManagedConnection(Connection):
    def __init__(self, ip=SERVER_IP, port=SERVER_PORT, timeout_s=10):
        super().__init__(ip, port, min(timeout_s, MICRO_TIMEOUT))
        self.connection_timeout_s = timeout_s

        # Threading
        self.session_lock = threading.Lock()
        self.receiver_thread_lock = threading.Lock()

        self.game_finished_condition = threading.Condition()
        self.num_running_sessions = 0
        self.num_running_sessions_lock = threading.Lock()

        # Session management
        self.message_store = MessageStore()
        self.last_msg_time = datetime.now()
        # Per-session condition variables. The receiver thread used to wake *every*
        # waiting game thread on *every* message (a single global condition +
        # notify_all). With up to MAX_CONCURRENT_GAMES_PER_TEAM sessions sharing one
        # connection that is an O(N) thundering herd per message — under the GIL it
        # makes the client fall behind the move deadline, so the server times out and
        # auto-plays for it. Waking only the one session that actually received a
        # message keeps the client responsive under high concurrency.
        self._session_conditions: Dict[SessionID, threading.Condition] = {}
        self._session_conditions_lock = threading.Lock()
        self.waiting_sessions: Set[SessionID] = set()
        self._waiting_sessions_lock = threading.Lock()
        self.receiver_thread: Optional[threading.Thread] = None

    def request_session(self, request: json, timeout_s=10) -> json:
        with self.session_lock:
            self.send(request)
            game_session_response = self.receive_from_session(UNASSIGNED_SESSION, timeout_s)
            assert game_session_response[Tags.TYPE] == ServerMsgTypes.GAME_SESSION_RESPONSE
            assert game_session_response[Tags.STATUS] == ServerStatus.SUCCESS
            return game_session_response

    def end_session(self, session_id: SessionID):
        self.message_store.remove_session(session_id)
        with self._session_conditions_lock:
            self._session_conditions.pop(session_id, None)

    def _cond_for(self, session_id: SessionID) -> threading.Condition:
        """Return (creating if needed) the condition variable for one session."""
        with self._session_conditions_lock:
            cond = self._session_conditions.get(session_id)
            if cond is None:
                cond = threading.Condition()
                self._session_conditions[session_id] = cond
            return cond

    def deliver_to_session(self, session_id: SessionID, message: json) -> None:
        """Queue a message for a session and wake only that session's waiter."""
        cond = self._cond_for(session_id)
        with cond:
            self.message_store.append(session_id, message)
            cond.notify_all()

    def _wake_all_sessions(self) -> None:
        """Wake every session's waiter (used when the connection drops)."""
        with self._session_conditions_lock:
            conds = list(self._session_conditions.values())
        for cond in conds:
            with cond:
                cond.notify_all()

    def _retrieve_next_message_for_session(self, session_id: SessionID, timeout_s: int):
        with self._waiting_sessions_lock:
            assert session_id not in self.waiting_sessions, f"Session {session_id} already waiting for message"
            self.waiting_sessions.add(session_id)
        try:
            self._start_receiver_thread()
            start_time = datetime.now()
            cond = self._cond_for(session_id)
            with cond:
                # Wake only when *this* session gets a message — no thundering herd.
                while len(self.message_store.get_all(session_id)) == 0 and \
                        timeout_s > (datetime.now() - start_time).seconds:
                    cond.wait(timeout=timeout_s)
        finally:
            with self._waiting_sessions_lock:
                self.waiting_sessions.discard(session_id)

    def receive_from_session(self, session_id: SessionID, timeout_s: int) -> json:
        self._retrieve_next_message_for_session(session_id, timeout_s)
        msg = self.message_store.pop_next(session_id)
        if msg is None:
            raise ConnectionError(f"Timeout while waiting for message from session {session_id} (waited {timeout_s} seconds)")
        self.logger.log(f"Sending message with seqnum {msg[Tags.SEQ_NUM]} to session {session_id}")
        return msg

    def get_next_message_type_for_session(self, session_id: SessionID, timeout_s: int) -> str:
        self._retrieve_next_message_for_session(session_id, timeout_s)
        return self.message_store.peek_next(session_id)["type"]

    def _receive_loop(self):
        self.logger.log("Starting receiver thread")
        with self.receiver_thread_lock:
            try:
                while True:
                    message = self.receive()
                    if message is None:
                        # Only exit when nobody is waiting AND the connection has been
                        # idle long enough to be considered dead.  Exiting while
                        # waiting_sessions is merely temporarily empty (between game
                        # batches) would leave the next session without a reader.
                        if len(self.waiting_sessions) == 0:
                            if self.connection_timeout_s is not None and \
                                    (datetime.now() - self.last_msg_time) >= timedelta(seconds=self.connection_timeout_s):
                                break
                        elif self.connection_timeout_s is not None and \
                                (datetime.now() - self.last_msg_time) >= timedelta(seconds=self.connection_timeout_s):
                            raise ConnectionError(f"Connection timed out while waiting for message, waiting for {self.waiting_sessions}")
                        continue
                    else:
                        self.last_msg_time = datetime.now()

                    self._handle_msg(message)
            except ConnectionError:
                # Server closed the connection — notify any waiting sessions so they
                # see the disconnect promptly rather than waiting for their timeout.
                self._wake_all_sessions()
            self.receiver_thread = None
        self.logger.log("Ending receiver thread")
        if len(self.waiting_sessions) > 0:
            self._start_receiver_thread()

    def _handle_msg(self, message: json):
        session_id = message[Tags.SESSION_ID]
        if message[Tags.TYPE] == ServerMsgTypes.GAME_SESSION_RESPONSE:
            session_id = UNASSIGNED_SESSION
        self.deliver_to_session(session_id, message)
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
