#pragma once

#include <iostream>
#include <utility>
#include "card_collection.h"
#include "types.h"
#include <map>

namespace Common::Game
{
class Player
{
public:
    explicit Player(PlayerID playerId) : mPlayerID(std::move(playerId)), mHand(), mTrickPlayedCards(), mScore(0) {}


    // Notifying virtual functions
    virtual void notifyStartGame(std::vector<PlayerID> playerOrder) = 0;
    virtual void notifyStartRound(int roundIndex, PassDirection passDirection, CardCollection hand) = 0;
    virtual CardCollection getCardsToPass(PassDirection direction) = 0;
    virtual void notifyReceivedCards(const CardCollection& receivedCards) = 0;
    virtual void notifyStartTrick(int trickIndex, std::vector<PlayerID> playerOrder) = 0;
    virtual Card getMove(const CardCollection& legalPlays) = 0;
    virtual void notifyMove(PlayerID playerID, Card card) = 0;
    virtual void notifyEndTrick(PlayerID winningPlayer) = 0;
    virtual void notifyEndRound(std::map<PlayerID, int> & roundScores) = 0;
    virtual void notifyEndGame(std::map<PlayerID, int> & gameScores, PlayerID winner) = 0;


    void assignHand(CardCollection const & hand)
    {
        mHand = hand;
    }

    void removeCardsFromHand(CardCollection const & cards)
    {
        mHand = mHand - cards;
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

    CardCollection getReceivedTrickCards()
    {
        return mTrickPlayedCards;
    }

    [[nodiscard]] int getScore() const
    {
        return mScore;
    }

    void addPoints(int newPoints)
    {
        mScore += newPoints;
    }

    std::string getName()
    {
        return mPlayerID;
    }

    [[nodiscard]] const CardCollection &getMHand() const {
        return mHand;
    }

private:
    std::string mPlayerID;
    CardCollection mHand;
    CardCollection mTrickPlayedCards;
    int mScore;
};

using PlayerRef = std::shared_ptr<Player>;
using PlayerArray = std::array<PlayerRef, Constants::NUM_PLAYERS>;

PlayerArray LeftShiftArray(const PlayerArray & arr, size_t offset) {
    PlayerArray result = arr;

    for (size_t i = 0; i < arr.size(); i++) {
        size_t newIndex = (i - offset) % arr.size();
        result[newIndex] = arr[i];
    }

    return result;
}

std::vector<PlayerID> PlayerArrayToIds(const PlayerArray & arr) {
    std::vector<PlayerID> result;
    for (const PlayerRef & player : arr) {
        result.push_back(player->getName());
    }
    return result;
}

}