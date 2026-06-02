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
    int consecutiveTimeouts = 0;
    int autoMoveThreshold = 2;  // 0 = never auto-move
    std::optional<std::shared_ptr<Common::MessageLogger>> messageLogger;
};

class ManagedConnection : public Connection {
public:
    explicit ManagedConnection(const SocketPtr &clientSocket) : Connection(clientSocket), playerGameSessions() {
        try {
            Connection::handleConnectionRequest();
        }
        catch (std::exception &e) {
            // Suppress "End of file" — it just means the client disconnected before
            // sending anything (e.g. a port-readiness probe). Everything else is real.
            if (std::string(e.what()).find("End of file") == std::string::npos)
                LOG("Error with client at %s:%d: %s", this->mClientIP, this->mClientPort, e.what());
        }
    }


    // Register a server-initiated session so incoming messages for it are routed correctly.
    void addSession(PlayerGameSessionID sessionId, int autoMoveThreshold = 2)
    {
        auto parts = std::make_unique<SessionParts>();
        parts->autoMoveThreshold = autoMoveThreshold;
        std::lock_guard<std::mutex> lock(mSessionsMtx);
        playerGameSessions.emplace(sessionId, std::move(parts));
    }

    // Auto-move threshold applied to sessions that ConnectionListener auto-registers
    // (the client-initiated path). The lobby server sets this to 0 so a human's turn
    // never times out into a server-played move. Defaults to 2 (tournament behavior).
    void setNewSessionAutoMoveThreshold(int threshold) { mNewSessionAutoMoveThreshold = threshold; }

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
                    // A callback may return 0 to signal "no session created" — e.g. an
                    // auth rejection, or a control message (tournament heartbeat) that
                    // updates state without opening a session. Don't register a bogus
                    // session 0 in that case.
                    if (sessionID != 0) {
                        auto parts = std::make_unique<SessionParts>();
                        parts->autoMoveThreshold = mNewSessionAutoMoveThreshold;
                        std::lock_guard<std::mutex> lock(mSessionsMtx);
                        playerGameSessions.emplace(sessionID, std::move(parts));
                    }
                } else {
                    // .at() throws (caught below) on a missing/ill-typed session id,
                    // rather than the old const operator[] which was UB for a missing key.
                    auto sessionId = message.getJson().at(Tags::SESSION_ID).get<PlayerGameSessionID>();
                    auto sessionMessage = Message::SessionMessage(message);
                    SessionParts* parts = nullptr;
                    {
                        std::lock_guard<std::mutex> mapLock(mSessionsMtx);
                        auto it = playerGameSessions.find(sessionId);
                        if (it == playerGameSessions.end()) {
                            // A client referencing an unknown session must not crash
                            // the server. ASRT compiles to assert(), a no-op under
                            // NDEBUG, after which the old code dereferenced an end()
                            // iterator (UB). Skip the message and keep serving.
                            LOG("Client at %s:%d referenced unknown session %lld; ignoring",
                                this->mClientIP, this->mClientPort, (long long) sessionId);
                            continue;
                        }
                        parts = it->second.get();
                    }
                    {
                        std::lock_guard<std::mutex> sessLock(parts->mutex);
                        parts->unprocessedReceivedMessages.push_back(sessionMessage);
                        parts->waitCondition.notify_all();
                    }
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
            else if (std::string(e.what()).find("Bad file descriptor") != std::string::npos) {
                // Normal: socket was closed by shutdownSocket() during server cleanup
            }
            else {
                LOG("Error with client at %s:%d: %s", this->mClientIP, this->mClientPort, e.what());
            }
            disconnectAllSessions();
        }
        catch (const std::exception &e) {
            // A malformed-but-valid-JSON message (e.g. missing "type", wrong
            // value type for session_id) throws from the Message ctor / .get<>()
            // rather than as a boost system_error. Without this clause the
            // exception escapes the per-connection thread and calls
            // std::terminate(), taking the whole server down — a trivial
            // client-triggerable DoS. Tear down only this connection instead.
            LOG("Client at %s:%d sent an unprocessable message (%s); dropping connection",
                this->mClientIP, this->mClientPort, e.what());
            disconnectAllSessions();
        }
    }

    // Mark every session on this connection disconnected and wake any thread
    // blocked in receiveOnSession so it can observe the disconnect and exit.
    void disconnectAllSessions()
    {
        std::vector<SessionParts*> snapshot;
        {
            std::lock_guard<std::mutex> mapLock(mSessionsMtx);
            for (auto& [id, p] : playerGameSessions)
                snapshot.push_back(p.get());
        }
        for (auto* p : snapshot)
        {
            std::lock_guard<std::mutex> lock(p->mutex);
            p->disconnected = true;
            p->waitCondition.notify_all();
        }
    }

    // True if any session on this connection has been marked disconnected (the
    // ConnectionListener sets this when the client's socket hits EOF / reset).
    // Used by the tournament lobby to drop players whose clients have dropped.
    bool anySessionDisconnected()
    {
        std::lock_guard<std::mutex> mapLock(mSessionsMtx);
        for (auto& [id, p] : playerGameSessions)
        {
            std::lock_guard<std::mutex> lock(p->mutex);
            if (p->disconnected)
                return true;
        }
        return false;
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

        SessionParts* parts = nullptr;
        {
            std::lock_guard<std::mutex> lock(mSessionsMtx);
            auto it = playerGameSessions.find(message.getSessionID());
            if (it != playerGameSessions.end())
                parts = it->second.get();
        }
        if (parts)
            logMessage("Sent", message, *parts);
    }

    // Returns nullopt on timeout or client disconnect
    std::optional<Message::SessionMessage> receiveOnSession(
            PlayerGameSessionID sessionId,
            std::chrono::milliseconds timeout = std::chrono::seconds(15))
    {
        SessionParts* rawParts;
        {
            std::lock_guard<std::mutex> mapLock(mSessionsMtx);
            auto it = playerGameSessions.find(sessionId);
            ASRT(it != playerGameSessions.end(), "Session ID %lld not found", sessionId);
            rawParts = it->second.get();
        }
        SessionParts& parts = *rawParts;

        std::unique_lock<std::mutex> lock(parts.mutex);
        auto effectiveTimeout = (parts.autoMoveThreshold > 0 && parts.consecutiveTimeouts >= parts.autoMoveThreshold)
            ? std::chrono::milliseconds(0) : timeout;
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

    // Closes the underlying socket, unblocking any ConnectionListener thread waiting
    // for reads so it can exit cleanly before the object is destroyed.
    void shutdownSocket()
    {
        closeConnection();
    }

    void setMessageLogger(PlayerGameSessionID sessionID, const std::shared_ptr<Common::MessageLogger>& messageLogger)
    {
        std::lock_guard<std::mutex> lock(mSessionsMtx);
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
    std::mutex mSessionsMtx;
    std::unordered_map<PlayerGameSessionID, std::unique_ptr<SessionParts>> playerGameSessions;
    int mNewSessionAutoMoveThreshold = 2;
};

}
