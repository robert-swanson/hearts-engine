# Defined in server/constants.h
from enum import Enum

SERVER_IP = "localhost"
SERVER_PORT = 40405

LOG_ALL_SENT_MESSAGES = True
LOG_ALL_RECEIVED_MESSAGES = True


class Tags:
    TYPE = "type"
    STATUS = "status"
    SESSION_ID = "session_id"

    PLAYER_TAG = "player_tag"
    GAME_TYPE = "game_type"


class ServerMsgTypes:
    CONNECTION_RESPONSE = "connection_response"
    GAME_SESSION_RESPONSE = "game_session_response"


class ClientMsgTypes:
    REQUEST_CONNECTION = "connection_request"
    REQUEST_GAME_REQUEST = "game_session_request"


class ServerStatus:
    SUCCESS = "success"

    UNKNOWN_PLAYER_ID = "unknown_player_id"


class GameType(Enum):
    HUMANS_ONLY = "humans_only"
    BOTS_ONLY = "bots_only"
    ANY = "any"
