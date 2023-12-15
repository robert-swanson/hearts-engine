import json
from abc import ABC


class Messenger(ABC):
    def receive(self) -> json:
        pass

    def receive_type(self, expected_msg_type: str) -> json:
        pass

    def receive_status(self, expected_status: str, expected_msg_type: str) -> json:
        pass

    def get_next_message_type(self) -> str:
        pass

    def send(self, json_data: json):
        pass


class PassingMessenger(Messenger):
    def __init__(self, messenger: Messenger):
        self.messenger = messenger

    def receive(self) -> json:
        return self.messenger.receive()

    def receive_type(self, expected_msg_type: str) -> json:
        return self.messenger.receive_type(expected_msg_type)

    def receive_status(self, expected_status: str, expected_msg_type: str) -> json:
        return self.messenger.receive_status(expected_status, expected_msg_type)

    def get_next_message_type(self) -> str:
        return self.messenger.get_next_message_type()

    def send(self, json_data: json):
        self.messenger.send(json_data)