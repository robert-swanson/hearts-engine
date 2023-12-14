#pragma once

#include "api/game_session.h"

namespace Common::Server
{

class Matcher
{
private:
    static Matcher instance;

    Matcher(): sessions(), sessionCounter(0)
    {
        sessionCounter = std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count();
    }

public:
    static Matcher& GetInstance()
    {
        return Matcher::instance;
    }

    static void HandleNewSession(ManagedConnection &connection)
    {
        GetInstance().createPlayerGameSession(connection);
    }

    void createPlayerGameSession(ManagedConnection &connection)
    {
        auto sessionID = sessionCounter.fetch_add(1, std::memory_order_relaxed);
        auto session = PlayerGameSession(sessionID, connection);
        std::thread(&PlayerGameSession::RunGameSession, session).detach();
    }

private:
    std::unordered_map<PlayerGameSessionID, PlayerGameSession> sessions;
    std::atomic<PlayerGameSessionID> sessionCounter;
};
}