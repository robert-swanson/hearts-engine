#pragma once

// TcpChannel: a MessageChannel over a blocking POSIX TCP socket.
//
// Uses raw BSD sockets (no Boost) to keep the client dependency-light and
// portable across Linux and macOS. TCP_NODELAY is set because Hearts messages
// are small and latency-sensitive. All heap use is confined to the receive
// buffer and JSON (de)serialization at this transport boundary; the game-state
// and player-facing types never allocate.

#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cerrno>
#include <cstring>
#include <stdexcept>
#include <string>

#include "protocol.h"
#include "transport.h"

namespace hearts {

class TcpChannel : public MessageChannel {
 public:
  // Connect to host:port. Throws std::runtime_error on failure.
  TcpChannel(const std::string& host, int port) {
    addrinfo hints{};
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    addrinfo* res = nullptr;
    std::string portStr = std::to_string(port);
    int rc = ::getaddrinfo(host.c_str(), portStr.c_str(), &hints, &res);
    if (rc != 0)
      throw std::runtime_error("getaddrinfo(" + host + "): " + gai_strerror(rc));

    int fd = -1;
    for (addrinfo* p = res; p != nullptr; p = p->ai_next) {
      fd = ::socket(p->ai_family, p->ai_socktype, p->ai_protocol);
      if (fd < 0) continue;
      if (::connect(fd, p->ai_addr, p->ai_addrlen) == 0) break;
      ::close(fd);
      fd = -1;
    }
    ::freeaddrinfo(res);
    if (fd < 0)
      throw std::runtime_error("could not connect to " + host + ":" + portStr +
                               " (is the server running?)");

    int one = 1;
    ::setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
    fd_ = fd;
  }

  // Adopt an already-connected socket fd (useful for tests / custom setups).
  explicit TcpChannel(int fd) : fd_(fd) {}

  ~TcpChannel() override {
    if (fd_ >= 0) ::close(fd_);
  }

  TcpChannel(const TcpChannel&) = delete;
  TcpChannel& operator=(const TcpChannel&) = delete;

  void sendJson(const json& msg) override {
    std::string payload = msg.dump();
    const char* data = payload.data();
    std::size_t remaining = payload.size();
    while (remaining > 0) {
      ssize_t n = ::send(fd_, data, remaining, 0);
      if (n < 0) {
        if (errno == EINTR) continue;
        throw std::runtime_error(std::string("send failed: ") + std::strerror(errno));
      }
      data += n;
      remaining -= static_cast<std::size_t>(n);
    }
  }

  json recvJson() override {
    while (true) {
      // First, try to satisfy the request from already-buffered bytes.
      std::string frame = takeFirstFrame(buffer_);
      if (!frame.empty()) {
        // A "}{" boundary guarantees a complete object before it.
        return json::parse(frame);
      }
      // No boundary: the whole buffer might already be one complete object.
      if (!buffer_.empty()) {
        try {
          json parsed = json::parse(buffer_);
          buffer_.clear();
          return parsed;
        } catch (const json::parse_error&) {
          // Incomplete — fall through and read more bytes.
        }
      }
      readMore();
    }
  }

 private:
  void readMore() {
    char chunk[2048];
    ssize_t n = ::recv(fd_, chunk, sizeof(chunk), 0);
    if (n == 0) throw ConnectionClosed();
    if (n < 0) {
      if (errno == EINTR) return;  // retry on next loop iteration
      throw std::runtime_error(std::string("recv failed: ") + std::strerror(errno));
    }
    buffer_.append(chunk, static_cast<std::size_t>(n));
  }

  int fd_ = -1;
  std::string buffer_;
};

}  // namespace hearts
