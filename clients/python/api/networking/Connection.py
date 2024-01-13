import json
import threading
from enum import Enum
from socket import socket, AF_INET, SOCK_STREAM, timeout
from typing import List

from clients.python.util.Constants import Tags, ClientMsgTypes, ServerMsgTypes, \
    ServerStatus, MICRO_TIMEOUT, LOG_CONNECTIONS
from clients.python.util.Env import SERVER_IP, SERVER_PORT
from clients.python.util.Logging import ConnectionLogger


class ConnectionStatus(Enum):
    CONNECTED = 0
    DISCONNECTED = 1


class Connection:
    def __init__(self, ip=SERVER_IP, port=SERVER_PORT):
        self.host = ip
        self.port = port
        self.client_socket = socket(AF_INET, SOCK_STREAM)
        self.client_socket.connect((SERVER_IP, SERVER_PORT))
        self.client_socket.settimeout(MICRO_TIMEOUT)
        self.status = ConnectionStatus.CONNECTED
        self.pending_messages: List[json] = []
        self.incomplete_message: bytes = b""
        self.sending_lock = threading.Lock()
        self.logger = ConnectionLogger() if LOG_CONNECTIONS else None

        self.setup()
        print(f"Connected to {SERVER_IP}:{SERVER_PORT}")

    def receive(self) -> json:
        if len(self.pending_messages) == 0:
            data = self.incomplete_message
            try:
                data += self.client_socket.recv(1024)
            except timeout:
                return None

            if data == b'':
                raise ConnectionError("Server closed connection while waiting for data")
            try:
                json_objects = self._get_json_objects(data.decode("utf-8"))
            except json.decoder.JSONDecodeError:
                self.incomplete_message = data
                # log(f"Received incomplete message, attempting to receive more data, current data: {data}")
                return self.receive()
            json_data = json_objects[0]
            self.pending_messages = json_objects[1:]
            self.incomplete_message = b""
        else:
            json_data = self.pending_messages.pop(0)

        if self.logger is not None:
            self.logger.log_message("Received", json_data, False)
        return json_data

    @staticmethod
    def _get_json_objects(data: str) -> List:
        json_objects = []
        previous_split = 0
        while True:
            next_split = data[previous_split:].find("}{") + 1 + previous_split
            if next_split == previous_split:
                next_split = len(data)
            json_str = data[previous_split:next_split]
            json_objects.append(json.loads(json_str))
            if next_split == len(data):
                break
            previous_split = next_split
        return json_objects

    def receive_status(self, expected_status: str, expected_msg_type: str) -> json:
        response = self.receive()
        if response is None:
            raise ConnectionError("Server closed connection while waiting for status")
        assert response[Tags.TYPE] == expected_msg_type, \
            f"Expected message type {expected_msg_type}, got {response[Tags.TYPE]}"
        assert response[Tags.STATUS] == expected_status, \
            f"Expected mStatus {expected_status}, got {response[Tags.STATUS]}"
        return response

    def send(self, json_data: json):
        json_str = json.dumps(json_data, default=str, indent=1)
        with self.sending_lock:
            bytes_sent = self.client_socket.send(json_str.encode("utf-8"))
            if self.logger is not None:
                self.logger.log_message("Sent", json_data, False)
            if bytes_sent != len(json_str):
                raise ConnectionError(f"Expected to send {len(json_str)} bytes, but sent {bytes_sent}")

    def setup(self):
        connection_request = {
            Tags.TYPE: ClientMsgTypes.REQUEST_CONNECTION,
        }
        self.send(connection_request)
        self.receive_status(ServerStatus.SUCCESS, ServerMsgTypes.CONNECTION_RESPONSE)
