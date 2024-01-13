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

    Matcher(): allSessions(), sessionCounter(0)
    {
//        sessionCounter = std::chrono::duration_cast<std::chrono::milliseconds>(
//                std::chrono::system_clock::now().time_since_epoch()).count();
    }

public:
    static Matcher& GetInstance()
    {
        return Matcher::instance;
    }

    static PlayerGameSessionID HandleSessionRequest(ManagedConnection &connection, Message::Message message)
    {
        auto playerTag = message.getTag<PlayerTag>(Tags::PLAYER_TAG);
        return GetInstance().createPlayerGameSession(connection, playerTag);
    }

    PlayerGameSessionID createPlayerGameSession(ManagedConnection &connection, const PlayerTag& playerTag)
    {
        auto sessionID = sessionCounter.fetch_add(1, std::memory_order_relaxed);
        auto session = std::make_shared<PlayerGameSession>(sessionID, playerTag, connection);
        allSessions.emplace(sessionID, session);
        session->Setup();
        unmatchedPlayers.push_back(sessionID);
        attemptMatch();
        return sessionID;
    }

    void attemptMatch()
    {
        if (unmatchedPlayers.size() >= 4)
        {
            std::string msgLoggerName = std::to_string(unmatchedPlayers[0]) + "_" + MESSAGE_LOG_NAME + ".log";
            auto messageLogger = std::make_shared<MessageLogger>(makeGameLogDirPath(MESSAGE_LOG_NAME) / msgLoggerName);

            std::string gameLoggerName = std::to_string(unmatchedPlayers[0]) + "_" + GAME_LOG_NAME + ".log";
            auto gameLogger = std::make_shared<GameLogger>(makeGameLogDirPath(GAME_LOG_NAME) / gameLoggerName);

            std::vector<Game::PlayerRef> players{};
            for (int i = 0; i < 4; i++)
            {
                auto sessionID = unmatchedPlayers[0];
                unmatchedPlayers.erase(unmatchedPlayers.begin());
                const auto & session = allSessions.at(sessionID);
                session->setMessageLogger(messageLogger);
                players.emplace_back(std::make_shared<RemotePlayer>(session->getPlayerTagSession(), session));
            }
            Game::Game game({players[0], players[1], players[2], players[3]}, gameLogger);
            std::thread(&Game::Game::runGame, game).detach();
        }
    }

private:
    static std::filesystem::path makeGameLogDirPath(const std::string & logDirName)
    {
        std::filesystem::path logPath = ENV_STRING("LOG_DIR");
        return logPath / SERVER_LOG_DIRNAME / logDirName / Dates::GetStrDate('-') / Dates::GetStrTime(':');
    }

private:
    std::unordered_map<PlayerGameSessionID, std::shared_ptr<PlayerGameSession>> allSessions;
    std::atomic<PlayerGameSessionID> sessionCounter;
    std::vector<PlayerGameSessionID> unmatchedPlayers;
};
}