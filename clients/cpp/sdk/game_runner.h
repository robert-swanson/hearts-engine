#pragma once

// GameRunner: drives one Session through a full game, translating protocol
// messages into Player callbacks and the player's decisions back into messages.
//
// The whole game is a single sequential loop: receive a message, dispatch by
// type. The only client-originated messages are `donated_cards` (sent
// proactively after a non-Keeper start_round) and `decided_move` (sent in reply
// to move_request). Because the session's sequence counter advances on every
// message in both directions, this strict ordering keeps client and server in
// lockstep with no extra bookkeeping.

#include <chrono>
#include <stdexcept>
#include <string>

#include "card.h"
#include "card_set.h"
#include "player.h"
#include "protocol.h"
#include "session.h"
#include "transport.h"

namespace hearts {

namespace detail {

inline long nowMs() {
  return static_cast<long>(std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count());
}

inline void parseCards(const json& arr, CardSet& out) {
  out.clear();
  for (const auto& c : arr)
    out.push_back(Card::fromAbbrev(c.template get_ref<const std::string&>()));
}

inline PlayerList parsePlayerList(const json& arr) {
  PlayerList list;
  for (const auto& p : arr) list.add(p.template get_ref<const std::string&>());
  return list;
}

inline ScoreList parseScoreList(const json& obj) {
  ScoreList list;
  for (auto it = obj.begin(); it != obj.end(); ++it)
    list.add(it.key(), it.value().get<int>());
  return list;
}

inline json cardsToJson(const CardSet& cards) {
  json arr = json::array();
  for (Card c : cards) arr.push_back(c.abbrev().str());
  return arr;
}

}  // namespace detail

class GameRunner {
 public:
  GameRunner(Session& session, Player& player) : session_(session), player_(player) {}

  // Play one game to completion. Returns normally after end_game; propagates
  // ConnectionClosed if the peer hangs up, and std::logic_error if the player
  // returns an invalid pass/move (a bug in the player, surfaced early).
  void run() {
    using namespace proto;
    while (true) {
      json msg = session_.receive();
      auto typeIt = msg.find(tag::kType);
      if (typeIt == msg.end()) continue;  // ignore frames without a type
      const std::string& type = typeIt->get_ref<const std::string&>();

      if (type == server_msg::kStartGame) {
        PlayerList order = detail::parsePlayerList(msg.at(tag::kPlayerOrder));
        player_.onStartGame(order);
      } else if (type == server_msg::kStartRound) {
        handleStartRound(msg);
      } else if (type == server_msg::kReceivedCards) {
        CardSet received, donated;
        detail::parseCards(msg.at(tag::kCards), received);
        if (msg.contains(tag::kDonatedCards))
          detail::parseCards(msg.at(tag::kDonatedCards), donated);
        player_.onReceivedCards(received, donated);
      } else if (type == server_msg::kStartTrick) {
        PlayerList order = detail::parsePlayerList(msg.at(tag::kPlayerOrder));
        player_.onStartTrick(msg.value(tag::kTrickIndex, 0), order);
      } else if (type == server_msg::kMoveRequest) {
        handleMoveRequest(msg);
      } else if (type == server_msg::kMoveReport) {
        bool autoMoved = msg.value(tag::kMoveSource, std::string(move_source::kPlayer)) ==
                         move_source::kServer;
        player_.onMove(msg.at(tag::kPlayerTag).get_ref<const std::string&>(),
                       Card::fromAbbrev(msg.at(tag::kCard).get_ref<const std::string&>()),
                       autoMoved);
      } else if (type == server_msg::kEndTrick) {
        player_.onEndTrick(msg.at(tag::kWinningPlayer).get_ref<const std::string&>());
      } else if (type == server_msg::kEndRound) {
        player_.onEndRound(detail::parseScoreList(msg.at(tag::kRoundPoints)));
      } else if (type == server_msg::kEndGame) {
        ScoreList scores = detail::parseScoreList(msg.at(tag::kGamePoints));
        std::string_view winner =
            msg.contains(tag::kWinningPlayer)
                ? std::string_view(msg.at(tag::kWinningPlayer).get_ref<const std::string&>())
                : std::string_view();
        player_.onEndGame(scores, winner);
        return;
      }
      // Unknown message types are ignored so a protocol addition can't wedge us.
    }
  }

 private:
  void handleStartRound(const json& msg) {
    using namespace proto;
    PassDirection dir = passDirectionFromString(
        msg.at(tag::kPassDirection).get_ref<const std::string&>());
    CardSet hand;
    detail::parseCards(msg.at(tag::kCards), hand);
    player_.onStartRound(msg.value(tag::kRoundIndex, 0), dir, hand);

    if (dir == PassDirection::Keeper) return;  // no passing on Keeper rounds

    CardSet toPass;
    player_.getCardsToPass(dir, hand, toPass);
    if (toPass.size() != 3)
      throw std::logic_error("getCardsToPass must select exactly 3 cards");
    for (Card c : toPass)
      if (!hand.contains(c))
        throw std::logic_error("getCardsToPass returned a card not in hand");

    session_.send({{tag::kType, client_msg::kDonatedCards},
                   {tag::kCards, detail::cardsToJson(toPass)}});
  }

  void handleMoveRequest(const json& msg) {
    using namespace proto;
    CardSet legal;
    detail::parseCards(msg.at(tag::kLegalMoves), legal);
    if (legal.empty()) throw std::logic_error("move_request had no legal moves");

    Card chosen = player_.getMove(legal);
    if (!legal.contains(chosen))
      throw std::logic_error("getMove returned a card that is not a legal move");

    long now = detail::nowMs();
    long s2cLatency = -1;
    if (msg.contains(tag::kSentAtMs))
      s2cLatency = now - msg.at(tag::kSentAtMs).get<long>();

    session_.send({{tag::kType, client_msg::kDecidedMove},
                   {tag::kCard, chosen.abbrev().str()},
                   {tag::kSentAtMs, now},
                   {tag::kPrevLatencyMs, s2cLatency}});
  }

  Session& session_;
  Player& player_;
};

}  // namespace hearts
