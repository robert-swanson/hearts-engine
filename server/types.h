#pragma once

#include <nlohmann/json.hpp>
#include <boost/asio.hpp>
#include "../game/objects/types.h"

namespace Common::Server
{
using SocketPtr = std::shared_ptr<boost::asio::ip::tcp::socket>;
using json = nlohmann::json;
using PlayerID = Game::PlayerID;
using PlayerGameSessionID = long long;
}