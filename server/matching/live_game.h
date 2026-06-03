#pragma once

#include <array>
#include <thread>
#include <utility>

#include "server/game/game_recorder.h"
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

        for (SessionRef const &session: mPlayerSessions)
        {
            session->setMessageLogger(messageLogger);
            mGamePlayers.emplace_back(std::make_shared<RemotePlayer>(session->getPlayerTagSession(), session));
        }
    };

    void startGame()
    {
        // The LiveGame object is destroyed as soon as startGame() returns (its
        // caller holds it on the stack), so everything the game thread needs is
        // captured by value: the four players, the logger, and the recorder
        // identity. The RecordingObserver lives inside the thread for the whole
        // game and is used to write the browsable lobby JSON when it finishes.
        std::array<Game::PlayerRef, 4> players =
            {mGamePlayers[0], mGamePlayers[1], mGamePlayers[2], mGamePlayers[3]};
        auto logger = mGameLogger;

        // Shared YYYY-M-D_HH-MM-SS.mmm timestamp — same shape the web backend
        // already parses for tournament directories.
        std::string ts = Dates::GetStrDate('-') + "_" + Dates::GetStrTime('-');
        std::string gameId   = ts + "_" + mGameID;
        std::string playedAt = ts;
        std::filesystem::path resultsDir =
            EnvLoader->has("RESULTS_DIR") ? std::filesystem::path(ENV_STRING("RESULTS_DIR"))
                                          : std::filesystem::path("results");

        // Match the move timeout the Matcher assigns to lobby sessions, so the
        // recorded move-time histogram buckets the right way (see matcher.h).
        long moveTimeoutMs = (EnvLoader && EnvLoader->has("MOVE_TIMEOUT_MS"))
            ? (long)std::stoi(ENV_STRING("MOVE_TIMEOUT_MS")) : 15000;

        std::thread([players, logger, gameId, playedAt, resultsDir, moveTimeoutMs]() {
            Common::Game::RecordingObserver recorder(gameId, "lobby", moveTimeoutMs);
            // Seating order = the order players were dealt into the game.
            for (const auto& p : players)
                recorder.result.playerOrder.push_back(p->getTagSession());

            Common::Game::Game game(
                {players[0], players[1], players[2], players[3]}, logger, &recorder);
            game.runGame();

            try
            {
                Common::Game::writeLobbyGameResult(resultsDir, recorder.result, playedAt);
            }
            catch (const std::exception& e)
            {
                logger->Log("Failed to write lobby game result: %s", e.what());
            }
        }).detach();
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