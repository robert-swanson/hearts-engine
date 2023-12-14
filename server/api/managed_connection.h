# pragma once

#include <netinet/in.h>
#include <vector>
#include <algorithm>
#include <arpa/inet.h>
#include "connection.h"
#include "../types.h"
#include "../messages/server/accept_connection.h"
#include "../messages/client/connection_request.h"

using namespace boost::asio;

namespace Common::Server {
struct SessionParts
{
    std::vector<Common::Server::Message::AnySessionMessage> unprocessedReceivedMessages;
    std::condition_variable waitCondition;
    std::mutex mutex;
};

class ManagedConnection : public Connection {
public:
    explicit ManagedConnection(const SocketPtr &clientSocket) : Connection(clientSocket), playerGameSessions() {
        try {
            Connection::handleConnectionRequest();
        }
        catch (std::exception &e) {
            LOG("Error with client at %s:%d: %s", this->clientIP, this->clientPort, e.what());
        }
    }


    void ConnectionListener(const std::function<void(ManagedConnection &)> &new_session_callback) {
        try {
            while (true) {
                auto message = this->receive<Message::AnyMessage>();
                if (message.value["type"] == ClientMsgTypes::GAME_SESSION_REQUEST) {
                    new_session_callback(*this);
                } else {
                    auto sessionId = message.value[Tags::SESSION_ID].get<PlayerGameSessionID>();
                    Message::AnySessionMessage sessionMessage = dynamic_cast<Message::AnySessionMessage &>(message);
                    auto sessionParts = playerGameSessions.find(sessionId);
                    ASRT(sessionParts != playerGameSessions.end(), "Session ID %d not found", sessionId);
                    sessionParts->second.unprocessedReceivedMessages.push_back(sessionMessage);
                    sessionParts->second.waitCondition.notify_all();
                }
            }
        }
        catch (std::exception &e) {
            if (e.what() != std::string("read_some: End of file")) {
                LOG("Client at %s:%d disconnected", this->clientIP, this->clientPort);
            } else {
                LOG("Error with client at %s:%d: %s", this->clientIP, this->clientPort, e.what());
            }
        }
    }

    static void CleanConnections(std::vector<std::unique_ptr<ManagedConnection>> &connections) {
        connections.erase(
                std::remove_if(connections.begin(), connections.end(),
                               [](std::unique_ptr<ManagedConnection> &connection) {
                                   return !connection->isConnected();
                               }),
                connections.end());
    }

    void sendOnSession(Message::AnySessionMessage &message) {
        ASRT(message.value.find(Tags::SESSION_ID) != message.value.end(), "Message has no session ID");
        send(message);
    }

    Message::AnySessionMessage receiveOnSession(PlayerGameSessionID sessionId) {
        auto sessionParts = playerGameSessions.find(sessionId);
        ASRT(sessionParts != playerGameSessions.end(), "Session ID %d not found", sessionId);
        std::unique_lock<std::mutex> lock(sessionParts->second.mutex);
        sessionParts->second.waitCondition.wait(lock, [&sessionParts] {
            return !sessionParts->second.unprocessedReceivedMessages.empty();
        });
        auto message = sessionParts->second.unprocessedReceivedMessages[0];
        sessionParts->second.unprocessedReceivedMessages.erase(
                sessionParts->second.unprocessedReceivedMessages.begin());
        return message;
    }

private:
    std::unordered_map<PlayerGameSessionID, SessionParts> playerGameSessions;
};

}
