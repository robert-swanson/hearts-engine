import json
import threading
from collections import defaultdict
from typing import Dict, Optional, Set, List

from clients.python.api.networking.Connection import Connection
from clients.python.types.Constants import SERVER_IP, SERVER_PORT, Tags, ServerMsgTypes, ServerStatus
from clients.python.types.PlayerTagSession import PlayerTag
from clients.python.types.logger import log_message

SessionID = int
UNASSIGNED_SESSION: SessionID = -1


class ManagedConnection(Connection):
    def __init__(self, player_tag: PlayerTag, ip=SERVER_IP, port=SERVER_PORT):
        super().__init__(player_tag, ip, port)

        self.session_lock = threading.Lock()

        self.message_received_condition = threading.Condition()
        self.id_to_received_messages: Dict[SessionID, List[json]] = defaultdict(list)
        self.waiting_sessions: Set[SessionID] = set()
        self.receiver_thread: Optional[threading.Thread] = None

    def request_session(self, request: json) -> SessionID:
        with self.session_lock:
            self.send(request)
            game_session_response = self.receive_from_session(UNASSIGNED_SESSION)
            assert game_session_response[Tags.TYPE] == ServerMsgTypes.GAME_SESSION_RESPONSE
            assert game_session_response[Tags.STATUS] == ServerStatus.SUCCESS
            session_id = game_session_response[Tags.SESSION_ID]
            self.id_to_received_messages[session_id] = []
            return game_session_response

    def end_session(self, session_id: SessionID):
        self.id_to_received_messages.pop(session_id)

    def _retrieve_next_message_for_session(self, session_id: SessionID):
        assert session_id not in self.waiting_sessions, f"Session {session_id} already waiting for message"
        self.waiting_sessions.add(session_id)
        self._start_receiver_thread()
        with self.message_received_condition:  # TODO: does this check once in case its waiting?
            while len(self.id_to_received_messages[session_id]) == 0:
                self.message_received_condition.wait()
        self.waiting_sessions.remove(session_id)

    def receive_from_session(self, session_id: SessionID) -> json:
        self._retrieve_next_message_for_session(session_id)
        return self.id_to_received_messages[session_id].pop(0)

    def get_next_message_type_for_session(self, session_id: SessionID) -> str:
        self._retrieve_next_message_for_session(session_id)
        return self.id_to_received_messages[session_id][0]["type"]

    def _receive_loop(self):
        while len(self.waiting_sessions) > 0:
            message = self.receive()
            session_id = message[Tags.SESSION_ID]
            with self.message_received_condition:
                if message[Tags.TYPE] == ServerMsgTypes.GAME_SESSION_RESPONSE:
                    session_id = UNASSIGNED_SESSION
                self.id_to_received_messages[session_id].append(message)
                self.message_received_condition.notify_all()
        self.receiver_thread = None

    def _start_receiver_thread(self):
        if self.receiver_thread is not None:
            return
        self.receiver_thread = threading.Thread(target=self._receive_loop)
        self.receiver_thread.start()

    def send_to_session(self, session_id: SessionID, json_data: json) -> None:
        json_data["session_id"] = session_id
        self.send(json_data)
