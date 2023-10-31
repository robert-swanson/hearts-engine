
#include <netinet/in.h>
#include <vector>
#include <algorithm>
#include <arpa/inet.h>
#include "types.h"
#include "messages/server/accept_connection.h"
#include "messages/client/connection_request.h"

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
        clientSocket(clientSocket), clientIP()
    {
        status = ConnectionStatus::CONNECTED;

        // Get Client IP and Port
        ip::tcp::endpoint endpoint = clientSocket->remote_endpoint();
        clientPort = endpoint.port();
        strcpy(clientIP, endpoint.address().to_string().c_str());
    }

    void start()
    {
        auto connectionRequest = receive<Message::ConnectionRequest>();
        send(Message::ConnectionResponse(ServerStatus::SUCCESS));
        LOG("\nConnected to '%s' at %s:%d", connectionRequest.getPlayerTag().c_str(), clientIP, clientPort);

        closeConnection();
    }
    
    template<typename MessageT>
    MessageT receive()
    {
        char buf[1024];
        clientSocket->read_some(buffer(buf));
        json jsonMsg = json::parse(buf);
        CONDITIONAL_LOG(LOG_ALL_RECEIVED_MESSAGES, "%s", jsonMsg.dump().c_str());

        static_assert(std::is_base_of<Message::Message, MessageT>::value, "MessageT must be a subclass of Message");
        MessageT msg;
        msg.initializeFromJson(jsonMsg);
        return msg;
    }

    template<typename MessageT>
    void send(MessageT message)
    {
        auto json = message.toJson();
        auto jsonStr = json.dump();
        CONDITIONAL_LOG(LOG_ALL_SENT_MESSAGES, "%s", jsonStr.c_str());
        write(*clientSocket, buffer(jsonStr));
    }


    void closeConnection()
    {
        LOG("Closing connection to %s:%d", clientIP, clientPort);
        clientSocket->close();
        status = ConnectionStatus::DISCONNECTED;
        ASRT_EQ(isConnected(), false);
    }

    bool isConnected()
    {
        return status == ConnectionStatus::CONNECTED;
    }

    static void CleanConnections(std::vector<std::unique_ptr<Connection>> &connections)
    {
        connections.erase(
                std::remove_if(connections.begin(), connections.end(), [](std::unique_ptr<Connection> & connection) {
                    return !connection->isConnected();
                }),
                connections.end());
    }

private:
    SocketPtr clientSocket;
    char clientIP[INET_ADDRSTRLEN];
    int clientPort;
    ConnectionStatus status;
};
}