#pragma once

#include <map>
#include <string>
#include <utility>
#include <vector>

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
                  GameObserver* observer = nullptr,
                  std::string gameId = "", std::string resultsRelDir = "",
                  std::map<std::string, std::string> playerFullIds = {}):
    mPlayers(players), mRankings(players), mMaxScore(0),
    mGameLogger(std::move(gameLogger)), mObserver(observer),
    mGameId(std::move(gameId)), mResultsRelDir(std::move(resultsRelDir)),
    mPlayerFullIds(std::move(playerFullIds))
    {
    }

    PlayerArray runGame()
    {
        try
        {
            PassDirection passDirection = Left;
            updateRankings();
            notifyStartGame();
            while (mMaxScore < Constants::GAME_END_SCORE)
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
        std::vector<PlayerID> order = PlayerArrayToIds(mPlayers);
        // Seat ids as recorded in the game detail JSON, parallel to `order`.
        // Left empty when no mapping was supplied (lobby games record the
        // protocol id verbatim), so the field is simply omitted on the wire.
        std::vector<std::string> fullIds;
        if (!mPlayerFullIds.empty())
            for (const PlayerID& id : order)
            {
                auto it = mPlayerFullIds.find(id);
                fullIds.push_back(it == mPlayerFullIds.end() ? id : it->second);
            }

        for (PlayerRef & player : mPlayers)
            player->notifyStartGame(order, mGameId, mResultsRelDir, fullIds);
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
    std::string mGameId;         // recorded game id, forwarded to clients in start_game
    std::string mResultsRelDir;  // game's results dir relative to RESULTS_DIR (e.g. "lobby")
    // Protocol id ("player_tag(session_id)") → recorded id. Empty when the two
    // are the same (lobby); populated for tournaments, which record
    // team-qualified ids. See Tags::PLAYER_FULL_IDS.
    std::map<std::string, std::string> mPlayerFullIds;
};
}
