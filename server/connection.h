
#include <netinet/in.h>
#include <vector>
#include <arpa/inet.h>

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
    Connection(int clientSocket, struct sockaddr_in clientAddress):
        clientSocket(clientSocket), clientIP()
    {
        status = ConnectionStatus::CONNECTED;

        // Get Client IP and Port
        socklen_t clientAddressLength = sizeof(clientAddress);
        int code = getpeername(clientSocket, (struct sockaddr *) &clientAddress, &clientAddressLength);
        ASRT_EQ(code, SUCCESS_CODE);
        inet_ntop(AF_INET, &(clientAddress.sin_addr), clientIP, INET_ADDRSTRLEN);
        clientPort = ntohs(clientAddress.sin_port);
    }

    void start()
    {
        LOG("Connected to %s:%d", clientIP, clientPort);
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
    int clientSocket;
    char clientIP[INET_ADDRSTRLEN];
    int clientPort;
    ConnectionStatus status;
};
}