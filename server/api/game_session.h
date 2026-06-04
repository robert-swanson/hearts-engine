#pragma once

#include <atomic>
#include <utility>

#include "managed_connection.h"

namespace Common::Server
{

class PlayerGameSession
{
public:
    explicit PlayerGameSession(PlayerGameSessionID game_session_id, const PlayerTag& playerTag,
                               Common::Server::ManagedConnection &connection,
                               uint16_t starting_seq = 1,
                               std::chrono::milliseconds moveTimeout = std::chrono::seconds(15))
    : mPlayerTag(playerTag), mGameSessionID(game_session_id),
      mPlayerTagSession(MakePlayerTagSession(playerTag, game_session_id)),
      mConnection(connection), mSessionSeqNum(starting_seq), mMoveTimeout(moveTimeout) {}

    void Setup() {
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
        mConnection.sendOnSession(sessionMessage, mGameSessionID);
    }

    // Returns nullopt on timeout, disconnect, or bad sequence number.
    // Always advances the sequence counter to stay in sync with the client.
    std::optional<Message::Message> receive()
    {
        while (true)
        {
            auto raw = mConnection.receiveOnSession(mGameSessionID, mMoveTimeout);
            if (!raw)
            {
                // Timeout or disconnect: consume the slot the client would have used
                // so both counters remain aligned going forward.
                mSessionSeqNum.fetch_add(1, std::memory_order_relaxed);
                return std::nullopt;
            }

            ASRT_EQ(raw->getSessionID(), mGameSessionID);

            if (raw->getSeqNum() < mSessionSeqNum.load())
            {
                // Stale late-arrival (e.g. a decided_move that arrived after a timeout).
                // Drop it without advancing the counter, then wait for the right message.
                LOG("Discarding stale message %lld.%u (expected .%u)",
                    mGameSessionID, raw->getSeqNum(), mSessionSeqNum.load());
                continue;
            }

            if (raw->getSeqNum() != mSessionSeqNum.load())
            {
                LOG("Unexpected seq %u on session %lld (expected %u) — treating as timeout",
                    raw->getSeqNum(), mGameSessionID, mSessionSeqNum.load());
                mSessionSeqNum.fetch_add(1, std::memory_order_relaxed);
                return std::nullopt;
            }

            mSessionSeqNum.fetch_add(1, std::memory_order_relaxed);
            return *raw;
        }
    }

    void setMessageLogger(const std::shared_ptr<Common::MessageLogger>& messageLogger)
    {
        mConnection.setMessageLogger(mGameSessionID, messageLogger);
    }

    [[nodiscard]] PlayerTagSession getPlayerTagSession() const {
        return mPlayerTagSession;
    }

    [[nodiscard]] PlayerGameSessionID getGameSessionID() const {
        return mGameSessionID;
    }

    // True if the last receive() returned nullopt because the connection gave up
    // immediately (give-up mode) rather than waiting the full move timeout. Used
    // by RemotePlayer to mark an auto-move as give-up ("#") vs. timeout ("*").
    bool lastReceiveWasGiveUp() {
        return mConnection.sessionLastReceiveWasGiveUp(mGameSessionID);
    }


private:
    uint16_t getSeqNumAndIncrement()
    {
        return mSessionSeqNum.fetch_add(1, std::memory_order_relaxed);
    }

    PlayerTag mPlayerTag;
    PlayerGameSessionID mGameSessionID;
    Common::Server::PlayerTagSession mPlayerTagSession;
    ManagedConnection &mConnection;
    std::atomic<uint16_t> mSessionSeqNum;
    std::chrono::milliseconds mMoveTimeout;
};

using SessionRef = std::shared_ptr<PlayerGameSession>;
}

// TODO: to support backwards dependability without circular imports, add a 'Messenger' protocol that the dependant can call rather than the creator class