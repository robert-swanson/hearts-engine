#pragma once

#include <algorithm>
#include <random>
#include <utility>

#include "server/game/game.h"
#include "live_game.h"

namespace Common::Server {


class Lobby {
public:
    explicit Lobby(LobbyCode code): mCode(std::move(code)), mUnmatchedPlayers()
    {
    }

    void addPlayer(const SessionRef& session)
    {
        std::lock_guard<std::mutex> lock(mLock);
        // Drop queued players whose client has since disconnected — otherwise a
        // new player gets matched into a game of dead seats (which instantly
        // auto-plays their whole game), and stale sessions accumulate forever.
        mUnmatchedPlayers.erase(
            std::remove_if(mUnmatchedPlayers.begin(), mUnmatchedPlayers.end(),
                           [](const SessionRef& s) { return s->isDisconnected(); }),
            mUnmatchedPlayers.end());
        mUnmatchedPlayers.push_back(session);
        if (mUnmatchedPlayers.size() >= 4)
        {
            matchFourPlayers();
        }
    }

private:
    void matchFourPlayers()
    {
        if (mUnmatchedPlayers.size() < 4)
        {
            return;
        }
        std::vector game_players(mUnmatchedPlayers.begin(), mUnmatchedPlayers.begin() + 4);
        mUnmatchedPlayers.erase(mUnmatchedPlayers.begin(), mUnmatchedPlayers.begin() + 4);
        std::shuffle(game_players.begin(), game_players.end(), std::mt19937{std::random_device{}()});
        try
        {
            auto game = LiveGame(mCode, game_players);
            game.startGame();
        }
        catch (const std::exception& e)
        {
            // Game setup failed (e.g. log path problem). Never let the exception
            // escape into the connection thread that happened to complete the
            // match — that would tear down an unrelated client's connection.
            LOG("Failed to start game in lobby '%s': %s", mCode.c_str(), e.what());
        }
    }

    LobbyCode mCode;
    std::vector<SessionRef> mUnmatchedPlayers;
    std::mutex mLock;
};

}