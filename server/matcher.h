#pragma once

#include "api/game_session.h"
#include "remote_player.h"
#include "../game/game.h"

namespace Common::Server
{

class Matcher
{
private:
    static Matcher instance;

    Matcher(): sessions(), sessionCounter(0)
    {
//        sessionCounter = std::chrono::duration_cast<std::chrono::milliseconds>(
//                std::chrono::system_clock::now().time_since_epoch()).count();
    }

public:
    static Matcher& GetInstance()
    {
        return Matcher::instance;
    }

    static PlayerGameSessionID HandleSessionRequest(ManagedConnection &connection)
    {
        return GetInstance().createPlayerGameSession(connection);
    }

    PlayerGameSessionID createPlayerGameSession(ManagedConnection &connection)
    {
        auto sessionID = sessionCounter.fetch_add(1, std::memory_order_relaxed);
        auto session = std::make_shared<PlayerGameSession>(sessionID, connection);
        sessions.emplace(sessionID, *session);
        std::thread(&PlayerGameSession::RunGameSession, session).detach();
        unmatchedPlayers.push_back(sessionID);
        attemptMatch();
        return sessionID;
    }

    void attemptMatch()
    {
        if (unmatchedPlayers.size() >= 4)
        {
            std::vector<Game::PlayerRef> players{};
            for (int i = 0; i < 4; i++)
            {
                PlayerGameSession & session = sessions.at(unmatchedPlayers[0]);
                players.emplace_back(std::make_shared<RemotePlayer>(session.getPlayerId(), session));
                unmatchedPlayers.erase(unmatchedPlayers.begin());
            }
            Game::Game game({players[0], players[1], players[2], players[3]});
            std::thread(&Game::Game::runGame, game).detach();
        }
    }

private:
    std::unordered_map<PlayerGameSessionID, PlayerGameSession> sessions;
    std::atomic<PlayerGameSessionID> sessionCounter;
    std::vector<PlayerGameSessionID> unmatchedPlayers;
};
}