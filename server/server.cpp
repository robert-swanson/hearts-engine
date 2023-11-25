#include <iostream>
#include <sys/socket.h>
#include <netinet/in.h>
#include "constants.h"
#include "../util/assertions.h"
#include "../util/logging.h"
#include "connection.h"
#include <future>
#include <boost/asio.hpp>

using namespace Common::Server;
using namespace boost::asio;


int main()
{
    io_context ioContext;
    ip::tcp::endpoint endpoint(ip::tcp::v4(), SERVER_PORT);
    ip::tcp::acceptor acceptor(ioContext, endpoint);

    std::vector<std::unique_ptr<Connection>> connections;
    LOG("Server started on port %d...", SERVER_PORT);

    while (true)
    {
        SocketPtr socket = std::make_shared<ip::tcp::socket>(ioContext);
        acceptor.accept(*socket);
        Connection::CleanConnections(connections);
        auto & connection = connections.emplace_back(std::make_unique<Connection>(socket));
        std::thread(&Connection::start, connection.get()).detach();
    }

    return 0;
}
