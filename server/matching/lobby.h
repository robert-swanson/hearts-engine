#pragma once

#include <utility>

#include "../../game/game.h"
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
        auto game = LiveGame(mCode, game_players);
        game.startGame();
    }

    LobbyCode mCode;
    std::vector<SessionRef> mUnmatchedPlayers;
    std::mutex mLock;
};

}