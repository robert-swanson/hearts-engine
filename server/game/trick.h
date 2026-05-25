#pragma once

#include <chrono>
#include <utility>

#include "objects/player.h"
#include "game_observer.h"
#include "../util/logging.h"

namespace Common::Game
{
class Trick
{
public:
    explicit Trick(PlayerArray players, int trickIndex, bool brokenHearts,
                   std::shared_ptr<GameLogger> gameLogger, GameObserver* observer = nullptr):
            mPlayers(std::move(players)), mTrickIndex(trickIndex), mBrokenHearts(brokenHearts),
            mPlayedCards(), mGameLogger(std::move(gameLogger)), mObserver(observer)
    {
    }

    void RunTrick()
    {
        notifyStartTrick();
        for (const PlayerRef& currentPlayer : mPlayers)
        {
            CardCollection legalMoves = legalMovesForPlayer(currentPlayer);
            auto moveStart = std::chrono::steady_clock::now();
            Card card = currentPlayer->getMove(legalMoves);
            long latencyMs = std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::steady_clock::now() - moveStart).count();
            bool autoMoved = currentPlayer->wasLastMoveAuto();
            // RemotePlayer validates and auto-substitutes on bad input, so a card
            // reaching here should always be legal. Keep as a sanity-check assertion.
            ASRT(legalMoves.contains(card), "Illegal card %s reached trick (should have been caught in RemotePlayer)",
                 card.getAbbreviation().c_str());
            currentPlayer->removeCardsFromHand(CardCollection{card});
            mPlayedCards = mPlayedCards + card;
            mBrokenHearts |= (card.getSuit() == HEARTS);
            notifyMove(currentPlayer, card, autoMoved);
            if (mObserver)
                mObserver->onMove(currentPlayer->getTagSession(), latencyMs, autoMoved,
                                  currentPlayer->lastS2CLatencyMs(),
                                  currentPlayer->lastC2SLatencyMs(),
                                  currentPlayer->lastThinkTimeMs());
        }
        determineTrickWinner();
        notifyEndTrick(mPlayers[mTrickWinnerIdx]);
        if (mObserver)
        {
            std::vector<std::string> playerOrder, cards;
            int points = 0;
            for (int i = 0; i < (int)mPlayers.size(); ++i)
            {
                playerOrder.push_back(mPlayers[i]->getTagSession());
                cards.push_back(mPlayedCards[i].getAbbreviation());
                if (mPlayedCards[i].getSuit() == HEARTS) points++;
                if (mPlayedCards[i] == Card(QUEEN, SPADES)) points += Constants::QUEEN_SCORE;
            }
            mObserver->onTrickComplete(playerOrder, cards,
                mPlayers[mTrickWinnerIdx]->getTagSession(), points);
        }
    }

    bool heartsBroken() const
    {
        return mBrokenHearts;
    }

    void determineTrickWinner()
    {
        int winningPlayer = 0;
        Suit trickSuit = mPlayedCards[0].getSuit();
        Rank winningRank = mPlayedCards[0].getRank();
        ASRT_EQ(mPlayedCards.size(), Constants::NUM_PLAYERS);
        for (int playerI = 1; playerI < Constants::NUM_PLAYERS; playerI++)
        {
            Card card = mPlayedCards[playerI];
            if (card.getSuit() == trickSuit and card.getRank() > winningRank)
            {
                winningPlayer = playerI;
                winningRank = card.getRank();
            }
        }
        mTrickWinnerIdx = winningPlayer;
    }

    int getTrickWinnerIdx() const
    {
        return mTrickWinnerIdx;
    }

    CardCollection getPlayedCards()
    {
        return mPlayedCards;
    }

    CardCollection legalMovesForPlayer(PlayerRef player)
    {
        CardCollection legalMoves = player->getHand();
        ASRT(!legalMoves.empty(), "Can't get legal move from empty hand");
        bool leadingPlay = mPlayedCards.empty();
        if (not leadingPlay) {
            Card leadingCard = mPlayedCards[0];
            CardCollection matchingSuit = legalMoves.filter([leadingCard](Card card){
                return card.getSuit() == leadingCard.getSuit();
            });
            if (not matchingSuit.empty())
            {
                legalMoves = matchingSuit;
            }
        }
        if (leadingPlay and not mBrokenHearts) {
            CardCollection nonHeartsLegalMoves = legalMoves.filter([](Card card) {
                return card.getSuit() != HEARTS;
            });
            if (not nonHeartsLegalMoves.empty())
                legalMoves = nonHeartsLegalMoves;
            // In the unlikely event that the leading player has only hearts, they have to lead with a heart
        }
        if (mTrickIndex == 0)
        {
            if (leadingPlay)
            {
                ASRT(legalMoves.contains(Constants::STARTING_CARD), "Starting card not found in first player");
                return CardCollection{Constants::STARTING_CARD};
            }
            legalMoves = legalMoves.filter([](Card card) {
                return (card != Card(QUEEN, SPADES));
            });
        }
        return legalMoves;
    }

private:

    void logTrick()
    {
        std::string msg = "\t\tTrick " + std::to_string(mTrickIndex) + ": [ ";
        for (auto card : mPlayedCards)
        {
            msg += card.getAbbreviation() + " ";
        }
        msg += "] Winner: " + mPlayers[mTrickWinnerIdx]->getTagSession();
        if (mBrokenHearts)
        {
            msg += " (HB)";
        }
        mGameLogger->Log(msg.c_str());
    }

    void notifyStartTrick()
    {
        for (PlayerRef & player : mPlayers)
        {
            player->notifyStartTrick(mTrickIndex, PlayerArrayToIds(mPlayers));
        }
    }

    void notifyMove(PlayerRef player, Card card, bool autoMoved)
    {
        for (PlayerRef & otherPlayer : mPlayers)
        {
            otherPlayer->notifyMove(player->getTagSession(), card, autoMoved);
        }
    }

    void notifyEndTrick(PlayerRef winner)
    {
        for (PlayerRef & player : mPlayers)
        {
            player->notifyEndTrick(winner->getTagSession());
        }
    }

    PlayerArray mPlayers;
    int mTrickIndex;
    bool mBrokenHearts;
    CardCollection mPlayedCards;
    std::shared_ptr<GameLogger> mGameLogger;
    GameObserver* mObserver;
    int mTrickWinnerIdx = -1;
};
}