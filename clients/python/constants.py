# Defined in server/constants.h
from enum import Enum

SERVER_IP = "localhost"
SERVER_PORT = 40404

LOG_ALL_SENT_MESSAGES = False
LOG_ALL_RECEIVED_MESSAGES = False

class Tags:
    TYPE = "type"
    STATUS = "status"

    PLAYER_TAG = "player_tag"


class ServerMsgTypes:
    ACCEPT_CONNECTION = "accept"


class ClientMsgTypes:
    REQUEST_CONNECTION = "request"


class ServerStatus:
    SUCCESS = "success"

    UNKNOWN_PLAYER_ID = "unknown_player_id"
