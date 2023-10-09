#pragma once

#include <utility>

#include "objects/player.h"
#include "deal.h"
#include "../util/logging.h"

namespace Common::Game
{
class Game
{
public:
    explicit Game(PlayerArray players): mPlayers(players), mRankings(players), mMaxScore(0)
    {
    }

    PlayerArray runGame()
    {
        LOG("starting game");
        PassDirection passDirection = Left;
        updateRankings();
        while (mMaxScore <= Constants::GAME_END_SCORE)
        {
            Deal deal(mPlayers, passDirection);
            deal.runDeal();
            passDirection = NextPassDirection(passDirection);
            updateRankings();
            LOG("Max score %d", mMaxScore);
        }
        return mRankings;
    }

private:
    // Sort by decreasing scores
    void updateRankings()
    {
        for (int a = 1; a < mRankings.size(); a++)
        {
            for (int b = a - 1; b >= 0; b--)
            {
                if (mPlayers[b].get().getScore() < mPlayers[b+1].get().getScore())
                {
                    PlayerRef temp = mPlayers[b];
                    mPlayers[b] = mPlayers[b+1];
                    mPlayers[b+1] = temp;
                }
                else
                    break;
            }
        }
        mMaxScore = mPlayers[0].get().getScore();
    }

    PlayerArray mPlayers;
    PlayerArray mRankings;
    int mMaxScore;
};
}