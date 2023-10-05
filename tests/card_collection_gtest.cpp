#include <gtest/gtest.h>

#include "../game/card_collection.h"

using namespace Common::Game;

TEST(CardCollection, DeckHas52Cards)
{
    Common::Game::CardCollection deck;
    deck.shuffle();
    ASSERT_EQ(deck.size(), 52);
}

TEST(CardCollection, DeckIsUnique)
{
    Common::Game::CardCollection deck;
    deck.shuffle();
    std::set<Card> seen_cards;
    for (Card card : deck)
    {
        ASSERT_TRUE(seen_cards.find(card) == seen_cards.end());
        seen_cards.insert(card);
    }
}
