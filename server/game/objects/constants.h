#pragma once

#include <array>
#include "card.h"

namespace Common::Constants
{


constexpr size_t NUM_RANKS = 13;
constexpr std::array<Common::Game::Rank, NUM_RANKS> RANKS =
{
    Common::Game::Rank::TWO,
    Common::Game::Rank::THREE,
    Common::Game::Rank::FOUR,
    Common::Game::Rank::FIVE,
    Common::Game::Rank::SIX,
    Common::Game::Rank::SEVEN,
    Common::Game::Rank::EIGHT,
    Common::Game::Rank::NINE,
    Common::Game::Rank::TEN,
    Common::Game::Rank::JACK,
    Common::Game::Rank::QUEEN,
    Common::Game::Rank::KING,
    Common::Game::Rank::ACE
};
static_assert(sizeof(RANKS) / sizeof(RANKS[0]) == NUM_RANKS);

constexpr size_t NUM_SUITS = 4;
constexpr std::array<Common::Game::Suit, NUM_SUITS> SUITS =
{
    Common::Game::Suit::HEARTS,
    Common::Game::Suit::DIAMONDS,
    Common::Game::Suit::SPADES,
    Common::Game::Suit::CLUBS
};
static_assert(sizeof(SUITS) / sizeof(SUITS[0]) == NUM_SUITS);

constexpr size_t DECK_SIZE = 52;
static_assert(DECK_SIZE == NUM_RANKS*NUM_SUITS);

constexpr size_t NUM_PLAYERS = 4;
constexpr size_t NUM_CARDS_TO_PASS = 3;
constexpr size_t NUM_TRICKS = 13;
static_assert(NUM_TRICKS == DECK_SIZE / NUM_PLAYERS);

constexpr size_t GAME_END_SCORE = 100;
constexpr size_t QUEEN_SCORE = 13;
constexpr size_t MAX_TRICK_SCORE = 26;
static_assert(MAX_TRICK_SCORE == QUEEN_SCORE + NUM_RANKS);

const auto STARTING_CARD = Common::Game::Card(Game::TWO, Game::CLUBS);
}