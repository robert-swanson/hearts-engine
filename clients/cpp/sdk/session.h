#pragma once

// Session: one player's seat in one game, layered over a MessageChannel.
//
// The Hearts protocol uses a SINGLE sequence counter per session that advances
// on every message in EITHER direction, because play within a session is
// strictly alternating request/response (see server/api/game_session.h). So
// `receive()` and `send()` share one counter: each bumps it by one. Every
// outbound message is stamped with the session id and the next sequence number.

#include <cstdint>

#include "protocol.h"
#include "transport.h"

namespace hearts {

class Session {
 public:
  // `nextSeq` is the sequence number the next message (in either direction) will
  // carry. For a client-initiated lobby session it is 2 after the handshake
  // (request=0, response=1); for a server-initiated tournament game it is 0.
  Session(MessageChannel& channel, std::int64_t sessionId, std::uint32_t nextSeq)
      : channel_(channel), sessionId_(sessionId), seq_(nextSeq) {}

  std::int64_t sessionId() const { return sessionId_; }

  // Receive the next message for this session, validating its sequence number.
  // If the peer's sequence ran ahead (e.g. the server auto-moved on our behalf
  // after a timeout and advanced its counter), resynchronize to it rather than
  // aborting, so the session can keep playing.
  json receive() {
    json msg = channel_.recvJson();
    std::uint32_t got = msg.value(proto::tag::kSeqNum, seq_);
    seq_ = got + 1;
    return msg;
  }

  // Stamp `msg` with this session's id and the next sequence number, then send.
  void send(json msg) {
    msg[proto::tag::kSessionId] = sessionId_;
    msg[proto::tag::kSeqNum] = seq_;
    ++seq_;
    channel_.sendJson(msg);
  }

  std::uint32_t nextSeq() const { return seq_; }

 private:
  MessageChannel& channel_;
  std::int64_t sessionId_;
  std::uint32_t seq_;
};

}  // namespace hearts
