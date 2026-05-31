#include <future>
#include <boost/asio.hpp>

#include "util/assertions.h"
#include "util/logging.h"
#include "util/env.h"
#include "api/managed_connection.h"
#include "matching/matcher.h"

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
        try
        {
            SocketPtr socket = std::make_shared<ip::tcp::socket>(ioContext);
            acceptor.accept(*socket);
            auto & connection = connections.emplace_back(std::make_unique<ManagedConnection>(socket));
            auto* conn_ptr = connection.get();
            // Lobby play is interactive: a human seat must be able to take as long
            // as it likes without the server timing out and playing for them. Unlike
            // the tournament server (which auto-moves after N timeouts to keep a bracket
            // moving), disable auto-move entirely here.
            conn_ptr->setNewSessionAutoMoveThreshold(0);
            std::thread([conn_ptr]() {
                conn_ptr->ConnectionListener(Matcher::HandleSessionRequest);
            }).detach();
            ManagedConnection::CleanConnections(connections);
        }
        catch (boost::system::system_error &e)
        {
            auto code = e.code().value();
            if (e.code() == boost::asio::error::connection_aborted || code == EINVAL)
                LOG("Client aborted connection before accept completed");
            else if (std::string(e.what()).find("Broken pipe") != std::string::npos)
                LOG("Client broke the pipe while connecting");
            else
                LOG("Error: %s", e.what());
        }
    }

    return 0;
}
