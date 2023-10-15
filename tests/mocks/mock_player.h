#pragma once


#include <gtest/gtest.h>
#include <gmock/gmock.h>

using namespace Common::Game;

class MockPlayer : public Common::Game::Player
{
public:
    MockPlayer() : Player("mock_player"){
    };

    MOCK_METHOD(void, assignHand, (CardCollection const & hand));
    MOCK_METHOD(CardCollection, getCardsToPass, (PassDirection direction));
    MOCK_METHOD(void, receiveCards, (CardCollection& receivedCards));
    MOCK_METHOD(void, resetReceivedTrickCards, ());
    MOCK_METHOD(void, receiveTrick, (const CardCollection& trickWinnings));
    MOCK_METHOD(CardCollection, getHand, ());
    MOCK_METHOD(CardCollection, getReceivedTrickCard, ());
    MOCK_METHOD(Card, getPlay, (CardCollection& legalPlays));
};