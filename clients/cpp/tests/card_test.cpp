#include "clients/cpp/sdk/card.h"
#include "clients/cpp/sdk/card_set.h"

#include <gtest/gtest.h>

using namespace hearts;

TEST(Card, RoundTripsThroughAbbreviation) {
  const char* abbrevs[] = {"2C", "TH", "QS", "AD", "KH", "9C", "JS"};
  for (const char* a : abbrevs) {
    Card c = Card::fromAbbrev(a);
    EXPECT_EQ(c.abbrev().str(), a);
  }
}

TEST(Card, ParsesRankAndSuit) {
  Card qs = Card::fromAbbrev("QS");
  EXPECT_EQ(qs.rank(), Rank::Queen);
  EXPECT_EQ(qs.suit(), Suit::Spades);

  Card th = Card::fromAbbrev("TH");
  EXPECT_EQ(th.rank(), Rank::Ten);
  EXPECT_EQ(th.suit(), Suit::Hearts);
}

TEST(Card, RejectsMalformed) {
  EXPECT_THROW(Card::fromAbbrev("Q"), std::invalid_argument);
  EXPECT_THROW(Card::fromAbbrev("QSS"), std::invalid_argument);
  EXPECT_THROW(Card::fromAbbrev("1C"), std::invalid_argument);
  EXPECT_THROW(Card::fromAbbrev("QX"), std::invalid_argument);
}

TEST(Card, PenaltyPoints) {
  EXPECT_EQ(Card::fromAbbrev("QS").points(), 13);
  EXPECT_EQ(Card::fromAbbrev("AH").points(), 1);
  EXPECT_EQ(Card::fromAbbrev("2H").points(), 1);
  EXPECT_EQ(Card::fromAbbrev("KS").points(), 0);
  EXPECT_EQ(Card::fromAbbrev("2C").points(), 0);
}

TEST(Card, OrdersByRankThenSuit) {
  EXPECT_TRUE(Card::fromAbbrev("2C") < Card::fromAbbrev("3C"));
  EXPECT_TRUE(Card::fromAbbrev("AH") < Card::fromAbbrev("AD"));  // Hearts < Diamonds
  EXPECT_FALSE(Card::fromAbbrev("KS") < Card::fromAbbrev("KS"));
}

TEST(CardSet, PushContainsRemove) {
  CardSet set;
  EXPECT_TRUE(set.empty());
  set.push_back(Card::fromAbbrev("QS"));
  set.push_back(Card::fromAbbrev("2C"));
  EXPECT_EQ(set.size(), 2u);
  EXPECT_TRUE(set.contains(Card::fromAbbrev("QS")));
  EXPECT_FALSE(set.contains(Card::fromAbbrev("3C")));

  EXPECT_TRUE(set.remove(Card::fromAbbrev("QS")));
  EXPECT_FALSE(set.contains(Card::fromAbbrev("QS")));
  EXPECT_EQ(set.size(), 1u);
  EXPECT_FALSE(set.remove(Card::fromAbbrev("QS")));  // already gone
}

TEST(CardSet, IteratesInInsertionOrder) {
  CardSet set;
  set.push_back(Card::fromAbbrev("AH"));
  set.push_back(Card::fromAbbrev("2C"));
  set.push_back(Card::fromAbbrev("QS"));
  std::string seen;
  for (Card c : set) seen += c.abbrev().str();
  EXPECT_EQ(seen, "AH2CQS");
}

TEST(CardSet, ThrowsWhenOverCapacity) {
  BasicCardSet<2> tiny;
  tiny.push_back(Card::fromAbbrev("2C"));
  tiny.push_back(Card::fromAbbrev("3C"));
  EXPECT_THROW(tiny.push_back(Card::fromAbbrev("4C")), std::out_of_range);
}
