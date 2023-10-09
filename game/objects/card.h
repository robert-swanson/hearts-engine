#pragma once

#include <iostream>

namespace Common::Game
{

enum Rank
{
    TWO, THREE, FOUR, FIVE, SIX, SEVEN, EIGHT, NINE, TEN, JACK, QUEEN, KING, ACE
};

std::string RankToDescription(const Rank rank)
{
    switch (rank)
    {
        case TWO:
            return "2";
        case THREE:
            return "3";
        case FOUR:
            return "4";
        case FIVE:
            return "5";
        case SIX:
            return "6";
        case SEVEN:
            return "7";
        case EIGHT:
            return "8";
        case NINE:
            return "9";
        case TEN:
            return "10";
        case JACK:
            return "Jack";
        case QUEEN:
            return "Queen";
        case KING:
            return "King";
        case ACE:
            return "Ace";
        default:
            throw std::invalid_argument("Unexpected rank");
    }
}

std::string RankToAbbreviation(const Rank rank)
{
    switch (rank)
    {
        case TWO:
            return "2";
        case THREE:
            return "3";
        case FOUR:
            return "4";
        case FIVE:
            return "5";
        case SIX:
            return "6";
        case SEVEN:
            return "7";
        case EIGHT:
            return "8";
        case NINE:
            return "9";
        case TEN:
            return "T";
        case JACK:
            return "J";
        case QUEEN:
            return "Q";
        case KING:
            return "K";
        case ACE:
            return "A";
        default:
            throw std::invalid_argument("Unexpected rank");
    }
}

enum Suit
{
    HEARTS, DIAMONDS, SPADES, CLUBS
};

std::string SuitToDescription(const Suit suit)
{
    switch (suit)
    {
        case HEARTS:
            return "Hearts";
        case DIAMONDS:
            return "Diamonds";
        case SPADES:
            return "Spades";
        case CLUBS:
            return "Clubs";
        default:
            throw std::invalid_argument("Invalid Suit");
    }
}

std::string SuitToAbbreviation(const Suit suit)
{
    switch (suit)
    {
        case HEARTS:
            return "H";
        case DIAMONDS:
            return "D";
        case SPADES:
            return "S";
        case CLUBS:
            return "C";
        default:
            throw std::invalid_argument("Invalid Suit");
    }
}

class Card
{
public:
    Card(const Rank rank, const Suit suit) : rank(rank), suit(suit) {}

    std::string getDescription()
    {
        return RankToDescription(rank) + " of " + SuitToDescription(suit);
    }

    std::string getAbbreviation()
    {
        return RankToAbbreviation(rank) + SuitToAbbreviation(suit);
    }

    bool operator<(const Card& other) const
    {
        return rank < other.rank or (rank == other.rank and suit < other.suit);
    }

    bool operator==(const Card& other) const
    {
        return rank == other.rank and suit == other.suit;
    }

    bool operator!=(const Card& other) const
    {
        return not (*this == other);
    }

    Rank getRank() const {
        return rank;
    }

    Suit getSuit() const {
        return suit;
    }

private:
    Rank rank;
    Suit suit;
};
}
