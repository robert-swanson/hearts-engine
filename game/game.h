#pragma once

#include <utility>

#include "player.h"
#include "round.h"

namespace Common::Game
{
class Game
{
public:
    explicit Game(std::array<Player, Constants::NUM_PLAYERS> players): mPlayers(std::move(players))
    {
    }

    void startGame()
    {
        Round round(mPlayers);
        round.startRound();
    }

private:
    std::array<Player, Constants::NUM_PLAYERS> mPlayers;
};
}