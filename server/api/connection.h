# pragma once

#include <mutex>
#include <cstdio>
#include <netinet/in.h>
#include <vector>
#include <algorithm>
#include <arpa/inet.h>
#include "server/util/assertions.h"
#include "server/util/logging.h"
#include "server/util/types.h"
#include "message.h"

using namespace boost::asio;

namespace Common::Server
{
enum ConnectionStatus
{
    CONNECTED,
    DISCONNECTED
};


class Connection
{
public:
    explicit Connection(const SocketPtr& clientSocket):
            mClientSocket(clientSocket), mClientIP(), mUnprocessedData()
    {
        mStatus = ConnectionStatus::CONNECTED;

        // Disable Nagle's algorithm: our messages are small and latency matters.
        clientSocket->set_option(ip::tcp::no_delay(true));

        // Get Client IP and Port
        ip::tcp::endpoint endpoint = clientSocket->remote_endpoint();
        mClientPort = endpoint.port();
        // snprintf (not strcpy) so an IPv6 peer address that exceeds the buffer
        // is truncated rather than overflowing mClientIP and smashing the stack.
        std::snprintf(mClientIP, sizeof(mClientIP), "%s",
                      endpoint.address().to_string().c_str());
    }

protected:
    void handleConnectionRequest()
    {
        auto connectionRequest = receive();

        Message::Message connectionResponse = Message::Message(ServerMsgTypes::CONNECTION_RESPONSE, {
            {Tags::STATUS, ServerStatus::SUCCESS}
        });
        send(connectionResponse);
    }

    std::string readBytes()
    {
        std::vector<char> buf(1024);
        // read_some returns the number of bytes actually read; the rest of buf
        // is uninitialized. Constructing the string from the full vector (the
        // old behavior) appended up to 1024 garbage/NUL bytes onto every read,
        // corrupting message framing. Use only the bytes we received.
        size_t n = mClientSocket->read_some(buffer(buf));
        return std::string(buf.data(), n);
    }

    Message::Message receive()
    {
        // Loop rather than recurse: a peer that dribbles bytes without ever
        // forming a complete JSON object would otherwise recurse once per read
        // and overflow the stack. Cap how much we'll buffer for a single
        // message so a peer can't make us allocate unboundedly either.
        static constexpr size_t kMaxBufferedBytes = 1u << 20;  // 1 MiB
        std::string msgStr = getFirstMessage(mUnprocessedData.empty() ? readBytes() : mUnprocessedData);
        while (true)
        {
            try
            {
                json jsonMsg = json::parse(msgStr);
                return {jsonMsg};
            }
            catch (json::parse_error &e)
            {
                if (!mUnprocessedData.empty())
                {
                    LOG("Error parsing message: %s", e.what());
                    throw e;
                }
                if (msgStr.size() > kMaxBufferedBytes)
                {
                    LOG("Discarding oversized unparseable message (%zu bytes) from %s:%d",
                        msgStr.size(), mClientIP, mClientPort);
                    throw e;
                }
                msgStr = getFirstMessage(msgStr + readBytes());
            }
        }
    }

    void send(Message::Message message)
    {
        auto jsonStr = message.getJson().dump();
        std::lock_guard<std::mutex> lock(mSendMutex);
        write(*mClientSocket, buffer(jsonStr));
    }


    void closeConnection()
    {
        mStatus = ConnectionStatus::DISCONNECTED;
        try
        {
            mClientSocket->close();
        }
        catch (std::exception &e)
        {
            LOG("Error closing connection to %s:%d: %s", mClientIP, mClientPort, e.what());
        }
    }

public:
    bool isConnected()
    {
        return mStatus == ConnectionStatus::CONNECTED;
    }

    const char* clientIP() const { return mClientIP; }
    int clientPort() const { return mClientPort; }

private:
    std::string getFirstMessage(std::string buffer)
    {
        auto splitIdx = buffer.find("}{");
        if (splitIdx == std::string::npos)
        {
            mUnprocessedData = "";
            return buffer;
        }
        splitIdx++;
        mUnprocessedData = buffer.substr(splitIdx);
        return buffer.substr(0, splitIdx);
    }

protected:
    SocketPtr mClientSocket;
    char mClientIP[INET6_ADDRSTRLEN];
    int mClientPort;
    ConnectionStatus mStatus;

private:
    mutable std::mutex mSendMutex;
    std::string mUnprocessedData;

};
}