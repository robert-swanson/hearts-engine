#pragma once

namespace Common::Server
{
    // Dependencies in clients/python/Constants.py
    constexpr uint16_t SERVER_PORT = 40405;
    constexpr int MAX_CONNECTION_BACKLOG = 5;

    constexpr int SUCCESS_CODE = 0;
    constexpr int MAX_CONNECTIONS = 10;

    constexpr bool LOG_ALL_SENT_MESSAGES = true;
    constexpr bool LOG_ALL_RECEIVED_MESSAGES = true;
}


namespace Common::Server::Tags
{
    constexpr auto TYPE = "type";
    constexpr auto STATUS = "status";
    constexpr auto SESSION_ID = "session_id";
    constexpr auto PLAYER_TAG = "player_tag";
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