import json
from enum import Enum
from socket import socket, AF_INET, SOCK_STREAM

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

        self.setup()
        print(f"Connected player {player_tag} to {SERVER_IP}:{SERVER_PORT}")

    def receive(self) -> json:
        data = self.client_socket.recv(1024)
        if data == b'':
            raise ConnectionError("Server closed connection while waiting for data")
        decoded_data = data.decode("utf-8")
        json_data = json.loads(decoded_data)
        if LOG_ALL_RECEIVED_MESSAGES:
            print("<<<<<<<")
            print(json.dumps(json_data, default=str, indent=1))
            print("<<<<<<<")
            print()
        return json_data

    def receive_status(self, expected_status: str, expected_msg_type: str) -> json:
        response = self.receive()
        assert response[Tags.TYPE] == expected_msg_type, \
            f"Expected message type {expected_msg_type}, got {response[Tags.TYPE]}"
        assert response[Tags.STATUS] == expected_status, \
            f"Expected status {expected_status}, got {response[Tags.STATUS]}"
        return response

    def send(self, json_data: json):
        json_str = json.dumps(json_data, default=str, indent=1)
        if LOG_ALL_SENT_MESSAGES:
            print(">>>>>>")
            print(json_str)
            print(">>>>>>")
            print()
        bytes_sent = self.client_socket.send(json_str.encode("utf-8"))
        if bytes_sent != len(json_str):
            raise ConnectionError(f"Expected to send {len(json_str)} bytes, but sent {bytes_sent}")

    def setup(self):
        connection_request = {
            Tags.TYPE: ClientMsgTypes.REQUEST_CONNECTION,
            Tags.PLAYER_TAG: self.player_tag
        }
        self.send(connection_request)
        self.receive_status(ServerStatus.SUCCESS, ServerMsgTypes.CONNECTION_RESPONSE)
