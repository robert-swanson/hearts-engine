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

TEST(CardCollection, Divide_Sizes)
{
    Common::Game::CardCollection deck;
    deck.shuffle();
    auto decks = deck.divide(4);
    ASSERT_EQ(decks.size(), 4);
    for (auto subDeck : decks)
        ASSERT_EQ(subDeck.size(), 13);
}


TEST(CardCollection, Divide_Unique)
{
    Common::Game::CardCollection deck;
    deck.shuffle();
    auto decks = deck.divide(4);
    std::set<Card> seen_cards;
    for (auto subDeck : decks)
        for (Card card : subDeck)
        {
            ASSERT_TRUE(seen_cards.find(card) == seen_cards.end());
            seen_cards.insert(card);
        }
}

TEST(CardCollection, Filter)
{
    Common::Game::CardCollection deck;
    deck.shuffle();
    ASSERT_EQ(deck.filter([](Card card){return card.getRank() == ACE;}).size(), Common::Constants::NUM_SUITS);
    ASSERT_EQ(deck.filter([](Card card){return card.getSuit() == HEARTS;}).size(), Common::Constants::NUM_RANKS);
    ASSERT_EQ(deck.filter([](Card card){return card.getSuit() == HEARTS and card.getRank() == ACE;}).size(), 1);
    ASSERT_EQ(deck.filter([](Card card){return card.getRank() == TWO and card.getRank() == ACE;}).size(), 0);
}

TEST(CardCollection, Contains)
{
    Common::Game::CardCollection deck;
    deck.shuffle();
    ASSERT_TRUE(deck.contains([](Card card){return card.getRank() == ACE;}));
    ASSERT_TRUE(deck.contains([](Card card){return card.getSuit() == HEARTS;}));
    ASSERT_TRUE(deck.contains([](Card card){return card.getSuit() == HEARTS and card.getRank() == ACE;}));
    ASSERT_FALSE(deck.contains([](Card card){return card.getRank() == TWO and card.getRank() == ACE;}));
}
