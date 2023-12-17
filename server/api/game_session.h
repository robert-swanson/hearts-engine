#pragma once

#include "managed_connection.h"

namespace Common::Server
{

class PlayerGameSession
{
public:
    explicit PlayerGameSession(PlayerGameSessionID game_session_id, Common::Server::ManagedConnection &connection)
    : mPlayerId(connection.getPlayerID()), mGameSessionID(game_session_id), mConnection(connection) {}

    void RunGameSession() {
        send({{
            {Tags::TYPE, ServerMsgTypes::GAME_SESSION_RESPONSE},
            {Tags::STATUS, ServerStatus::SUCCESS}
        }});
    }

    void send(Message::Message message)
    {
        Message::SessionMessage sessionMessage(message, mGameSessionID);
        mConnection.sendOnSession(sessionMessage);
    }

    Message::Message receive()
    {
        return mConnection.receiveOnSession(mGameSessionID);
    }

    [[nodiscard]] PlayerID getPlayerId() const {
        return mPlayerId;
    }

private:
    Common::Server::PlayerID mPlayerId;
    PlayerGameSessionID mGameSessionID;
    ManagedConnection &mConnection;
};

}

// TODO: to support backwards dependability without circular imports, add a 'Messenger' protocol that the dependant can call rather than the creator class