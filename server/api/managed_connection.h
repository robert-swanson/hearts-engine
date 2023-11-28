# pragma once

#include <netinet/in.h>
#include <vector>
#include <algorithm>
#include <arpa/inet.h>
#include "../types.h"
#include "../messages/server/accept_connection.h"
#include "../messages/client/connection_request.h"
#include "connection.h"
#include "game_session.h"

using namespace boost::asio;

namespace Common::Server
{
class ManagedConnection: public Connection
{
public:
    explicit ManagedConnection(const SocketPtr &clientSocket)
            : Connection(clientSocket), playerGameSessions() {
        try
        {
            Connection::handleConnectionRequest();
        }
        catch (std::exception &e)
        {
            LOG("Error with client at %s:%d: %s", this->clientIP, this->clientPort, e.what());
        }
    }

    void ConnectionListener()
    {
        while (true)
        {
            auto message = this->receive<Message::AnyMessage>();

        }
    }


    static void CleanConnections(std::vector<std::unique_ptr<ManagedConnection>> &connections)
    {
        connections.erase(
            std::remove_if(connections.begin(), connections.end(), [](std::unique_ptr<ManagedConnection> & connection) {
                return !connection->isConnected();
            }),
            connections.end());
    }


private:
    std::unordered_map<PlayerID, PlayerGameSession> playerGameSessions;

};
}