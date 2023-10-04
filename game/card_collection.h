#pragma once

#include <iostream>
#include <random>
#include <algorithm>
#include <vector>

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
                cards.emplace_back(rank, suit);
    }

    void shuffle()
    {
        std::random_device randomDevice;
        std::mt19937 generator(randomDevice());
        std::shuffle(cards.begin(), cards.end(), generator);
    }

    std::vector<Common::Game::Card>::iterator begin()
    {
        return cards.begin();
    }

    std::vector<Common::Game::Card>::iterator end()
    {
        return cards.end();
    }

    size_t size()
    {
        return cards.size();
    }

    std::string getDescription()
    {
        if (cards.empty())
        {
            return "Empty Deck";
        }
        std::string description = cards[0].getDescription();
        std::for_each(cards.begin()+1, cards.end(), [&description](Card card){
            description += ", " + card.getDescription();
        });
        return description;
    }

    std::string getAbbreviation()
    {
        if (cards.empty())
        {
            return "";
        }
        std::string description = cards[0].getAbbreviation();
        std::for_each(cards.begin()+1, cards.end(), [&description](Card card){
            description += ", " + card.getAbbreviation();
        });
        return description;
    }

private:
    std::vector<Card> cards;
};
}
