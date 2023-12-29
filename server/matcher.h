#pragma once

#include "api/game_session.h"
#include "remote_player.h"
#include "../game/game.h"
#include "../util/dates.h"

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
        sessions.emplace(sessionID, session);
        session->Setup();
        unmatchedPlayers.push_back(sessionID);
        attemptMatch();
        return sessionID;
    }

    void attemptMatch()
    {
        if (unmatchedPlayers.size() >= 4)
        {
            std::vector<std::shared_ptr<PlayerGameSession>> gamePlayerSessions;
            for (int i = 0; i < 4; i++)
            {
                auto sessionID = unmatchedPlayers[0];
                unmatchedPlayers.erase(unmatchedPlayers.begin());
                gamePlayerSessions.push_back(sessions.at(sessionID));
            }

            auto logPath = getGameLogPath(gamePlayerSessions);
            std::shared_ptr<MessageLogger> logger = std::make_shared<MessageLogger>(logPath);
            LOG("Starting game with log file %s", logPath.c_str());

            std::vector<Game::PlayerRef> players{};
            for (auto & session: gamePlayerSessions)
            {
                session->setMessageLogger(logger);
                players.emplace_back(std::make_shared<RemotePlayer>(session->getPlayerTagSession(), session));
            }
            Game::Game game({players[0], players[1], players[2], players[3]});
            std::thread(&Game::Game::runGame, game).detach();
        }
    }

private:
    std::filesystem::path getGameLogPath(std::vector<std::shared_ptr<PlayerGameSession>> &sessions)
    {
        std::filesystem::path logPath = ENV_STRING("LOG_DIR");
        logPath /= Dates::GetStrDate();
        std::string name = Dates::GetStrTime();
        for (auto & session: sessions)
        {
            name += "_" + session->getPlayerTagSession();
        }

        if(std::filesystem::exists(logPath / (name + ".log")))
        {
            int counter = 1;
            while (std::filesystem::exists(logPath / (name + "_" + std::to_string(counter) + ".log")))
            {
                counter++;
            }
        }

        return logPath / (name + ".log");
    }

private:
    std::unordered_map<PlayerGameSessionID, std::shared_ptr<PlayerGameSession>> sessions;
    std::atomic<PlayerGameSessionID> sessionCounter;
    std::vector<PlayerGameSessionID> unmatchedPlayers;
};
}