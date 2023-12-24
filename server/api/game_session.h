#pragma once

#include <utility>

#include "managed_connection.h"

namespace Common::Server
{

class PlayerGameSession
{
public:
    explicit PlayerGameSession(PlayerGameSessionID game_session_id, Common::Server::ManagedConnection &connection)
    : mGameSessionID(game_session_id),  mPlayerTagSession(MakePlayerTagSession(connection.getPlayerTag(), game_session_id)), mConnection(connection) {}

    void RunGameSession() {
        send({{
            {Tags::TYPE, ServerMsgTypes::GAME_SESSION_RESPONSE},
            {Tags::STATUS, ServerStatus::SUCCESS}
        }});
    }

    // delete copy constructor and assignment operator
    PlayerGameSession(const PlayerGameSession&) = delete;
    PlayerGameSession& operator=(const PlayerGameSession&) = delete;

    void send(Message::Message message)
    {
        Message::SessionMessage sessionMessage(std::move(message), mGameSessionID, getSeqNumAndIncrement());
        mConnection.sendOnSession(sessionMessage);
    }

    Message::Message receive()
    {
        auto sessionMessage = mConnection.receiveOnSession(mGameSessionID);
        auto expectedSeqNum = getSeqNumAndIncrement();
        ASRT_EQ(sessionMessage.getSessionID(), mGameSessionID);
        ASRT(sessionMessage.getSeqNum() == expectedSeqNum, "Expected %lld.%u, but got %lld.%u", mGameSessionID, expectedSeqNum, sessionMessage.getSessionID(), sessionMessage.getSeqNum());
        return sessionMessage;
    }

    [[nodiscard]] PlayerTagSession getPlayerTagSession() const {
        return mPlayerTagSession;
    }


private:
    uint16_t getSeqNumAndIncrement()
    {
        auto oldSeqNum = mSessionSeqNum;
        auto newSeqNum = ++mSessionSeqNum;
        return oldSeqNum;
    }

    PlayerGameSessionID mGameSessionID;
    Common::Server::PlayerTagSession mPlayerTagSession;
    ManagedConnection &mConnection;
    uint16_t mSessionSeqNum = 1;
};

}

// TODO: to support backwards dependability without circular imports, add a 'Messenger' protocol that the dependant can call rather than the creator class