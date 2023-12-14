#pragma once

#include "managed_connection.h"

namespace Common::Server
{

class PlayerGameSession
{
public:
    explicit PlayerGameSession(PlayerGameSessionID game_session_id, Common::Server::ManagedConnection &connection)
    : player_id("player"), game_session_id(game_session_id), connection(connection) {}

    void RunGameSession() {
        Message::AnyMessage message;
        json j = {{Tags::TYPE, ServerMsgTypes::GAME_SESSION_RESPONSE}, {Tags::STATUS, ServerStatus::SUCCESS}};
        message.value = j;
        send(message);
    }

    void send(Message::AnyMessage &message)
    {
        message.value[Tags::SESSION_ID] = game_session_id;
        connection.sendOnSession(static_cast<Message::AnySessionMessage &>(message));
    }

    Message::AnyMessage receive(Message::AnyMessage &message)
    {
        return connection.receiveOnSession(game_session_id);
    }
private:
    Common::Server::PlayerID player_id;
    PlayerGameSessionID game_session_id;
    ManagedConnection &connection;
};

}

// TODO: to support backwards dependability without circular imports, add a 'Messenger' protocol that the dependant can call rather than the creator class