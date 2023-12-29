#include <future>
#include <boost/asio.hpp>

#include "../util/assertions.h"
#include "../util/logging.h"
#include "../util/env.h"
#include "api/managed_connection.h"
#include "matcher.h"

using namespace Common::Server;
using namespace boost::asio;

Matcher Matcher::instance;

int main(int argc, char **argv)
{
    ASRT(argc == 2, "Usage: ./server <env_file_path>");
    // current working directory
    EnvLoader = EnvironmentLoader(argv[1]);

    io_context ioContext;
    ip::tcp::endpoint endpoint(ip::tcp::v4(), ENV_INT(Common::Env::SERVER_PORT));
    ip::tcp::acceptor acceptor(ioContext, endpoint);

    std::vector<std::unique_ptr<ManagedConnection>> connections;
    LOG("Server started on port %d...", ENV_INT(Common::Env::SERVER_PORT));

    while (true)
    {
        SocketPtr socket = std::make_shared<ip::tcp::socket>(ioContext);
        acceptor.accept(*socket);
        ManagedConnection::CleanConnections(connections);
        auto & connection = connections.emplace_back(std::make_unique<ManagedConnection>(socket));
        std::thread(&ManagedConnection::ConnectionListener, connection.get(), Matcher::HandleSessionRequest).detach();
    }

    return 0;
}
