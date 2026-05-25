#pragma once

#include <utility>

#include "objects/player.h"
#include "round.h"
#include "game_observer.h"
#include "../util/logging.h"

namespace Common::Game
{
class Game
{
public:
    explicit Game(PlayerArray players, std::shared_ptr<GameLogger> gameLogger,
                  GameObserver* observer = nullptr):
    mPlayers(players), mRankings(players), mMaxScore(0),
    mGameLogger(std::move(gameLogger)), mObserver(observer)
    {
    }

    PlayerArray runGame()
    {
        try
        {
            PassDirection passDirection = Left;
            updateRankings();
            notifyStartGame();
            while (mMaxScore <= Constants::GAME_END_SCORE)
            {
                Round round(mCurrentRoundIdx, mPlayers, passDirection, mGameLogger, mObserver);
                round.runDeal();
                passDirection = NextPassDirection(passDirection);
                updateRankings();
                mCurrentRoundIdx++;
            }
            notifyEndGame();
            return mRankings;
        }
        catch (const std::exception& e)
        {
            mGameLogger->Log("Game crash: %s", e.what());
            return mPlayers;
        }
        catch (...)
        {
            mGameLogger->Log("Game crash: unknown error");
            return mPlayers;
        }
    }

    int getRoundsPlayed() const { return mCurrentRoundIdx; }

private:
    void notifyStartGame()
    {
        for (PlayerRef & player : mPlayers)
            player->notifyStartGame(PlayerArrayToIds(mPlayers));
    }

    void notifyEndGame()
    {
        std::map<PlayerID, int> playerScores;
        for (PlayerRef & player : mPlayers)
            playerScores[player->getTagSession()] = player->getScore();

        std::string winner = mRankings[3]->getTagSession();
        for (PlayerRef & player : mPlayers)
            player->notifyEndGame(playerScores, winner);

        if (mObserver)
            mObserver->onGameComplete(playerScores, winner);
    }

    void updateRankings()
    {
        for (int a = 1; a < (int)mRankings.size(); a++)
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
    GameObserver* mObserver;
};
}
