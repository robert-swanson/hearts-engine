#pragma once

#include <iostream>
#include <utility>
#include "card_collection.h"
#include "round.h"

namespace Common::Game
{
class Player
{
public:
    Player(std::string  name) : mName(std::move(name)), mHand(), mDiscarded() {}

    void assignHand(CardCollection hand)
    {
        mHand = std::move(hand);
    }

    CardCollection getCardsToPass(PassDirection direction) {
        auto cardsToPass = mHand.subset(0, Constants::NUM_CARDS_TO_PASS);
        mHand = mHand - cardsToPass;
        return cardsToPass;
    }


    void addDiscarded(const CardCollection& discarded)
    {
        mDiscarded = mDiscarded + discarded;
    }

    void receiveCards(const CardCollection& receivedCards)
    {
        mHand = mHand + receivedCards;
    }

    Card getPlay(const CardCollection& legalPlays)
    {
        return legalPlays[0];
    }

private:
    std::string mName;
    CardCollection mHand;
    CardCollection mDiscarded;
    int mScore;
};
}