#include <gtest/gtest.h>
#include "../game/objects/card_collection.h"

using namespace Common::Game;

TEST(CardCollection, DeckHas52Cards)
{
    auto deck = Common::Game::CardCollection::ShuffledDeck();
    ASSERT_EQ(deck.size(), 52);
}

TEST(CardCollection, DeckIsUnique)
{
    auto deck = Common::Game::CardCollection::ShuffledDeck();
    std::set<Card> seen_cards;
    for (Card card : deck)
    {
        ASSERT_TRUE(seen_cards.find(card) == seen_cards.end());
        seen_cards.insert(card);
    }
    ASSERT_DEATH(deck + deck, ".* in card collection \\(size .*\\) multiple times");
}

TEST(CardCollection, Divide_Sizes)
{
    auto deck = Common::Game::CardCollection::ShuffledDeck();
    auto subDecks = deck.divide(4);
    ASSERT_EQ(subDecks.size(), 4);
    for (auto subDeck : subDecks)
        ASSERT_EQ(subDeck.size(), 13);
}


TEST(CardCollection, Divide_Unique)
{
    auto deck = Common::Game::CardCollection::ShuffledDeck();
    auto subDecks = deck.divide(4);
    std::set<Card> seen_cards;
    for (auto subDeck : subDecks)
    {
        for (Card card : subDeck)
        {
            ASSERT_TRUE(seen_cards.find(card) == seen_cards.end());
            seen_cards.insert(card);
        }
    }
}

TEST(CardCollection, Subset)
{
    auto deck = Common::Game::CardCollection::ShuffledDeck();
    ASSERT_EQ(deck.subset(0, 0).size(), 0);
    ASSERT_EQ(deck.subset(0, 1).size(), 1);
    ASSERT_EQ(deck.subset(0, 2).size(), 2);
    ASSERT_EQ(deck.subset(1, 3).size(), 2);
    ASSERT_EQ(deck.subset(1, 3)[0], deck[1]);

    ASSERT_DEATH(deck.subset(-1, 1), "Assertion failed.*");
    ASSERT_DEATH(deck.subset(1, 0), "Assertion failed.*");
    ASSERT_DEATH(deck.subset(0, deck.size()+1), "Assertion failed.*");
}

TEST(CardCollection, Filter)
{
    auto deck = Common::Game::CardCollection::ShuffledDeck();
    ASSERT_EQ(deck.filter([](Card card){return card.getRank() == ACE;}).size(), Common::Constants::NUM_SUITS);
    ASSERT_EQ(deck.filter([](Card card){return card.getSuit() == HEARTS;}).size(), Common::Constants::NUM_RANKS);
    ASSERT_EQ(deck.filter([](Card card){return card.getSuit() == HEARTS and card.getRank() == ACE;}).size(), 1);
    ASSERT_EQ(deck.filter([](Card card){return card.getRank() == TWO and card.getRank() == ACE;}).size(), 0);
}

TEST(CardCollection, ContainsFilter)
{
    auto deck = Common::Game::CardCollection::ShuffledDeck();
    ASSERT_TRUE(deck.contains([](Card card){return card.getRank() == ACE;}));
    ASSERT_TRUE(deck.contains([](Card card){return card.getSuit() == HEARTS;}));
    ASSERT_TRUE(deck.contains([](Card card){return card.getSuit() == HEARTS and card.getRank() == ACE;}));
    ASSERT_FALSE(deck.contains([](Card card){return card.getRank() == TWO and card.getRank() == ACE;}));
}

TEST(CardCollection, ContainsCard)
{
    auto deck = Common::Game::CardCollection::ShuffledDeck();
    ASSERT_TRUE(deck.contains(Card(ACE, SPADES)));
    auto subDecks = deck.divide(2);
    ASSERT_NE(subDecks[0].contains(Card(ACE, SPADES)), subDecks[1].contains(Card(ACE, SPADES)));
}
