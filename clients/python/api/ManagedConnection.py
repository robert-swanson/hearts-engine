import json
import threading
from typing import Dict, Optional, Set, List

from clients.python.api.Connection import Connection
from clients.python.types.Constants import SERVER_IP, SERVER_PORT
from clients.python.types.PlayerTag import PlayerTag

SessionID = str


class ManagedConnection(Connection):
    def __init__(self, player_tag: PlayerTag, ip=SERVER_IP, port=SERVER_PORT):
        super().__init__(player_tag, ip, port)

        self.session_lock = threading.Lock()
        self.message_received_condition = threading.Condition()
        self.id_to_received_messages: Dict[SessionID, List[json]] = {}
        self.waiting_sessions: Set[SessionID] = set()
        self.receiver_thread: Optional[threading.Thread] = None

    def add_session(self, session_id: SessionID):
        self.id_to_received_messages[session_id] = []

    def end_session(self, session_id: SessionID):
        self.id_to_received_messages.pop(session_id)

    def receive_from_session(self, session_id: SessionID) -> json:
        assert session_id not in self.waiting_sessions, f"Session {session_id} already waiting for message"
        self._start_receiver_thread()

        self.waiting_sessions.add(session_id)
        with self.message_received_condition:
            while len(self.id_to_received_messages[session_id]) == 0:
                self.message_received_condition.wait()
        self.waiting_sessions.remove(session_id)

        return self.id_to_received_messages[session_id].pop(0)

    def _receive_loop(self):
        while len(self.waiting_sessions) > 0:
            message = self.receive()
            session_id = message["session_id"]
            with self.message_received_condition:
                self.id_to_received_messages[session_id].append(message)
                self.message_received_condition.notify_all()
        self.receiver_thread = None

    def _start_receiver_thread(self):
        if self.receiver_thread is not None:
            return
        receiver_thread = threading.Thread(target=self._receive_loop)
        receiver_thread.start()

    def send_to_session(self, session_id: SessionID, json_data: json) -> None:
        json_data["session_id"] = session_id
        self.send(json_data)
