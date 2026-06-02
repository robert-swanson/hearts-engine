#include "clients/cpp/sdk/game_runner.h"
#include "clients/cpp/sdk/player.h"
#include "clients/cpp/sdk/session.h"
#include "clients/cpp/tests/mock_channel.h"
#include "clients/cpp/players/random_player.h"

#include <string>
#include <vector>

#include <gtest/gtest.h>

using namespace hearts;

namespace {

// A player that records every hook it receives and makes deterministic
// decisions (pass the first three cards of the hand, play the first legal move)
// so a test can assert on the exact protocol traffic it produces.
class RecordingPlayer : public Player {
 public:
  void getCardsToPass(PassDirection dir, const CardSet& hand, CardSet& out) override {
    lastPassDir = dir;
    for (std::size_t i = 0; i < 3 && i < hand.size(); ++i) out.push_back(hand[i]);
  }
  Card getMove(const CardSet& legalMoves) override {
    ++getMoveCalls;
    return legalMoves[0];
  }

  void onStartGame(const PlayerList& order) override { startGamePlayers = order.size(); }
  void onStartRound(int roundIndex, PassDirection dir, const CardSet& hand) override {
    ++startRounds;
    lastRoundIndex = roundIndex;
    lastStartDir = dir;
    handSize = hand.size();
  }
  void onReceivedCards(const CardSet& received, const CardSet&) override {
    ++receivedCalls;
    receivedCount = received.size();
  }
  void onStartTrick(int trickIndex, const PlayerList&) override {
    ++startTricks;
    lastTrickIndex = trickIndex;
  }
  void onMove(std::string_view player, Card card, bool autoMoved) override {
    moves.push_back(std::string(player) + ":" + card.abbrev().str() +
                    (autoMoved ? "(auto)" : ""));
  }
  void onEndTrick(std::string_view winner) override { trickWinners.push_back(std::string(winner)); }
  void onEndRound(const ScoreList& scores) override { endRounds = scores.size(); }
  void onEndGame(const ScoreList& scores, std::string_view winner) override {
    endGameWinner = std::string(winner);
    endGameScores = scores.size();
  }

  PassDirection lastPassDir = PassDirection::Keeper;
  PassDirection lastStartDir = PassDirection::Keeper;
  int getMoveCalls = 0, startGamePlayers = 0, startRounds = 0, receivedCalls = 0;
  int startTricks = 0, lastRoundIndex = -1, lastTrickIndex = -1, endRounds = 0;
  int endGameScores = 0;
  std::size_t handSize = 0, receivedCount = 0;
  std::vector<std::string> moves, trickWinners;
  std::string endGameWinner;
};

// The 13-card hand the scripted server deals; the first three ("2C","3C","4C")
// are what RecordingPlayer will pass.
json dealHand() {
  return json::array({"2C", "3C", "4C", "5C", "6C", "7C", "8C", "9C", "TC",
                      "JC", "QC", "KC", "AC"});
}

json playerOrder() {
  return json::array({"me(0)", "p1(1)", "p2(2)", "p3(3)"});
}

}  // namespace

// Scripts a full (single-round, single-trick) game over a MockChannel and
// checks that the runner emits the right client messages and fires every hook.
TEST(GameRunner, DrivesAFullScriptedGame) {
  using namespace proto;
  MockChannel ch;
  ch.inbox.push_back({{tag::kType, server_msg::kStartGame}, {tag::kPlayerOrder, playerOrder()}});
  ch.inbox.push_back({{tag::kType, server_msg::kStartRound},
                      {tag::kRoundIndex, 0},
                      {tag::kPassDirection, "Left"},
                      {tag::kCards, dealHand()}});
  ch.inbox.push_back({{tag::kType, server_msg::kReceivedCards},
                      {tag::kCards, json::array({"2H", "3H", "4H"})},
                      {tag::kDonatedCards, json::array({"2C", "3C", "4C"})}});
  ch.inbox.push_back({{tag::kType, server_msg::kStartTrick},
                      {tag::kTrickIndex, 0},
                      {tag::kPlayerOrder, playerOrder()}});
  ch.inbox.push_back({{tag::kType, server_msg::kMoveRequest},
                      {tag::kLegalMoves, json::array({"2D", "5C"})},
                      {tag::kSentAtMs, 1000}});
  ch.inbox.push_back({{tag::kType, server_msg::kMoveReport},
                      {tag::kPlayerTag, "me(0)"}, {tag::kCard, "2D"}});
  ch.inbox.push_back({{tag::kType, server_msg::kMoveReport},
                      {tag::kPlayerTag, "p1(1)"}, {tag::kCard, "5D"},
                      {tag::kMoveSource, move_source::kServer}});
  ch.inbox.push_back({{tag::kType, server_msg::kMoveReport},
                      {tag::kPlayerTag, "p2(2)"}, {tag::kCard, "6D"}});
  ch.inbox.push_back({{tag::kType, server_msg::kMoveReport},
                      {tag::kPlayerTag, "p3(3)"}, {tag::kCard, "7D"}});
  ch.inbox.push_back({{tag::kType, server_msg::kEndTrick}, {tag::kWinningPlayer, "p3(3)"}});
  ch.inbox.push_back({{tag::kType, server_msg::kEndRound},
                      {tag::kRoundPoints, {{"me(0)", 0}, {"p1(1)", 0}, {"p2(2)", 0}, {"p3(3)", 1}}}});
  ch.inbox.push_back({{tag::kType, server_msg::kEndGame},
                      {tag::kWinningPlayer, "me(0)"},
                      {tag::kGamePoints, {{"me(0)", 3}, {"p1(1)", 9}, {"p2(2)", 7}, {"p3(3)", 7}}}});

  Session session(ch, /*sessionId=*/0, /*nextSeq=*/2);
  RecordingPlayer player;
  GameRunner(session, player).run();  // returns at end_game

  // Hooks fired in the expected shape.
  EXPECT_EQ(player.startGamePlayers, 4);
  EXPECT_EQ(player.startRounds, 1);
  EXPECT_EQ(player.lastRoundIndex, 0);
  EXPECT_EQ(player.lastStartDir, PassDirection::Left);
  EXPECT_EQ(player.handSize, 13u);
  EXPECT_EQ(player.receivedCalls, 1);
  EXPECT_EQ(player.receivedCount, 3u);
  EXPECT_EQ(player.startTricks, 1);
  EXPECT_EQ(player.getMoveCalls, 1);
  EXPECT_EQ(player.endRounds, 4);
  EXPECT_EQ(player.endGameScores, 4);
  EXPECT_EQ(player.endGameWinner, "me(0)");

  // All four moves observed; the second was a server auto-move.
  ASSERT_EQ(player.moves.size(), 4u);
  EXPECT_EQ(player.moves[0], "me(0):2D");
  EXPECT_EQ(player.moves[1], "p1(1):5D(auto)");
  ASSERT_EQ(player.trickWinners.size(), 1u);
  EXPECT_EQ(player.trickWinners[0], "p3(3)");

  // Two client messages: donated_cards then decided_move, with the shared
  // sequence counter advancing (donated=4, decided=8).
  ASSERT_EQ(ch.outbox.size(), 2u);
  const json& donated = ch.outbox[0];
  EXPECT_EQ(donated[tag::kType], client_msg::kDonatedCards);
  EXPECT_EQ(donated[tag::kSeqNum], 4u);
  ASSERT_EQ(donated[tag::kCards].size(), 3u);
  EXPECT_EQ(donated[tag::kCards][0], "2C");
  EXPECT_EQ(donated[tag::kCards][1], "3C");
  EXPECT_EQ(donated[tag::kCards][2], "4C");

  const json& decided = ch.outbox[1];
  EXPECT_EQ(decided[tag::kType], client_msg::kDecidedMove);
  EXPECT_EQ(decided[tag::kSeqNum], 8u);
  EXPECT_EQ(decided[tag::kCard], "2D");          // first legal move
  EXPECT_TRUE(decided.contains(tag::kSentAtMs));
  EXPECT_TRUE(decided.contains(tag::kPrevLatencyMs));
}

// Keeper rounds skip passing entirely: no donated_cards should be sent.
TEST(GameRunner, KeeperRoundSendsNoDonation) {
  using namespace proto;
  MockChannel ch;
  ch.inbox.push_back({{tag::kType, server_msg::kStartRound},
                      {tag::kRoundIndex, 3},
                      {tag::kPassDirection, "Keeper"},
                      {tag::kCards, dealHand()}});
  ch.inbox.push_back({{tag::kType, server_msg::kEndGame},
                      {tag::kGamePoints, {{"me(0)", 0}}}});

  Session session(ch, 0, 2);
  RecordingPlayer player;
  GameRunner(session, player).run();

  EXPECT_EQ(player.startRounds, 1);
  EXPECT_TRUE(ch.outbox.empty());  // nothing passed on a Keeper round
}

// A player that returns the wrong number of pass cards is a bug; the runner
// surfaces it as logic_error rather than sending a malformed message.
namespace {
class BadPassPlayer : public RecordingPlayer {
 public:
  void getCardsToPass(PassDirection, const CardSet& hand, CardSet& out) override {
    out.push_back(hand[0]);  // only one card — invalid
  }
};
class BadMovePlayer : public RecordingPlayer {
 public:
  Card getMove(const CardSet&) override { return Card::fromAbbrev("AS"); }  // not legal
};
}  // namespace

TEST(GameRunner, RejectsInvalidPassSelection) {
  using namespace proto;
  MockChannel ch;
  ch.inbox.push_back({{tag::kType, server_msg::kStartRound},
                      {tag::kRoundIndex, 0},
                      {tag::kPassDirection, "Left"},
                      {tag::kCards, dealHand()}});
  Session session(ch, 0, 2);
  BadPassPlayer player;
  EXPECT_THROW(GameRunner(session, player).run(), std::logic_error);
}

TEST(GameRunner, RejectsIllegalMove) {
  using namespace proto;
  MockChannel ch;
  ch.inbox.push_back({{tag::kType, server_msg::kMoveRequest},
                      {tag::kLegalMoves, json::array({"2D", "5C"})}});
  Session session(ch, 0, 2);
  BadMovePlayer player;
  EXPECT_THROW(GameRunner(session, player).run(), std::logic_error);
}

// RandomPlayer is the reference AI: over many deals it must always pass exactly
// three cards from the hand and pick a legal move.
TEST(GameRunner, RandomPlayerAlwaysProducesLegalChoices) {
  RandomPlayer player(/*seed=*/12345);
  CardSet hand;
  const char* abbrevs[] = {"2C", "3C", "4C", "5C", "6C", "7C", "8C", "9C", "TC",
                           "JC", "QC", "KC", "AC"};
  for (const char* a : abbrevs) hand.push_back(Card::fromAbbrev(a));

  for (int trial = 0; trial < 1000; ++trial) {
    CardSet out;
    player.getCardsToPass(PassDirection::Left, hand, out);
    ASSERT_EQ(out.size(), 3u);
    for (Card c : out) EXPECT_TRUE(hand.contains(c));
    // The three picks must be distinct.
    EXPECT_FALSE(out[0] == out[1]);
    EXPECT_FALSE(out[0] == out[2]);
    EXPECT_FALSE(out[1] == out[2]);

    Card move = player.getMove(hand);
    EXPECT_TRUE(hand.contains(move));
  }
}
