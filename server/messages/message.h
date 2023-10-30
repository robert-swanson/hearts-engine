#pragma once

namespace Common::Server::Message
{
    class Message
    {
    public:
        Message() = default;
        Message(const Message &message) = default;
        Message(Message &&message) = default;
        Message &operator=(const Message &message) = default;
        Message &operator=(Message &&message) = default;
        virtual ~Message() = default;

        virtual void send(int clientSocket) = 0;
        virtual void receive(int clientSocket) = 0;
    };
}