#pragma once

// CardSet — a fixed-capacity, allocation-free ordered collection of Cards.
//
// Backed by std::array, so a hand (13 cards), a set of legal moves (≤13), or a
// passed-cards triple (3) all live on the stack/in-place with no heap use. The
// API is deliberately small: the SDK fills these and hands them to the player;
// the player reads them and may copy into its own fixed storage.

#include <array>
#include <cstddef>
#include <stdexcept>

#include "card.h"

namespace hearts {

// A full deck has 52 cards; that is the largest a CardSet ever needs to hold.
inline constexpr std::size_t kMaxCards = 52;

template <std::size_t Capacity = kMaxCards>
class BasicCardSet {
 public:
  BasicCardSet() = default;

  std::size_t size() const { return size_; }
  bool empty() const { return size_ == 0; }
  static constexpr std::size_t capacity() { return Capacity; }

  void clear() { size_ = 0; }

  void push_back(Card c) {
    if (size_ >= Capacity) throw std::out_of_range("CardSet capacity exceeded");
    cards_[size_++] = c;
  }

  Card operator[](std::size_t i) const { return cards_[i]; }

  const Card* begin() const { return cards_.data(); }
  const Card* end() const { return cards_.data() + size_; }

  bool contains(Card c) const {
    for (std::size_t i = 0; i < size_; ++i)
      if (cards_[i] == c) return true;
    return false;
  }

  // Remove the first occurrence of c (order-preserving). Returns true if found.
  bool remove(Card c) {
    for (std::size_t i = 0; i < size_; ++i) {
      if (cards_[i] == c) {
        for (std::size_t j = i + 1; j < size_; ++j) cards_[j - 1] = cards_[j];
        --size_;
        return true;
      }
    }
    return false;
  }

 private:
  std::array<Card, Capacity> cards_{};
  std::size_t size_ = 0;
};

using CardSet = BasicCardSet<kMaxCards>;

}  // namespace hearts
