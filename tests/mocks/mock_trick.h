#pragma once


#include <gtest/gtest.h>
#include <gmock/gmock.h>

using namespace Common::Game;

class MockTrick : public Common::Game::Trick
{
public:
    MockTrick(PlayerArray players) : Common::Game::Trick(players, 0, false){
    };

    MOCK_METHOD(int, getTrickWinner, ());
    MOCK_METHOD(int, legalMovesForPlayer, ());
};