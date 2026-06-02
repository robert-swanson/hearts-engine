#pragma once

// Client: the high-level entry point. Owns a connection to the server, performs
// the connection handshake, and opens game sessions by lobby code. Each opened
// session can be played to completion with GameRunner.
//
//   hearts::Client client("127.0.0.1", 40406);
//   hearts::Session s = client.joinLobby("my_player", "ABCD");
//   MyPlayer p;
//   hearts::GameRunner(s, p).run();
//
// One Client drives one game at a time (sequential). That covers lobby play and
// is enough to join tournament-assigned games one after another; concurrency is
// intentionally left to the user (issue #59: keep the SDK simple, leave
// performance flexibility to the caller).

#include <memory>
#include <stdexcept>
#include <string>

#include "game_runner.h"
#include "protocol.h"
#include "session.h"
#include "tcp_channel.h"
#include "transport.h"

namespace hearts {

class Client {
 public:
  Client(const std::string& host, int port)
      : channel_(std::make_unique<TcpChannel>(host, port)) {
    handshake();
  }

  // Inject a custom channel (e.g. an in-memory channel in tests). Performs the
  // connection handshake over it.
  explicit Client(std::unique_ptr<MessageChannel> channel)
      : channel_(std::move(channel)) {
    handshake();
  }

  // Open a game session as `playerTag`, matched FIFO within `lobbyCode`
  // (sessions sharing a code play together). Blocks only for the request/
  // response round-trip; the returned Session is positioned to receive
  // start_game once the matcher fills the table.
  Session joinLobby(const std::string& playerTag,
                    const std::string& lobbyCode = proto::kDefaultLobbyCode) {
    using namespace proto;
    channel_->sendJson({{tag::kType, client_msg::kGameSessionRequest},
                        {tag::kPlayerTag, playerTag},
                        {tag::kLobbyCode, lobbyCode},
                        {tag::kGameType, "any"},
                        {tag::kSeqNum, 0}});
    json resp = channel_->recvJson();
    const std::string& type = resp.at(tag::kType).get_ref<const std::string&>();
    if (type != server_msg::kGameSessionResponse)
      throw std::runtime_error("expected game_session_response, got " + type);
    if (resp.value(tag::kStatus, std::string()) != status::kSuccess)
      throw std::runtime_error("session request rejected by server");

    std::int64_t sessionId = resp.at(tag::kSessionId).get<std::int64_t>();
    // request used seq 0, response carried seq 1, so the game stream resumes at 2.
    return Session(*channel_, sessionId, /*nextSeq=*/2);
  }

  MessageChannel& channel() { return *channel_; }

 private:
  void handshake() {
    using namespace proto;
    channel_->sendJson({{tag::kType, client_msg::kConnectionRequest}});
    json resp = channel_->recvJson();
    const std::string& type = resp.at(tag::kType).get_ref<const std::string&>();
    if (type != server_msg::kConnectionResponse)
      throw std::runtime_error("expected connection_response, got " + type);
  }

  std::unique_ptr<MessageChannel> channel_;
};

}  // namespace hearts
