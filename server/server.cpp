#include <iostream>
#include <sys/socket.h>
#include <netinet/in.h>
#include "constants.h"
#include "../util/assertions.h"
#include "../util/logging.h"
#include "connection.h"
#include <future>

using namespace Common::Server;

int main()
{
    int serverSocket = socket(AF_INET, SOCK_STREAM, 0);

    struct sockaddr_in serverAddress{};
    serverAddress.sin_family = AF_INET;
    serverAddress.sin_port = htons(SERVER_PORT);
    serverAddress.sin_addr.s_addr = INADDR_ANY;

    int code = bind(serverSocket, (struct sockaddr *) &serverAddress, sizeof(serverAddress));
    ASRT_EQ(code, SUCCESS_CODE);

    code = listen(serverSocket, MAX_CONNECTION_BACKLOG);
    ASRT_EQ(code, SUCCESS_CODE);

    LOG("Server listening on address %d, port %d...", serverAddress.sin_addr.s_addr, serverAddress.sin_port);
    std::vector<Connection> connections;
    while (true)
    {
        struct sockaddr_in clientAddress{};
        socklen_t clientAddressLength = sizeof(clientAddress);
        int clientSocket = accept(serverSocket, (struct sockaddr *) &clientAddress, &clientAddressLength);

        Connection connection = connections.emplace_back(clientSocket, clientAddress);
        connection.start();

        Connection::CleanConnections(connections);
    }


}








