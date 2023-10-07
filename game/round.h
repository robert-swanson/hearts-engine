#pragma once

#include "player.h"
#include "types.h"

namespace Common::Game
{
int PlayerToPassTo(int fromPlayer, PassDirection passDirection)
{
    switch (passDirection)
    {
        case Left:
            return (fromPlayer + 1) % static_cast<int>(Constants::NUM_PLAYERS);
        case Right:
            return (fromPlayer - 1) % static_cast<int>(Constants::NUM_PLAYERS);
        case Across:
            return (fromPlayer + 2) % static_cast<int>(Constants::NUM_PLAYERS);
        default:
            return fromPlayer;
    }
}

class Round
{
public:
    explicit Round(std::array<Player, Constants::NUM_PLAYERS> &players): mPlayers(players), mStartingPlayer(-1), mCurrentPlayer(-1)
    {
    }

    void dealCards()
    {
        auto fullDeck = CardCollection::ShuffledDeck();
        auto hands = fullDeck.divide(Constants::NUM_PLAYERS);

        for (int i = 0; i < Constants::NUM_PLAYERS; i++)
        {
            if (hands[i].contains(Card(TWO, SPADES)))
            {
                mStartingPlayer = i;
                mCurrentPlayer = i;
            }
            mPlayers[i].assignHand(hands[i]);
        }

    }

    void passCards(PassDirection passDirection)
    {
        if (passDirection == Keeper)
            return;

        std::vector<CardCollection> passedCards;
        for (Player& player: mPlayers)
        {
            auto cards = player.getCardsToPass(passDirection);
            ASRT_EQ(cards.size(), Constants::NUM_CARDS_TO_PASS);
            passedCards.push_back(cards);
        }

        for (int passFrom = 0; passFrom < Constants::NUM_PLAYERS; passFrom++)
        {
            auto passTo = PlayerToPassTo(passFrom, passDirection);
            mPlayers[passTo].receiveCards(passedCards[passFrom]);
        }
    }

    void startRound()
    {
    }

private:
    std::array<Player, Constants::NUM_PLAYERS> & mPlayers;
    size_t mStartingPlayer;
    size_t mCurrentPlayer;
    CardCollection table;
};

}