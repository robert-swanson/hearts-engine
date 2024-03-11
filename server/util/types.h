#pragma once

#include <nlohmann/json.hpp>
#include <boost/asio.hpp>
#include "../game/objects/types.h"

namespace Common::Server
{
using SocketPtr = std::shared_ptr<boost::asio::ip::tcp::socket>;
using json = nlohmann::json;
using PlayerTag = std::string;
using PlayerGameSessionID = long long;
using PlayerTagSession = std::string;
using LobbyCode = std::string;

PlayerTagSession MakePlayerTagSession(const PlayerTag& playerTag, PlayerGameSessionID playerGameSessionID)
{
    return playerTag + "(" + std::to_string(playerGameSessionID) + ")";
}

}