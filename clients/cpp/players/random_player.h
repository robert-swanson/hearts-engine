#pragma once

// RandomPlayer — the reference player and template for new C++ AIs.
//
// It passes three random cards and plays a random legal move. Copy this file,
// rename the class, and replace the bodies of getCardsToPass / getMove with
// your strategy; override the observation hooks in player.h to track state.
//
// Allocation-free after construction: the RNG is seeded once, and selections
// use stack arrays sized to the maximum hand (13 cards).

#include <array>
#include <cstddef>
#include <random>

#include "clients/cpp/sdk/card.h"
#include "clients/cpp/sdk/card_set.h"
#include "clients/cpp/sdk/player.h"

namespace hearts {

class RandomPlayer : public Player {
 public:
  RandomPlayer() : rng_(std::random_device{}()) {}
  explicit RandomPlayer(std::uint_fast32_t seed) : rng_(seed) {}

  void getCardsToPass(PassDirection /*direction*/, const CardSet& hand,
                      CardSet& out) override {
    // Partial Fisher–Yates: pick 3 distinct positions without allocating.
    const std::size_t n = hand.size();
    std::array<std::size_t, kMaxCards> idx{};
    for (std::size_t i = 0; i < n; ++i) idx[i] = i;
    for (std::size_t k = 0; k < 3 && k < n; ++k) {
      std::uniform_int_distribution<std::size_t> dist(k, n - 1);
      std::size_t j = dist(rng_);
      std::swap(idx[k], idx[j]);
      out.push_back(hand[idx[k]]);
    }
  }

  Card getMove(const CardSet& legalMoves) override {
    std::uniform_int_distribution<std::size_t> dist(0, legalMoves.size() - 1);
    return legalMoves[dist(rng_)];
  }

 private:
  std::mt19937 rng_;
};

}  // namespace hearts
