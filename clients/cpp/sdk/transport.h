#pragma once

// Transport: a bidirectional JSON message channel.
//
// The Hearts wire protocol frames messages as compact JSON objects concatenated
// with no delimiter; a boundary between two messages is the only place the
// two-byte sequence "}{" can appear (a single compact JSON value never contains
// it). Receivers therefore split on "}{" and parse, mirroring the C++ server
// (server/api/connection.h). MessageChannel abstracts this so the game loop can
// be unit-tested against an in-memory channel with no socket.

#include <stdexcept>
#include <string>

#include <nlohmann/json.hpp>

namespace hearts {

using json = nlohmann::json;

// Thrown when the peer closes the connection (clean EOF) while a message is
// still expected. Callers treat this as end-of-session.
struct ConnectionClosed : std::runtime_error {
  ConnectionClosed() : std::runtime_error("connection closed by peer") {}
};

class MessageChannel {
 public:
  virtual ~MessageChannel() = default;
  // Serialize and send one JSON object.
  virtual void sendJson(const json& msg) = 0;
  // Block until one complete JSON object arrives; throw ConnectionClosed on EOF.
  virtual json recvJson() = 0;
};

// Split helper shared by the TCP channel and exercised directly by tests.
// Given a buffer that may hold zero or more whole messages plus a partial tail,
// returns the first complete message string and rewrites `buffer` to the
// remainder. Returns empty string (and leaves `buffer` unchanged) when no "}{"
// boundary is present — the caller must then try to parse the whole buffer and,
// if that fails, read more bytes.
inline std::string takeFirstFrame(std::string& buffer) {
  auto boundary = buffer.find("}{");
  if (boundary == std::string::npos) return std::string();
  std::string first = buffer.substr(0, boundary + 1);
  buffer.erase(0, boundary + 1);
  return first;
}

}  // namespace hearts
