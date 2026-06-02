#pragma once

// Card / Rank / Suit value types for the Hearts C++ client SDK.
//
// Design goals (see issue #59): zero dynamic allocation. A Card is a trivially
// copyable 2-byte value; collections of cards live in fixed-capacity arrays
// (see card_set.h). Parsing/formatting goes through the two-character
// abbreviation used on the wire (rank char + suit char, e.g. "QS", "2C", "TH").

#include <array>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <string_view>

namespace hearts {

// Order mirrors the server (server/game/objects/card.h): low rank first.
enum class Rank : uint8_t {
  Two, Three, Four, Five, Six, Seven, Eight, Nine, Ten, Jack, Queen, King, Ace
};

// Order mirrors the server's Suit enum.
enum class Suit : uint8_t { Hearts, Diamonds, Spades, Clubs };

inline char rankToChar(Rank r) {
  switch (r) {
    case Rank::Two:   return '2';
    case Rank::Three: return '3';
    case Rank::Four:  return '4';
    case Rank::Five:  return '5';
    case Rank::Six:   return '6';
    case Rank::Seven: return '7';
    case Rank::Eight: return '8';
    case Rank::Nine:  return '9';
    case Rank::Ten:   return 'T';
    case Rank::Jack:  return 'J';
    case Rank::Queen: return 'Q';
    case Rank::King:  return 'K';
    case Rank::Ace:   return 'A';
  }
  throw std::invalid_argument("invalid rank");
}

inline Rank rankFromChar(char c) {
  switch (c) {
    case '2': return Rank::Two;
    case '3': return Rank::Three;
    case '4': return Rank::Four;
    case '5': return Rank::Five;
    case '6': return Rank::Six;
    case '7': return Rank::Seven;
    case '8': return Rank::Eight;
    case '9': return Rank::Nine;
    case 'T': return Rank::Ten;
    case 'J': return Rank::Jack;
    case 'Q': return Rank::Queen;
    case 'K': return Rank::King;
    case 'A': return Rank::Ace;
  }
  throw std::invalid_argument(std::string("invalid rank char: ") + c);
}

inline char suitToChar(Suit s) {
  switch (s) {
    case Suit::Hearts:   return 'H';
    case Suit::Diamonds: return 'D';
    case Suit::Spades:   return 'S';
    case Suit::Clubs:    return 'C';
  }
  throw std::invalid_argument("invalid suit");
}

inline Suit suitFromChar(char c) {
  switch (c) {
    case 'H': return Suit::Hearts;
    case 'D': return Suit::Diamonds;
    case 'S': return Suit::Spades;
    case 'C': return Suit::Clubs;
  }
  throw std::invalid_argument(std::string("invalid suit char: ") + c);
}

// A two-character card abbreviation as a stack value (NUL-terminated), so a Card
// can be formatted without touching the heap.
struct CardStr {
  std::array<char, 3> data{};
  const char* c_str() const { return data.data(); }
  std::string str() const { return std::string(data.data()); }
};

class Card {
 public:
  constexpr Card() : rank_(Rank::Two), suit_(Suit::Clubs) {}
  constexpr Card(Rank r, Suit s) : rank_(r), suit_(s) {}

  // Parse a two-char abbreviation ("QS", "TH", ...). Throws on malformed input.
  static Card fromAbbrev(std::string_view abbr) {
    if (abbr.size() != 2)
      throw std::invalid_argument("card abbreviation must be 2 chars");
    return Card(rankFromChar(abbr[0]), suitFromChar(abbr[1]));
  }

  Rank rank() const { return rank_; }
  Suit suit() const { return suit_; }

  CardStr abbrev() const {
    CardStr s;
    s.data[0] = rankToChar(rank_);
    s.data[1] = suitToChar(suit_);
    s.data[2] = '\0';
    return s;
  }

  // Penalty points this card is worth when taken in a trick: each heart = 1,
  // the Queen of Spades = 13, everything else = 0.
  int points() const {
    if (suit_ == Suit::Hearts) return 1;
    if (suit_ == Suit::Spades && rank_ == Rank::Queen) return 13;
    return 0;
  }

  bool operator==(const Card& o) const { return rank_ == o.rank_ && suit_ == o.suit_; }
  bool operator!=(const Card& o) const { return !(*this == o); }
  // Sort by rank, then suit — matches the server's Card::operator<.
  bool operator<(const Card& o) const {
    return rank_ < o.rank_ || (rank_ == o.rank_ && suit_ < o.suit_);
  }

 private:
  Rank rank_;
  Suit suit_;
};

}  // namespace hearts
