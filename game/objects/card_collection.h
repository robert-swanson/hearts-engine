#pragma once

#include <iostream>
#include <random>
#include <algorithm>
#include <utility>
#include <vector>
#include <set>
#include <cassert>

#include "card.h"
#include "constants.h"
#include "../../util/assertions.h"

namespace Common::Game
{
class CardCollection
{
public:
    CardCollection(): mCards()
    {
    }

    CardCollection(std::vector<Common::Game::Card>::const_iterator start, std::vector<Common::Game::Card>::const_iterator end):
            mCards(start, end)
    {
        verifyUnique();
    }

    CardCollection(const CardCollection& other): CardCollection(other.mCards.begin(), other.mCards.end()) {}

    CardCollection(std::vector<Card> cards): mCards(std::move(cards)) {}

    CardCollection(Card card): mCards({card}) {}

    static CardCollection ShuffledDeck()
    {
        std::vector<Card> cards;
        for (Suit suit: Common::Constants::SUITS)
            for (Rank rank: Common::Constants::RANKS)
                cards.emplace_back(rank, suit);
        auto deck = CardCollection(cards);
        deck.shuffle();
        return deck;
    }


    [[nodiscard]] std::vector<CardCollection> divide(int divisions) const
    {
        ASRT(size() % divisions == 0, "Cannot evenly divide %lu cards into %d divisions", size(), divisions);
        size_t newSize = size() / divisions;
        std::vector<CardCollection> collections;
        auto start = mCards.begin();
        for (auto end = start + static_cast<long>(newSize); end <= mCards.end(); end += static_cast<long>(newSize))
        {
            collections.emplace_back(start, end);
            start = end;
        }
        return collections;
    }

    [[nodiscard]] CardCollection subset(int startI, int endI) const
    {
        ASRT_GE(startI, 0);
        ASRT_LE(endI, static_cast<int>(size()));
        ASRT_LE(startI, endI);
        auto itr = mCards.begin();
        return {itr+startI, itr+endI};
    }

    CardCollection filter(std::function<bool(Card)> lambdaFilter)
    {
        std::vector<Card> filtered;
        std::copy_if(mCards.begin(), mCards.end(), std::back_inserter(filtered), std::move(lambdaFilter));
        return {filtered};
    }

    bool contains(std::function<bool(Card)> lambdaFilter)
    {
        return std::any_of(mCards.begin(), mCards.end(), std::move(lambdaFilter));
    }

    bool contains(Card card)
    {
        return std::find(mCards.begin(), mCards.end(), card) != mCards.end();
    }

private:
    void shuffle()
    {
        std::random_device randomDevice;
        std::mt19937 generator(randomDevice());
        std::shuffle(mCards.begin(), mCards.end(), generator);
    }

    void verifyUnique()
    {
        std::set<Card> seen_cards;
        for (Card card : mCards)
        {
            ASRT(seen_cards.find(card) == seen_cards.end(),
                 "%s in card collection (size %lu) multiple times", card.getAbbreviation().c_str(), size());
            seen_cards.insert(card);
        }
    }

public:
    std::vector<Common::Game::Card>::iterator begin()
    {
        return mCards.begin();
    }

    std::vector<Common::Game::Card>::iterator end()
    {
        return mCards.end();
    }

    Card operator[](int index) const
    {
        return mCards[index];
    }

    CardCollection operator+(const CardCollection& other) const
    {
        std::vector<Card> cards(mCards.begin(), mCards.end());
        cards.insert(cards.end(), other.mCards.begin(), other.mCards.end());
        return {cards};
    }

    CardCollection operator+(const Card other) const
    {
        std::vector<Card> cards(mCards.begin(), mCards.end());
        cards.push_back(other);
        return {cards};
    }

    CardCollection operator-(const CardCollection& other) const
    {
        std::vector<Card> cards(mCards.begin(), mCards.end());
        for (Card cardToRemove : other.mCards)
        {
            auto itr = std::find(cards.begin(), cards.end(), cardToRemove);
            ASRT(itr != cards.end(), "Tried to remove nonexistent card %s from deck (size %lu)" ,
                 cardToRemove.getAbbreviation().c_str(), size());
            cards.erase(itr);
        }
        return {cards};
    }


    [[nodiscard]] size_t size() const
    {
        return mCards.size();
    }

    bool empty() const
    {
        return mCards.empty();
    }

    std::string getDescription()
    {
        if (mCards.empty())
        {
            return "Empty Deck";
        }
        std::string description = mCards[0].getDescription();
        std::for_each(mCards.begin() + 1, mCards.end(), [&description](Card card){
            description += ", " + card.getDescription();
        });
        return description;
    }

    std::string getAbbreviation()
    {
        if (mCards.empty())
        {
            return "";
        }
        std::string description = mCards[0].getAbbreviation();
        std::for_each(mCards.begin() + 1, mCards.end(), [&description](Card card){
            description += ", " + card.getAbbreviation();
        });
        return description;
    }

private:
    std::vector<Card> mCards;
};
}
