#pragma once

#include <utility>

#include "lobby.h"

namespace Common::Server {

class LiveGame
{
public:

    LiveGame(LobbyCode code, std::vector <SessionRef> players) : mCode(std::move(code)), mGameID(), mPlayerSessions(players), mGamePlayers()
    {
        mGameID = mCode + "_" + std::to_string(mPlayerSessions[0].get()->getGameSessionID());
        std::string msgLoggerName = mGameID + "_" + MESSAGE_LOG_NAME + ".log";
        auto messageLogger = std::make_shared<MessageLogger>(makeGameLogDirPath(MESSAGE_LOG_NAME) / msgLoggerName);

        std::string gameLoggerName = mGameID + "_" + GAME_LOG_NAME + ".log";
        mGameLogger = std::make_shared<GameLogger>(makeGameLogDirPath(GAME_LOG_NAME) / gameLoggerName);

        for (SessionRef const session: mPlayerSessions)
        {
            session->setMessageLogger(messageLogger);
            mGamePlayers.emplace_back(std::make_shared<RemotePlayer>(session->getPlayerTagSession(), session));
        }
    };

    void startGame()
    {
        Common::Game::Game game({mGamePlayers[0], mGamePlayers[1], mGamePlayers[2], mGamePlayers[3]}, mGameLogger);
        std::thread(&Game::Game::runGame, game).detach();
    }

private:
    static std::filesystem::path makeGameLogDirPath(const std::string & logDirName)
    {
        std::filesystem::path logPath = ENV_STRING("LOG_DIR");
        return logPath / SERVER_LOG_DIRNAME / logDirName / Dates::GetStrDate('-') / Dates::GetStrTime(':');
    }

    LobbyCode mCode;
    std::string mGameID;
    std::vector <SessionRef> mPlayerSessions;
    std::vector<Game::PlayerRef> mGamePlayers{};
    std::shared_ptr<GameLogger> mGameLogger;
};

}