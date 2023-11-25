# Defined in server/constants.h
from enum import Enum

SERVER_IP = "localhost"
SERVER_PORT = 40404

LOG_ALL_SENT_MESSAGES = False
LOG_ALL_RECEIVED_MESSAGES = False


class Tags:
    TYPE = "type"
    STATUS = "status"
    SESSION_ID = "session_id"

    PLAYER_TAG = "player_tag"
    GAME_TYPE = "game_type"


class ServerMsgTypes:
    ACCEPT_CONNECTION = "accept"
    ACCEPT_GAME_SESSION = "accept_game_session"


class ClientMsgTypes:
    REQUEST_CONNECTION = "request"
    REQUEST_GAME_SESSION = "request_game_session"


class ServerStatus:
    SUCCESS = "success"

    UNKNOWN_PLAYER_ID = "unknown_player_id"


class GameType(Enum):
    HUMANS_ONLY = "humans_only"
    BOTS_ONLY = "bots_only"
    ANY = "any"
