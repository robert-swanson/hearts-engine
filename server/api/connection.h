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

    Message::Message receive()
    {
        std::string buffStr;
        if (!mUnprocessedData.empty())
        {
            buffStr = mUnprocessedData;
        }
        else
        {
            char buf[1024];
            size_t bytes_read = mClientSocket->read_some(buffer(buf));
            buf[bytes_read] = '\0';
            buffStr = buf;
        }
        auto msgStr = getFirstMessage(buffStr);
        json jsonMsg = json::parse(msgStr);
//        CONDITIONAL_LOG(LOG_ALL_RECEIVED_MESSAGES, "<<< %s", jsonMsg.dump().c_str());
        return {jsonMsg};
    }

    void send(Message::Message message)
    {
        auto jsonStr = message.getJson().dump();
//        CONDITIONAL_LOG(LOG_ALL_SENT_MESSAGES, ">>> %s", jsonStr.c_str());
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
        mUnprocessedData = buffer.substr(splitIdx + 1);
        return buffer.substr(0, splitIdx + 1);
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