#include <iostream>
#include <sys/socket.h>
#include <netinet/in.h>
#include <future>
#include <boost/asio.hpp>

#include "constants.h"
#include "../util/assertions.h"
#include "../util/logging.h"
#include "api/connection.h"
#include "api/managed_connection.h"
#include "matcher.h"

using namespace Common::Server;
using namespace boost::asio;

Matcher Matcher::instance;

int main()
{

    io_context ioContext;
    ip::tcp::endpoint endpoint(ip::tcp::v4(), SERVER_PORT);
    ip::tcp::acceptor acceptor(ioContext, endpoint);

    std::vector<std::unique_ptr<ManagedConnection>> connections;
    LOG("Server started on port %d...", SERVER_PORT);

    while (true)
    {
        SocketPtr socket = std::make_shared<ip::tcp::socket>(ioContext);
        acceptor.accept(*socket);
        ManagedConnection::CleanConnections(connections);
        auto & connection = connections.emplace_back(std::make_unique<ManagedConnection>(socket));
        std::thread(&ManagedConnection::ConnectionListener, connection.get(), Matcher::HandleNewSession).detach();
    }

    return 0;
}
