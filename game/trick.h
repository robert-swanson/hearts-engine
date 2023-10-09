#pragma once

#include <utility>

#include "objects/player.h"
#include "../util/logging.h"

namespace Common::Game
{
class Trick
{
public:
    explicit Trick(PlayerArray players, int trickIndex, bool brokenHearts):
            mPlayers(players), mTrickIndex(trickIndex), mBrokenHearts(brokenHearts), mPlayedCards()
    {
    }

    void RunTrick()
    {
        printf("Trick %d: ", mTrickIndex);
        for (PlayerRef currentPlayer : mPlayers)
        {
            CardCollection legalMoves = legalMovesForPlayer(currentPlayer);
            Card card = currentPlayer.get().getPlay(legalMoves);
            printf("%s: %s, ", currentPlayer.get().getName().c_str(), card.getAbbreviation().c_str());
            ASRT(legalMoves.contains(card), "Player played illegal card %s", card.getAbbreviation().c_str());
            mPlayedCards = mPlayedCards + card;
            mBrokenHearts |= (card.getSuit() == HEARTS);
        }
    }

    bool heartsBroken() const
    {
        return mBrokenHearts;
    }

    int getTrickWinner()
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
        printf("Winner = %s\n", mPlayers[winningPlayer].get().getName().c_str());
        return winningPlayer;
    }
private:
    CardCollection legalMovesForPlayer(PlayerRef player)
    {
        CardCollection legalMoves = player.get().getHand();
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
                return {Constants::STARTING_CARD};
            }
            legalMoves = legalMoves.filter([](Card card) {
                return (card != Card(QUEEN, SPADES));
            });
        }
        return legalMoves;
    }

    PlayerArray mPlayers;
    int mTrickIndex;
    bool mBrokenHearts;
    CardCollection mPlayedCards;
};
}