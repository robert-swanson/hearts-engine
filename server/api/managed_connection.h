# pragma once

#include <memory>
#include <mutex>
#include <condition_variable>
#include <unordered_map>
#include <netinet/in.h>
#include <vector>
#include <algorithm>
#include <arpa/inet.h>
#include "connection.h"
#include "server/util/assertions.h"
#include "server/util/constants.h"
#include "server/util/logging.h"
#include "server/util/types.h"

using namespace boost::asio;

namespace Common::Server {

// SessionParts holds per-session state. It contains non-movable types (mutex,
// condition_variable) so it is always heap-allocated and owned via unique_ptr.
struct SessionParts
{
    SessionParts(): unprocessedReceivedMessages(), waitCondition(), mutex(), disconnected(false)
    {
    }

    std::vector<Common::Server::Message::SessionMessage> unprocessedReceivedMessages;
    std::condition_variable waitCondition;
    std::mutex mutex;
    bool disconnected;
    int consecutiveTimeouts = 0; // after 2, skip the wait and auto-move immediately
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


    // Register a server-initiated session so incoming messages for it are routed correctly.
    void addSession(PlayerGameSessionID sessionId)
    {
        playerGameSessions.emplace(sessionId, std::make_unique<SessionParts>());
    }

    void ConnectionListener(
        const std::function<PlayerGameSessionID (ManagedConnection &, Message::Message)> &new_session_callback,
        const std::function<bool(const Message::Message &)> &is_new_session =
            [](const Message::Message &m){ return m.getJson()[Tags::TYPE] == ClientMsgTypes::GAME_SESSION_REQUEST; })
    {
        try {
            while (true) {
                auto message = this->receive();
                if (is_new_session(message)) {
                    PlayerGameSessionID sessionID = new_session_callback(*this, message);
                    playerGameSessions.emplace(sessionID, std::make_unique<SessionParts>());
                } else {
                    auto sessionId = message.getJson()[Tags::SESSION_ID].get<PlayerGameSessionID>();
                    auto sessionMessage = Message::SessionMessage(message);
                    auto it = playerGameSessions.find(sessionId);
                    ASRT(it != playerGameSessions.end(), "Session ID %lld not found", sessionId);
                    it->second->unprocessedReceivedMessages.push_back(sessionMessage);
                    it->second->waitCondition.notify_all();
                }
            }
        }
        catch (boost::system::system_error &e) {
            if (std::string(e.what()).find("End of file") != std::string::npos) {
                LOG("Client at %s:%d disconnected", this->mClientIP, this->mClientPort);
            }
            else if (std::string(e.what()).find("Connection reset by peer") != std::string::npos) {
                LOG("Client at %s:%d forcefully disconnected", this->mClientIP, this->mClientPort);
            }
            else if (std::string(e.what()).find("Broken pipe") != std::string::npos) {
                LOG("Client at %s:%d broke the pipe", this->mClientIP, this->mClientPort);
            }
            else {
                LOG("Error with client at %s:%d: %s", this->mClientIP, this->mClientPort, e.what());
            }
            // Wake all sessions waiting on this connection so they can handle the disconnect
            for (auto& [id, parts] : playerGameSessions)
            {
                std::lock_guard<std::mutex> lock(parts->mutex);
                parts->disconnected = true;
                parts->waitCondition.notify_all();
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

        auto it = playerGameSessions.find(message.getSessionID());
        if (it != playerGameSessions.end())
        {
            logMessage("Sent", message, *it->second);
        }
    }

    // Returns nullopt on timeout or client disconnect
    std::optional<Message::SessionMessage> receiveOnSession(
            PlayerGameSessionID sessionId,
            std::chrono::seconds timeout = std::chrono::seconds(15))
    {
        auto it = playerGameSessions.find(sessionId);
        ASRT(it != playerGameSessions.end(), "Session ID %lld not found", sessionId);
        SessionParts& parts = *it->second;

        std::unique_lock<std::mutex> lock(parts.mutex);
        // After 2 consecutive timeouts the client is unresponsive; skip waiting entirely.
        auto effectiveTimeout = (parts.consecutiveTimeouts >= 2)
            ? std::chrono::seconds(0) : timeout;
        bool gotMessage = parts.waitCondition.wait_for(lock, effectiveTimeout, [&parts] {
            return !parts.unprocessedReceivedMessages.empty()
                   || parts.disconnected;
        });

        if (!gotMessage || parts.disconnected
            || parts.unprocessedReceivedMessages.empty())
        {
            parts.consecutiveTimeouts++;
            return std::nullopt;
        }

        parts.consecutiveTimeouts = 0;
        auto message = parts.unprocessedReceivedMessages[0];
        parts.unprocessedReceivedMessages.erase(parts.unprocessedReceivedMessages.begin());

        logMessage("Received", message, parts);
        return message;
    }

    void setMessageLogger(PlayerGameSessionID sessionID, const std::shared_ptr<Common::MessageLogger>& messageLogger)
    {
        auto it = playerGameSessions.find(sessionID);
        if (it != playerGameSessions.end())
            it->second->messageLogger = messageLogger;
    }

    void logMessage(std::string &&prefix, const Server::Message::SessionMessage &message, SessionParts & sessionParts)
    {
        if (sessionParts.messageLogger.has_value())
        {
            sessionParts.messageLogger.value()->logMessage(prefix, message);
        }
    }

private:
    std::unordered_map<PlayerGameSessionID, std::unique_ptr<SessionParts>> playerGameSessions;
};

}
