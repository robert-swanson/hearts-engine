#pragma once


#include <gtest/gtest.h>
#include <gmock/gmock.h>

using namespace Common::Game;

class MockPlayer final : public Common::Game::Player
{
public:
    MockPlayer() : Player("mock_player"){
    };

    MOCK_METHOD(void, notifyStartGame, (std::vector<PlayerID> playerOrder));
    MOCK_METHOD(void, notifyStartRound, (int roundIndex, PassDirection passDirection, CardCollection hand));
    MOCK_METHOD(CardCollection, getCardsToPass, (PassDirection direction));
    MOCK_METHOD(void, notifyReceivedCards, (const CardCollection& receivedCards));
    MOCK_METHOD(void, notifyStartTrick, (int trickIndex, std::vector<PlayerID> playerOrder));
    MOCK_METHOD(Card, getMove, (const CardCollection& legalPlays));
    MOCK_METHOD(void, notifyMove, (PlayerID playerID, Card card));
    MOCK_METHOD(void, notifyEndTrick, (PlayerID winningPlayer));
    MOCK_METHOD(void, notifyEndRound, ((std::map<PlayerID, int> & roundScores)));
    MOCK_METHOD(void, notifyEndGame, ((std::map<PlayerID, int> & gameScores), PlayerID winner));

    MOCK_METHOD(void, resetReceivedTrickCards, ());
    MOCK_METHOD(void, receiveTrick, (const CardCollection& trickWinnings));
    MOCK_METHOD(CardCollection, getReceivedTrickCard, ());
    MOCK_METHOD(Card, getPlay, (CardCollection& legalPlays));
};