#include <gtest/gtest.h>

#include "server/game/trick.h"
#include "server/game/objects/constants.h"
#include "mocks/mock_player.h"
#include "mocks/mock_trick.h"

using namespace Common::Game;
using namespace testing;

class TrickTest : public ::testing::Test
{
protected:
    std::shared_ptr<MockPlayer> mPlayer1 = std::make_shared<MockPlayer>();
    std::shared_ptr<MockPlayer> mPlayer2 = std::make_shared<MockPlayer>();
    std::shared_ptr<MockPlayer> mPlayer3 = std::make_shared<MockPlayer>();
    std::shared_ptr<MockPlayer> mPlayer4 = std::make_shared<MockPlayer>();

    PlayerArray mPlayers{mPlayer1, mPlayer2, mPlayer3, mPlayer4};
    Trick mTrick{mPlayers, 0, false, std::make_shared<Common::GameLogger>(stdout)};
    std::vector<CardCollection> mHands = CardCollection::OrderedDeck().divide(Common::Constants::NUM_PLAYERS);

    void SetUp() override
    {
        mPlayer1->assignHand(mHands[3]);
        mPlayer2->assignHand(mHands[0]);
        mPlayer3->assignHand(mHands[1]);
        mPlayer4->assignHand(mHands[2]);

        // Return first card in hand
        auto returnFirstCard = [](const CardCollection& legalPlays){return legalPlays[0];};
        EXPECT_CALL(*mPlayer1, getMove(::testing::_)).WillOnce(Invoke(returnFirstCard));
        EXPECT_CALL(*mPlayer2, getMove(::testing::_)).WillOnce(Invoke(returnFirstCard));
        EXPECT_CALL(*mPlayer3, getMove(::testing::_)).WillOnce(Invoke(returnFirstCard));
        EXPECT_CALL(*mPlayer4, getMove(::testing::_)).WillOnce(Invoke(returnFirstCard));
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
    EXPECT_TRUE(mHands[3].contains(cards[0]));

    EXPECT_FALSE(mPlayer1->getHand().contains(cards[0]));
    EXPECT_FALSE(mPlayer2->getHand().contains(cards[1]));
    EXPECT_FALSE(mPlayer3->getHand().contains(cards[2]));
    EXPECT_FALSE(mPlayer4->getHand().contains(cards[3]));
}

TEST_F(TrickTest, VerifiesFirstCard)
{
    mPlayers[0].get()->assignHand(CardCollection{{ACE, DIAMONDS}});
    EXPECT_DEATH(mTrick.RunTrick(), "Starting card not found in first player");
    mPlayers[0].get()->assignHand(CardCollection{Common::Constants::STARTING_CARD});
    EXPECT_NO_FATAL_FAILURE(mTrick.RunTrick());
}

TEST_F(TrickTest, LegalMovesForPlayer_LeadingPlayExcludesPoints)
{
    mTrick.RunTrick();
    mPlayers[0].get()->assignHand(CardCollection{{"AC", "AH", "QS"}});
    auto legalMoves = mTrick.legalMovesForPlayer(mPlayers[0]);
    EXPECT_FALSE(legalMoves.contains([](Card card){return card.getSuit() == HEARTS;}));
    EXPECT_FALSE(legalMoves.contains(Card(QUEEN, SPADES)));
    EXPECT_TRUE(legalMoves.contains(Card(ACE, CLUBS)));
}