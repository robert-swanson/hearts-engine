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
    PLAYER_ORDER = "player_order"
    PASS_DIRECTION = "pass_direction"
    CARDS = "cards"
    CARD = "card"
    ROUND_INDEX = "round_index"
    TRICK_INDEX = "trick_index"
    LEGAL_MOVES = "legal_moves"
    WINNING_PLAYER = "winning_player"
    PLAYER_TO_ROUND_POINTS = "player_to_round_points"
    PLAYER_TO_GAME_POINTS = "player_to_game_points"


class ServerMsgTypes:
    CONNECTION_RESPONSE = "connection_response"
    GAME_SESSION_RESPONSE = "game_session_response"
    START_GAME = "start_game"
    START_ROUND = "start_round"
    RECEIVED_CARDS = "received_cards"
    START_TRICK = "start_trick"
    MOVE_REPORT = "move_report"
    MOVE_REQUEST = "move_request"
    END_TRICK = "end_trick"
    END_ROUND = "end_round"
    END_GAME = "end_game"


class ClientMsgTypes:
    REQUEST_CONNECTION = "connection_request"
    REQUEST_GAME_SESSION = "game_session_request"
    DONATED_CARDS = "donated_cards"
    DECIDED_MOVE = "decided_move"


class ServerStatus:
    SUCCESS = "success"

    UNKNOWN_PLAYER_ID = "unknown_player_id"


class GameType(Enum):
    HUMANS_ONLY = "humans_only"
    BOTS_ONLY = "bots_only"
    ANY = "any"
