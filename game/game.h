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

        LOG("Final rankings:");
        for (int i = 0; i < Constants::NUM_PLAYERS; i++)
        {
            Player & player = mRankings[mRankings.size()-1-i].get();
            LOG("%d: %s (%d points)", i+1, player.getName().c_str(), player.getScore());
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
                if (mRankings[b].get().getScore() < mRankings[b+1].get().getScore())
                {
                    PlayerRef temp = mRankings[b];
                    mRankings[b] = mRankings[b+1];
                    mRankings[b+1] = temp;
                }
                else
                    break;
            }
        }
        mMaxScore = mRankings[0].get().getScore();
    }

    PlayerArray mPlayers;
    PlayerArray mRankings;
    int mMaxScore;
};
}