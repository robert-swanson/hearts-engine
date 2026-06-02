#include "clients/cpp/sdk/session.h"
#include "clients/cpp/sdk/transport.h"
#include "clients/cpp/tests/mock_channel.h"

#include <string>

#include <gtest/gtest.h>

using namespace hearts;

// --- takeFirstFrame: the "}{" framing split -------------------------------

TEST(Framing, ReturnsEmptyWhenNoBoundary) {
  std::string buf = R"({"type":"start_game")";  // a partial frame, no "}{"
  std::string original = buf;
  EXPECT_TRUE(takeFirstFrame(buf).empty());
  EXPECT_EQ(buf, original);  // buffer untouched so caller can read more
}

TEST(Framing, SplitsTwoConcatenatedMessages) {
  std::string buf = R"({"a":1}{"b":2})";
  EXPECT_EQ(takeFirstFrame(buf), R"({"a":1})");
  EXPECT_EQ(buf, R"({"b":2})");
  // The remainder has no further boundary, so the next call returns nothing.
  EXPECT_TRUE(takeFirstFrame(buf).empty());
  EXPECT_EQ(buf, R"({"b":2})");
}

TEST(Framing, SplitsOnlyAtFirstBoundaryOfMany) {
  std::string buf = R"({"a":1}{"b":2}{"c":3})";
  EXPECT_EQ(takeFirstFrame(buf), R"({"a":1})");
  EXPECT_EQ(takeFirstFrame(buf), R"({"b":2})");
  EXPECT_EQ(buf, R"({"c":3})");
}

// --- Session: the shared, both-directions sequence counter ----------------

TEST(Session, StampsOutboundWithIdAndSeq) {
  MockChannel ch;
  Session session(ch, /*sessionId=*/7, /*nextSeq=*/2);

  session.send({{"type", "decided_move"}});

  ASSERT_EQ(ch.outbox.size(), 1u);
  EXPECT_EQ(ch.outbox[0]["session_id"], 7);
  EXPECT_EQ(ch.outbox[0]["seq_num"], 2u);
  EXPECT_EQ(ch.outbox[0]["type"], "decided_move");
  EXPECT_EQ(session.nextSeq(), 3u);
}

TEST(Session, CounterAdvancesAcrossBothDirections) {
  MockChannel ch;
  ch.inbox.push_back({{"type", "start_game"}, {"seq_num", 2}});
  ch.inbox.push_back({{"type", "start_round"}, {"seq_num", 4}});
  Session session(ch, /*sessionId=*/0, /*nextSeq=*/2);

  json got = session.receive();          // consumes seq 2 -> next is 3
  EXPECT_EQ(got["type"], "start_game");
  EXPECT_EQ(session.nextSeq(), 3u);

  session.send({{"type", "donated_cards"}});  // stamps seq 3 -> next is 4
  EXPECT_EQ(ch.outbox[0]["seq_num"], 3u);
  EXPECT_EQ(session.nextSeq(), 4u);

  session.receive();                     // consumes seq 4 -> next is 5
  EXPECT_EQ(session.nextSeq(), 5u);
}

TEST(Session, ResyncsWhenServerSeqRunsAhead) {
  // If the server auto-moved for us and advanced its counter, receive() should
  // adopt the server's number rather than abort the session.
  MockChannel ch;
  ch.inbox.push_back({{"type", "move_report"}, {"seq_num", 42}});
  Session session(ch, /*sessionId=*/0, /*nextSeq=*/10);

  session.receive();
  EXPECT_EQ(session.nextSeq(), 43u);  // resynced to server's 42, +1
}

TEST(Session, RecvOnClosedChannelThrows) {
  MockChannel ch;  // empty inbox
  Session session(ch, 0, 0);
  EXPECT_THROW(session.receive(), ConnectionClosed);
}
