#pragma once

#include <iostream>
#include <utility>
#include "card_collection.h"
#include "types.h"

namespace Common::Game
{
class Player
{
public:
    Player(std::string  name) : mName(std::move(name)), mHand(), mTrickPlayedCards(), mScore(0) {}

    void assignHand(CardCollection hand)
    {
        mHand = std::move(hand);
    }

    CardCollection getCardsToPass(PassDirection direction) {
        auto cardsToPass = mHand.subset(0, Constants::NUM_CARDS_TO_PASS);
        mHand = mHand - cardsToPass;
        return cardsToPass;
    }

    void receiveCards(const CardCollection& receivedCards)
    {
        mHand = mHand + receivedCards;
    }

    void resetReceivedTrickCards()
    {
        mTrickPlayedCards = CardCollection{};
    }

    void receiveTrick(const CardCollection& trickWinnings)
    {
        mTrickPlayedCards = mTrickPlayedCards + trickWinnings;
    }


    CardCollection getHand()
    {
        return mHand;
    }

    CardCollection getRecievedTrickCards()
    {
        return mTrickPlayedCards;
    }

    Card getPlay(const CardCollection& legalPlays)
    {
        Card play = legalPlays[0];
        mHand = mHand - CardCollection{play};
        return play;
    }

    int getScore() const
    {
        return mScore;
    }

    void addPoints(int newPoints)
    {
        mScore += newPoints;
    }

    std::string getName()
    {
        return mName;
    }

private:
    std::string mName;
    CardCollection mHand;
    CardCollection mTrickPlayedCards;
    int mScore;
};

using PlayerRef = std::reference_wrapper<Player>;
using PlayerArray = std::array<PlayerRef, Constants::NUM_PLAYERS>;

PlayerArray LeftShiftArray(const PlayerArray & arr, size_t offset) {
    PlayerArray result = arr;

    for (size_t i = 0; i < arr.size(); i++) {
        size_t newIndex = (i - offset) % arr.size();
        result[newIndex] = arr[i];
    }

    return result;
}

}