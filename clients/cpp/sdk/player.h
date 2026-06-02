#pragma once

// Player: the interface a Hearts AI implements, plus the small value types the
// SDK uses to hand game state to it. Everything here is allocation-free: cards
// live in fixed CardSets and player identifiers are passed as std::string_view
// into the (still-alive) parsed message, so a decision callback never touches
// the heap. A player that wants to retain an id can copy it into its own
// fixed storage.

#include <array>
#include <cstddef>
#include <stdexcept>
#include <string_view>

#include "card.h"
#include "card_set.h"

namespace hearts {

enum class PassDirection { Left, Right, Across, Keeper };

inline PassDirection passDirectionFromString(std::string_view s) {
  if (s == "Left") return PassDirection::Left;
  if (s == "Right") return PassDirection::Right;
  if (s == "Across") return PassDirection::Across;
  if (s == "Keeper") return PassDirection::Keeper;
  throw std::invalid_argument("unknown pass direction");
}

inline const char* passDirectionToString(PassDirection d) {
  switch (d) {
    case PassDirection::Left:   return "Left";
    case PassDirection::Right:  return "Right";
    case PassDirection::Across: return "Across";
    case PassDirection::Keeper: return "Keeper";
  }
  return "Unknown";
}

// A Hearts game always has four players. PlayerList is an ordered, fixed view of
// their identifiers (e.g. "random_player(2)") for the current message.
struct PlayerList {
  std::array<std::string_view, 4> ids{};
  std::size_t count = 0;

  void add(std::string_view id) {
    if (count >= ids.size()) throw std::out_of_range("PlayerList holds at most 4");
    ids[count++] = id;
  }
  std::size_t size() const { return count; }
  std::string_view operator[](std::size_t i) const { return ids[i]; }
  const std::string_view* begin() const { return ids.data(); }
  const std::string_view* end() const { return ids.data() + count; }
};

// Per-player score deltas/totals reported at end of round/game.
struct ScoreEntry {
  std::string_view player;
  int points = 0;
};
struct ScoreList {
  std::array<ScoreEntry, 4> entries{};
  std::size_t count = 0;

  void add(std::string_view player, int points) {
    if (count >= entries.size()) throw std::out_of_range("ScoreList holds at most 4");
    entries[count++] = ScoreEntry{player, points};
  }
  std::size_t size() const { return count; }
  const ScoreEntry& operator[](std::size_t i) const { return entries[i]; }
  const ScoreEntry* begin() const { return entries.data(); }
  const ScoreEntry* end() const { return entries.data() + count; }
};

// Implement this to write a Hearts AI. The two pure-virtual methods are the
// decisions; the rest are optional observation hooks (default no-ops). The SDK
// calls them on the thread running the game loop, in protocol order.
class Player {
 public:
  virtual ~Player() = default;

  // This seat's identifier for the current game, e.g. "my_player(1)". The runner
  // sets it before onStartGame; useful for spotting your own move_reports.
  void setSelfId(std::string_view id) { selfId_ = id; }
  const std::string& selfId() const { return selfId_; }

  // REQUIRED. Choose exactly three cards from `hand` to pass in `direction`,
  // appending them to `out` (which starts empty). Never called on Keeper rounds.
  virtual void getCardsToPass(PassDirection direction, const CardSet& hand, CardSet& out) = 0;

  // REQUIRED. Choose one card from `legalMoves` (always non-empty) to play.
  virtual Card getMove(const CardSet& legalMoves) = 0;

  // --- Optional observation hooks ------------------------------------------
  virtual void onStartGame(const PlayerList& /*order*/) {}
  virtual void onStartRound(int /*roundIndex*/, PassDirection /*dir*/, const CardSet& /*hand*/) {}
  virtual void onReceivedCards(const CardSet& /*received*/, const CardSet& /*donated*/) {}
  virtual void onStartTrick(int /*trickIndex*/, const PlayerList& /*order*/) {}
  virtual void onMove(std::string_view /*player*/, Card /*card*/, bool /*autoMoved*/) {}
  virtual void onEndTrick(std::string_view /*winningPlayer*/) {}
  virtual void onEndRound(const ScoreList& /*roundScores*/) {}
  virtual void onEndGame(const ScoreList& /*gameScores*/, std::string_view /*winner*/) {}

 private:
  std::string selfId_;  // set once at session start; not on the per-move hot path
};

}  // namespace hearts
