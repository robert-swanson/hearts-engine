#pragma once

namespace Common::Server
{
    constexpr uint16_t SERVER_PORT = 40404;
    constexpr int MAX_CONNECTION_BACKLOG = 5;

    constexpr int SUCCESS_CODE = 0;
    constexpr int MAX_CONNECTIONS = 10;


}

namespace Common::Server::Tags
{
    constexpr auto TYPE = "type";
};

namespace Common::Server::MsgTypes
{
    constexpr auto SERVER_ACCEPT_CONNECTION = "accept";

}