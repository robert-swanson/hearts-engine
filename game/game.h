#pragma once

#include <utility>

#include "objects/player.h"
#include "round.h"
#include "../util/logging.h"

namespace Common::Game
{
class Game
{
public:
    explicit Game(PlayerArray players, std::shared_ptr<GameLogger> gameLogger):
    mPlayers(players), mRankings(players), mMaxScore(0), mGameLogger(std::move(gameLogger))
    {
    }

    PlayerArray runGame()
    {
        std::string msg = "Player order: ";
        for (const auto& playerRef: mPlayers)
        {
            msg += playerRef->getTagSession() + ", ";
        }
        mGameLogger->Log(msg.c_str());

        PassDirection passDirection = Left;
        updateRankings();
        notifyStartGame();
        while (mMaxScore <= Constants::GAME_END_SCORE)
        {
            Round round(mCurrentRoundIdx, mPlayers, passDirection, mGameLogger);
            round.runDeal();
            passDirection = NextPassDirection(passDirection);
            updateRankings();
            mCurrentRoundIdx++;
        }
        notifyEndGame();
        mGameLogger->Log("Final scores:");
        for (int i = 0; i < Constants::NUM_PLAYERS; i++)
        {
            auto player = mRankings[mRankings.size()-1-i];
            mGameLogger->Log("%d: %s (%d points)", i+1, player->getTagSession().c_str(), player->getScore());
        }
        return mRankings;
    }

private:
    void notifyStartGame()
    {
        for (PlayerRef & player : mPlayers)
        {
            player->notifyStartGame(PlayerArrayToIds(mPlayers));
        }
    }

    void notifyEndGame()
    {
        std::map<PlayerID, int> playerScores;
        for (PlayerRef & player : mPlayers)
        {
            playerScores[player->getTagSession()] = player->getScore();
        }
        for (PlayerRef & player : mPlayers)
        {
            player->notifyEndGame(playerScores, mRankings[0]->getTagSession());
        }
    }


    // Sort by decreasing scores
    void updateRankings()
    {
        for (int a = 1; a < mRankings.size(); a++)
        {
            for (int b = a - 1; b >= 0; b--)
            {
                if (mRankings[b]->getScore() < mRankings[b+1]->getScore())
                {
                    PlayerRef temp = mRankings[b];
                    mRankings[b] = mRankings[b+1];
                    mRankings[b+1] = temp;
                }
                else
                    break;
            }
        }
        mMaxScore = mRankings[0]->getScore();
    }

    PlayerArray mPlayers;
    PlayerArray mRankings;
    int mMaxScore;
    int mCurrentRoundIdx = 0;
    std::shared_ptr<GameLogger> mGameLogger;
};
}