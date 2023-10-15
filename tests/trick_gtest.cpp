#include <gtest/gtest.h>

#include "../game/trick.h"
#include "../game/objects/constants.h"
#include "mocks/mock_player.h"
#include "mocks/mock_trick.h"

using namespace Common::Game;

class TrickTest : public ::testing::Test
{
protected:
    MockPlayer mPlayer1, mPlayer2, mPlayer3, mPlayer4;
    PlayerArray mPlayers{mPlayer1, mPlayer2, mPlayer3, mPlayer4};
    Trick mTrick{mPlayers, 0, false};
    std::vector<CardCollection> mHands = CardCollection::OrderedDeck().divide(Common::Constants::NUM_PLAYERS);

    void SetUp() override
    {
        mPlayers[0].get().assignHand(mHands[3]);
        mPlayers[1].get().assignHand(mHands[0]);
        mPlayers[2].get().assignHand(mHands[1]);
        mPlayers[3].get().assignHand(mHands[2]);
    }
};

TEST_F(TrickTest, TrickTakesCardFromEachPlayer)
{
    mTrick.RunTrick();
    auto cards = mTrick.getPlayedCards();

    EXPECT_EQ(cards.size(), Common::Constants::NUM_PLAYERS);
    EXPECT_EQ(cards[0], Card(TWO, CLUBS));
    EXPECT_TRUE(mHands[0].contains(cards[1]));
    EXPECT_TRUE(mHands[1].contains(cards[2]));
    EXPECT_TRUE(mHands[2].contains(cards[3]));
}

TEST_F(TrickTest, VerifiesFirstCard)
{
    mPlayers[0].get().assignHand(CardCollection{{ACE, DIAMONDS}});
    EXPECT_DEATH(mTrick.RunTrick(), "Starting card not found in first player");
    mPlayers[0].get().assignHand(CardCollection{Common::Constants::STARTING_CARD});
    EXPECT_NO_FATAL_FAILURE(mTrick.RunTrick());
}

TEST_F(TrickTest, LegalMovesForPlayer_LeadingPlayExcludesPoints)
{
    mTrick.RunTrick();
    mPlayers[0].get().assignHand(CardCollection{{{ACE, CLUBS}, {ACE, HEARTS}, {QUEEN, SPADES}}});
    auto legalMoves = mTrick.legalMovesForPlayer(mPlayers[0]);
    EXPECT_FALSE(legalMoves.contains([](Card card){return card.getSuit() == HEARTS;}));
    EXPECT_FALSE(legalMoves.contains(Card(QUEEN, SPADES)));
    EXPECT_TRUE(legalMoves.contains(Card(ACE, CLUBS)));
}