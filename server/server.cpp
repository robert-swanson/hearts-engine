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
    io_service io;
    ip::tcp::endpoint endpoint(ip::tcp::v4(), SERVER_PORT);
    ip::tcp::acceptor acceptor(io, endpoint);

    std::vector<Connection> connections;
    LOG("Server started on port %d...", SERVER_PORT);
    while (true)
    {
        SocketPtr socket = std::make_shared<ip::tcp::socket>(io);
        acceptor.async_accept(*socket, [&](const boost::system::error_code &error) {
            ASRT(error.value() == SUCCESS_CODE, "Error accepting connection: %s", error.message().c_str());
            Connection connection = connections.emplace_back(socket);
            connection.start();
            Connection::CleanConnections(connections);
        });

        io.run();
    }
}
