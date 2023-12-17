import json
from enum import Enum
from socket import socket, AF_INET, SOCK_STREAM
from typing import List

from clients.python.types.Constants import SERVER_IP, SERVER_PORT, LOG_ALL_RECEIVED_MESSAGES, LOG_ALL_SENT_MESSAGES, \
    Tags, ClientMsgTypes, ServerMsgTypes, \
    ServerStatus
from clients.python.types.PlayerTag import PlayerTag


class ConnectionStatus(Enum):
    CONNECTED = 0
    DISCONNECTED = 1


class Connection:
    def __init__(self, player_tag: PlayerTag, ip=SERVER_IP, port=SERVER_PORT):
        self.player_tag = player_tag
        self.host = ip
        self.port = port
        self.client_socket = socket(AF_INET, SOCK_STREAM)
        self.client_socket.connect((SERVER_IP, SERVER_PORT))
        self.status = ConnectionStatus.CONNECTED
        self.pending_messages: List[json] = []
        self.logging_session = -1

        self.setup()
        print(f"Connected player {player_tag} to {SERVER_IP}:{SERVER_PORT}")

    def receive(self) -> json:
        if len(self.pending_messages) == 0:
            data = self.client_socket.recv(1024)
            if data == b'':
                raise ConnectionError("Server closed connection while waiting for data")
            json_objects = self._get_json_objects(data.decode("utf-8"))
            json_data = json_objects[0]
            self.pending_messages = json_objects[1:]
        else:
            json_data = self.pending_messages.pop(0)

        if self.should_log_message(json_data, False):
            print("<<<<<<<")
            print(json.dumps(json_data, default=str, indent=1))
            print("<<<<<<<")
            print()

        return json_data

    @staticmethod
    def _get_json_objects(data: str) -> List:
        json_objects = []
        previous_split = 0
        while True:
            next_split = data[previous_split:].find("}{") + 1
            if next_split == 0:
                next_split = len(data)
            json_data = json.loads(data[previous_split:next_split])
            json_objects.append(json_data)
            if next_split == len(data):
                break
            previous_split = next_split
        return json_objects

    def receive_status(self, expected_status: str, expected_msg_type: str) -> json:
        response = self.receive()
        assert response[Tags.TYPE] == expected_msg_type, \
            f"Expected message type {expected_msg_type}, got {response[Tags.TYPE]}"
        assert response[Tags.STATUS] == expected_status, \
            f"Expected mStatus {expected_status}, got {response[Tags.STATUS]}"
        return response

    def send(self, json_data: json):
        json_str = json.dumps(json_data, default=str, indent=1)
        if self.should_log_message(json_data, True):
            print(">>>>>>")
            print(json_str)
            print(">>>>>>")
            print()
        bytes_sent = self.client_socket.send(json_str.encode("utf-8"))
        if bytes_sent != len(json_str):
            raise ConnectionError(f"Expected to send {len(json_str)} bytes, but sent {bytes_sent}")

    def should_log_message(self, json_data: json, sending: bool) -> bool:
        if sending and not LOG_ALL_SENT_MESSAGES:
            return False
        if not sending and not LOG_ALL_RECEIVED_MESSAGES:
            return False
        if Tags.SESSION_ID not in json_data:
            return False
        session_id = json_data[Tags.SESSION_ID]
        if self.logging_session == -1:
            self.logging_session = session_id
        return session_id == self.logging_session

    def setup(self):
        connection_request = {
            Tags.TYPE: ClientMsgTypes.REQUEST_CONNECTION,
            Tags.PLAYER_TAG: self.player_tag
        }
        self.send(connection_request)
        self.receive_status(ServerStatus.SUCCESS, ServerMsgTypes.CONNECTION_RESPONSE)
