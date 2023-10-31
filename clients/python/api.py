import json
from enum import Enum
from socket import socket, AF_INET, SOCK_STREAM

from constants import SERVER_IP, SERVER_PORT, Tags, ServerMsgTypes, ClientMsgTypes, ServerStatus, LOG_ALL_RECEIVED_MESSAGES, LOG_ALL_SENT_MESSAGES


class ConnectionStatus(Enum):
    CONNECTED = 0
    DISCONNECTED = 1


class Player:
    def __init__(self, player_tag: str):
        self.player_tag = player_tag

    def __repr__(self):
        return f"Player({self.player_tag})"

    def __str__(self):
        return self.player_tag


class Connection:
    def __init__(self, player: Player, ip=SERVER_IP, port=SERVER_PORT):
        self.player = player
        self.host = ip
        self.port = port
        self.client_socket = socket(AF_INET, SOCK_STREAM)
        self.client_socket.connect((SERVER_IP, SERVER_PORT))
        self.status = ConnectionStatus.CONNECTED

        request = {
            Tags.TYPE: ClientMsgTypes.REQUEST_CONNECTION,
            Tags.PLAYER_TAG: self.player.player_tag
        }
        self.send(request)

        confirmation = self.receive()
        assert confirmation[Tags.TYPE] == ServerMsgTypes.ACCEPT_CONNECTION
        assert confirmation[Tags.STATUS] == ServerStatus.SUCCESS, f"Failed to connect to server: {confirmation[Tags.STATUS]}"
        print(f"Connected player {player} to {SERVER_IP}:{SERVER_PORT}")

    def receive(self) -> json:
        data = self.client_socket.recv(1024)
        if data == b'':
            print("Server closed connection while waiting for data")
            raise ConnectionError
        decoded_data = data.decode("utf-8")
        json_data = json.loads(decoded_data)
        if LOG_ALL_RECEIVED_MESSAGES:
            print(json_data)
        return json_data

    def send(self, json_data: json):
        if LOG_ALL_SENT_MESSAGES:
            print(json_data)
        json_str = json.dumps(json_data)
        self.client_socket.send(json_str.encode("utf-8"))

    def __del__(self):
        try:
            self.client_socket.close()
            self.status = ConnectionStatus.DISCONNECTED
            print(f"Closed connection to {SERVER_IP}:{SERVER_PORT}")
        except Exception as e:
            print(f"Failed to close connection: {e}")


class GameSession:
    def __init__(self, connection: Connection):
        self.connection = connection
