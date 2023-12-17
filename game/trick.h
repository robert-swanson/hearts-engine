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
        notifyStartTrick();
        for (PlayerRef currentPlayer : mPlayers)
        {
            CardCollection legalMoves = legalMovesForPlayer(currentPlayer);
            Card card = currentPlayer->getMove(legalMoves);
            currentPlayer->removeCardsFromHand(CardCollection{card});
            printf("%s: %s, ", currentPlayer->getName().c_str(), card.getAbbreviation().c_str());
            ASRT(legalMoves.contains(card), "Player played illegal card %s", card.getAbbreviation().c_str());
            mPlayedCards = mPlayedCards + card;
            mBrokenHearts |= (card.getSuit() == HEARTS);
            notifyMove(currentPlayer, card);
        }
        notifyEndTrick(mPlayers[getTrickWinner()]);
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
        printf("Winner = %s\n", mPlayers[winningPlayer]->getName().c_str());
        return winningPlayer;
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
    void notifyStartTrick()
    {
        for (PlayerRef & player : mPlayers)
        {
            player->notifyStartTrick(mTrickIndex, PlayerArrayToIds(mPlayers));
        }
    }

    void notifyMove(PlayerRef player, Card card)
    {
        for (PlayerRef & otherPlayer : mPlayers)
        {
            otherPlayer->notifyMove(player->getName(), card);
        }
    }

    void notifyEndTrick(PlayerRef winner)
    {
        for (PlayerRef & player : mPlayers)
        {
            player->notifyEndTrick(winner->getName());
        }
    }

    PlayerArray mPlayers;
    int mTrickIndex;
    bool mBrokenHearts;
    CardCollection mPlayedCards;
};
}