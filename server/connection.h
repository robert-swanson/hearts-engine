
#include <netinet/in.h>
#include <vector>
#include <algorithm>
#include <arpa/inet.h>
#include <boost/asio.hpp>
#include <nlohmann/json.hpp>

using namespace boost::asio;

namespace Common::Server
{
enum ConnectionStatus
{
    CONNECTED,
    DISCONNECTED
};

using SocketPtr = std::shared_ptr<ip::tcp::socket>;
using json = nlohmann::json;

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
        LOG("Connected to %s:%d", clientIP, clientPort);
        json acceptMessage;
        acceptMessage["type"] = "accept";
        std::string responseStr = acceptMessage.dump() + "\n";
        write(*clientSocket, buffer(responseStr));
        closeConnection();
    }


    void closeConnection()
    {
        LOG("Closing connection to %s:%d", clientIP, clientPort);
        clientSocket->close();
        status = ConnectionStatus::DISCONNECTED;
    }

    bool isConnected()
    {
        return status == ConnectionStatus::CONNECTED;
    }

    static void CleanConnections(std::vector<Connection> &connections)
    {
        connections.erase(
                std::remove_if(connections.begin(), connections.end(), [](Connection connection) {
                    return !connection.isConnected();
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