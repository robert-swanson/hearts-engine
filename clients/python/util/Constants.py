# Defined in server/constants.h
from enum import Enum

# Connection
MICRO_TIMEOUT = 1  # Seconds or None
MACRO_TIMEOUT = None

# Logging
LOG_SESSIONS = True  # Can disable all message logging
LOG_CONNECTIONS = True  # Should the connection thread log with messages are sent/received
CLIENT_LOG_DIRNAME = "client"
SESSION_LOG_DIRNAME = "sessions"
CONNECTION_LOG_DIRNAME = "connections"


class Tags:
    TYPE = "type"
    STATUS = "status"
    SESSION_ID = "session_id"
    SEQ_NUM = "seq_num"
    PLAYER_TAG = "player_tag"
    LOBBY_CODE = "lobby_code"
    GAME_TYPE = "game_type"
    PLAYER_ORDER = "player_order"
    PASS_DIRECTION = "pass_direction"
    CARDS = "cards"
    CARD = "card"
    DONATED_CARDS = "donated_cards"
    MOVE_SOURCE = "move_source"
    ROUND_INDEX = "round_index"
    TRICK_INDEX = "trick_index"
    LEGAL_MOVES = "legal_moves"
    WINNING_PLAYER = "winning_player"
    PLAYER_TO_ROUND_POINTS = "player_to_round_points"
    PLAYER_TO_GAME_POINTS = "player_to_game_points"
    SENT_AT_MS     = "sent_at_ms"       # wall-clock ms when message was sent
    PREV_LATENCY_MS = "prev_latency_ms" # one-way latency of the previous message in the chain


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
    TOURNAMENT_REGISTER = "tournament_register"
    TOURNAMENT_HEARTBEAT = "tournament_heartbeat"


class TournamentMsgTypes:
    QUEUED          = "tournament_queued"
    GAME_ASSIGNMENT = "tournament_game_assignment"
    STAGE_COMPLETE  = "tournament_stage_complete"
    COMPLETE        = "tournament_complete"


class TournamentTags:
    TEAM_NAME       = "team_name"
    PASSWORD        = "password"
    PRIORITY_SCORE  = "priority_score"
    GAME_SESSION_ID = "game_session_id"
    GAME_ID         = "game_id"
    STAGE           = "stage"
    START_AT        = "start_at"
    RESULTS         = "results"


class MoveSource:
    PLAYER = "player"
    SERVER = "server"


class ServerStatus:
    SUCCESS = "success"

    UNKNOWN_PLAYER_ID = "unknown_player_id"


class GameType(Enum):
    HUMANS_ONLY = "humans_only"
    BOTS_ONLY = "bots_only"
    ANY = "any"
