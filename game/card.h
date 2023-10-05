#pragma once

#include <iostream>

namespace Common::Game
{

enum Rank
{
    ACE, KING, QUEEN, JACK, TEN, NINE, EIGHT, SEVEN, SIX, FIVE, FOUR, THREE, TWO
};

std::string RankToDescription(const Rank rank)
{
    switch (rank)
    {
        case ACE:
            return "Ace";
        case KING:
            return "King";
        case QUEEN:
            return "Queen";
        case JACK:
            return "Jack";
        case TEN:
            return "10";
        case NINE:
            return "9";
        case EIGHT:
            return "8";
        case SEVEN:
            return "7";
        case SIX:
            return "6";
        case FIVE:
            return "5";
        case FOUR:
            return "4";
        case THREE:
            return "3";
        case TWO:
            return "2";
        default:
            throw std::invalid_argument("Unexpected rank");
    }
}

std::string RankToAbbreviation(const Rank rank)
{
    switch (rank)
    {
        case ACE:
            return "A";
        case KING:
            return "K";
        case QUEEN:
            return "Q";
        case JACK:
            return "J";
        case TEN:
            return "10";
        case NINE:
            return "9";
        case EIGHT:
            return "8";
        case SEVEN:
            return "7";
        case SIX:
            return "6";
        case FIVE:
            return "5";
        case FOUR:
            return "4";
        case THREE:
            return "3";
        case TWO:
            return "2";
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
