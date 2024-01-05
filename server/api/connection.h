# pragma once

#include <netinet/in.h>
#include <vector>
#include <algorithm>
#include <arpa/inet.h>
#include "../types.h"
#include "../message.h"

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

        // Get Client IP and Port
        ip::tcp::endpoint endpoint = clientSocket->remote_endpoint();
        mClientPort = endpoint.port();
        strcpy(mClientIP, endpoint.address().to_string().c_str());
    }

protected:
    void handleConnectionRequest()
    {
        auto connectionRequest = receive();

        Message::Message connectionResponse = Message::Message(ServerMsgTypes::CONNECTION_RESPONSE, {
            {Tags::STATUS, ServerStatus::SUCCESS}
        });
        send(connectionResponse);

        LOG("\nConnected to %s:%d", mClientIP, mClientPort);
    }

    std::string readBytes()
    {
        std::vector<char> buf(1024);
        size_t bytes_read = mClientSocket->read_some(buffer(buf));
        return std::string(buf.begin(), buf.end());
    }

    Message::Message receive()
    {
        auto msgStr = getFirstMessage(mUnprocessedData.empty() ? readBytes() : mUnprocessedData);
        try
        {
            json jsonMsg = json::parse(msgStr);
            return {jsonMsg};
        }
        catch (json::parse_error &e)
        {
            if (mUnprocessedData.empty())
            {
                mUnprocessedData = msgStr + readBytes();
                return receive();
            }
            else
            {
                LOG("Error parsing message: %s", e.what());
                throw e;
            }
        }
    }

    void send(Message::Message message)
    {
        auto jsonStr = message.getJson().dump();
        write(*mClientSocket, buffer(jsonStr));
    }


    void closeConnection()
    {
        LOG("Closing mConnection to %s:%d", mClientIP, mClientPort);
        mStatus = ConnectionStatus::DISCONNECTED;
        try
        {
            mClientSocket->close();
        }
        catch (std::exception &e)
        {
            LOG("Error closing mConnection to %s:%d: %s", mClientIP, mClientPort, e.what());
        }
    }

public:
    bool isConnected()
    {
        return mStatus == ConnectionStatus::CONNECTED;
    }

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
    char mClientIP[INET_ADDRSTRLEN];
    int mClientPort;
    ConnectionStatus mStatus;

private:
    std::string mUnprocessedData;

};
}