# pragma once

#include <netinet/in.h>
#include <vector>
#include <algorithm>
#include <arpa/inet.h>
#include "connection.h"
#include "../types.h"

using namespace boost::asio;

namespace Common::Server {
struct SessionParts
{
    SessionParts(): unprocessedReceivedMessages(), waitCondition(), mutex()
    {
    }

    std::vector<Common::Server::Message::SessionMessage> unprocessedReceivedMessages;
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
            LOG("Error with client at %s:%d: %s", this->mClientIP, this->mClientPort, e.what());
        }
    }


    void ConnectionListener(const std::function<PlayerGameSessionID (ManagedConnection &)> &new_session_callback) {
        try {
            while (true) {
                auto message = this->receive();
                if (message.getJson()["type"] == ClientMsgTypes::GAME_SESSION_REQUEST) {
                    PlayerGameSessionID sessionID = new_session_callback(*this);
                    playerGameSessions[sessionID];
                } else {
                    auto sessionId = message.getJson()[Tags::SESSION_ID].get<PlayerGameSessionID>();
                    auto sessionMessage = Message::SessionMessage(message);
                    auto sessionParts = playerGameSessions.find(sessionId);
                    ASRT(sessionParts != playerGameSessions.end(), "Session ID %lld not found", sessionId);
                    sessionParts->second.unprocessedReceivedMessages.push_back(sessionMessage);
                    sessionParts->second.waitCondition.notify_all();
                }
            }
        }
        catch (std::exception &e) {
            if (e.what() == std::string("read_some: End of file")) {
                LOG("Client at %s:%d disconnected", this->mClientIP, this->mClientPort);
            } else {
                LOG("Error with client at %s:%d: %s", this->mClientIP, this->mClientPort, e.what());
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

    void sendOnSession(Message::SessionMessage message) {
        ASRT(message.getJson().find(Tags::SESSION_ID) != message.getJson().end(), "Message has no session ID");
        send(message);
    }

    Message::SessionMessage receiveOnSession(PlayerGameSessionID sessionId) {
        auto sessionParts = playerGameSessions.find(sessionId);
        ASRT(sessionParts != playerGameSessions.end(), "Session ID %lld not found", sessionId);
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
