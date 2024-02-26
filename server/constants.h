#pragma once

namespace Common::Server
{
    constexpr auto MESSAGE_LOG_NAME = "messages";
    constexpr auto GAME_LOG_NAME = "game";
    constexpr auto SERVER_LOG_DIRNAME = "server";

    constexpr auto DEFAULT_LOBBY_CODE = "main";
}

namespace Common::Env
{
    constexpr auto SERVER_PORT = "SERVER_PORT";
}


// Dependencies in clients/python/Constants.py
namespace Common::Server::Tags
{
    constexpr auto TYPE = "type";
    constexpr auto STATUS = "status";
    constexpr auto SESSION_ID = "session_id";
    constexpr auto SEQ_NUM = "seq_num";
    constexpr auto PLAYER_TAG = "player_tag";
    constexpr auto LOBBY_CODE = "lobby_code";
    constexpr auto PLAYER_SESSION_ID = "player_session_id";
    constexpr auto GAME_TYPE = "game_type";
    constexpr auto PLAYER_ORDER = "player_order";
    constexpr auto PASS_DIRECTION = "pass_direction";
    constexpr auto CARDS = "cards";
    constexpr auto CARD = "card";
    constexpr auto ROUND_INDEX = "round_index";
    constexpr auto TRICK_INDEX = "trick_index";
    constexpr auto LEGAL_MOVES = "legal_moves";
    constexpr auto WINNING_PLAYER = "winning_player";
    constexpr auto PLAYER_TO_ROUND_POINTS = "player_to_round_points";
    constexpr auto PLAYER_TO_GAME_POINTS = "player_to_game_points";
};

namespace Common::Server::ServerMsgTypes
{
    constexpr auto CONNECTION_RESPONSE = "connection_response";
    constexpr auto GAME_SESSION_RESPONSE = "game_session_response";
    constexpr auto START_GAME = "start_game";
    constexpr auto START_ROUND = "start_round";
    constexpr auto RECEIVED_CARDS = "received_cards";
    constexpr auto START_TRICK = "start_trick";
    constexpr auto MOVE_REPORT = "move_report";
    constexpr auto MOVE_REQUEST = "move_request";
    constexpr auto END_TRICK = "end_trick";
    constexpr auto END_ROUND = "end_round";
    constexpr auto END_GAME = "end_game";
}

namespace Common::Server::ClientMsgTypes
{
    constexpr auto CONNECTION_REQUEST = "connection_request";
    constexpr auto GAME_SESSION_REQUEST = "game_session_request";
    constexpr auto DONATED_CARDS = "donated_cards";
    constexpr auto DECIDED_MOVE = "decided_move";
}

namespace Common::Server::ServerStatus
{
    constexpr auto SUCCESS = "success";

    constexpr auto UNKNOWN_PLAYER_ID = "unknown_player_id";
}