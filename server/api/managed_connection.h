# pragma once

#include <netinet/in.h>
#include <vector>
#include <algorithm>
#include <arpa/inet.h>
#include "connection.h"
#include "../types.h"
#include "../constants.h"

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
    std::optional<std::shared_ptr<Common::MessageLogger>> messageLogger;
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
        catch (boost::system::system_error &e) {
            if (std::string(e.what()).find("End of file") != std::string::npos) {
                LOG("Client at %s:%d disconnected", this->mClientIP, this->mClientPort);
            } else {
                LOG("Error with client at %s:%d: %s", this->mClientIP, this->mClientPort, e.what());
                throw e;
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

    void sendOnSession(const Message::SessionMessage& message, PlayerGameSessionID sessionID)
    {
        send(message);

        auto sessionParts = playerGameSessions.find(message.getSessionID());
        if (sessionParts != playerGameSessions.end())
        {
            logMessage("Sent", message, sessionParts->second);
        }
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

        logMessage("Received", message, sessionParts->second);
        return message;
    }

    void setMessageLogger(PlayerGameSessionID sessionID, const std::shared_ptr<Common::MessageLogger>& messageLogger)
    {
        playerGameSessions[sessionID].messageLogger = messageLogger;
    }

    void logMessage(std::string &&prefix, const Server::Message::SessionMessage &message, SessionParts & sessionParts)
    {
        if (sessionParts.messageLogger.has_value())
        {
            sessionParts.messageLogger.value()->logMessage(prefix, message);
        }
    }

private:
    std::unordered_map<PlayerGameSessionID, SessionParts> playerGameSessions;
};

}
