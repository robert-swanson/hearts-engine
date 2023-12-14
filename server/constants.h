#pragma once

namespace Common::Server
{
    // Dependencies in clients/python/Constants.py
    constexpr uint16_t SERVER_PORT = 40405;
    constexpr int MAX_CONNECTION_BACKLOG = 5;

    constexpr int SUCCESS_CODE = 0;
    constexpr int MAX_CONNECTIONS = 10;

    constexpr bool LOG_ALL_SENT_MESSAGES = false;
    constexpr bool LOG_ALL_RECEIVED_MESSAGES = false;
}

namespace Common::Server::Tags
{
    constexpr auto TYPE = "type";
    constexpr auto SESSION_ID = "session_id";
    constexpr auto STATUS = "status";
    constexpr auto PLAYER_TAG = "player_tag";
};

namespace Common::Server::ServerMsgTypes
{
    constexpr auto CONNECTION_RESPONSE = "connection_response";
    constexpr auto GAME_SESSION_RESPONSE = "game_session_response";
}

namespace Common::Server::ClientMsgTypes
{
    constexpr auto CONNECTION_REQUEST = "connection_request";
    constexpr auto GAME_SESSION_REQUEST = "game_session_request";
}

namespace Common::Server::ServerStatus
{
    constexpr auto SUCCESS = "success";

    constexpr auto UNKNOWN_PLAYER_ID = "unknown_player_id";
}