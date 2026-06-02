#pragma once

// MockChannel — an in-memory MessageChannel for exercising Session and
// GameRunner without a socket. `inbox` is the script the "server" sends (popped
// in order by recvJson, which throws ConnectionClosed once drained); `outbox`
// records everything the client sent so a test can assert on it.

#include <deque>
#include <vector>

#include "clients/cpp/sdk/transport.h"

namespace hearts {

class MockChannel : public MessageChannel {
 public:
  std::deque<json> inbox;    // server -> client, consumed front-to-back
  std::vector<json> outbox;  // client -> server, appended in send order

  void sendJson(const json& msg) override { outbox.push_back(msg); }

  json recvJson() override {
    if (inbox.empty()) throw ConnectionClosed();
    json front = inbox.front();
    inbox.pop_front();
    return front;
  }
};

}  // namespace hearts
