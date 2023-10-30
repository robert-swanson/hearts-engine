#pragma once

#include <nlohmann/json.hpp>
#include <boost/asio.hpp>

namespace Common::Server
{
using SocketPtr = std::shared_ptr<boost::asio::ip::tcp::socket>;
using json = nlohmann::json;
}