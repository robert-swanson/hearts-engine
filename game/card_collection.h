#pragma once

#include <iostream>
#include <random>
#include <algorithm>
#include <vector>
#include <cassert>

#include "card.h"
#include "constants.h"

namespace Common::Game
{
class CardCollection
{
public:
    CardCollection()
    {
        for (Suit suit: Common::Constants::SUITS)
            for (Rank rank: Common::Constants::RANKS)
                mCards.emplace_back(rank, suit);
    }

    CardCollection(std::vector<Common::Game::Card>::iterator start, std::vector<Common::Game::Card>::iterator end):
            mCards(start, end)
    {
    }

    void shuffle()
    {
        std::random_device randomDevice;
        std::mt19937 generator(randomDevice());
        std::shuffle(mCards.begin(), mCards.end(), generator);
    }

    std::vector<CardCollection> divide(int divisions)
    {
        assert(size() % divisions == 0 && "cannot evenly divide card collection");
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

    std::vector<Common::Game::Card>::iterator begin()
    {
        return mCards.begin();
    }

    std::vector<Common::Game::Card>::iterator end()
    {
        return mCards.end();
    }

    size_t size()
    {
        return mCards.size();
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
