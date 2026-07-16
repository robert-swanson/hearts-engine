#pragma once

#include <chrono>

#include "server/api/game_session.h"
#include "server/game/remote_player.h"
#include "server/util/dates.h"
#include "server/util/env.h"
#include "server/util/validation.h"
#include "lobby.h"

namespace Common::Server
{

class Matcher
{
private:
    static Matcher instance;

    // Start at 1 so session id 0 is never handed out: 0 is the reserved
    // "no session created" sentinel that ConnectionListener uses to skip
    // registering control messages (e.g. tournament heartbeats / auth rejects).
    Matcher(): sessionCounter(1)
    {
//        sessionCounter = std::chrono::duration_cast<std::chrono::milliseconds>(
//                std::chrono::system_clock::now().time_since_epoch()).count();
    }

public:
    static Matcher& GetInstance()
    {
        return Matcher::instance;
    }

    // Sessions one client may open on a single connection. Batch testing
    // legitimately multiplexes 64+ sessions; this only stops a client from
    // opening sessions (and eventually games/threads) without bound.
    static constexpr size_t MAX_SESSIONS_PER_CONNECTION = 512;

    // Distinct lobby codes the server will track at once. Lobbies are never
    // reclaimed, so without a cap a client spamming random codes grows the map
    // (and strands a session in each) indefinitely.
    static constexpr size_t MAX_LOBBIES = 4096;

    static PlayerGameSessionID HandleSessionRequest(ManagedConnection &connection, Message::Message message)
    {
        if (!message.hasTag(Tags::PLAYER_TAG))
            return rejectSessionRequest(connection, "missing player_tag");
        auto playerTag = message.getTag<PlayerTag>(Tags::PLAYER_TAG);
        if (!Validation::IsValidPlayerTag(playerTag))
            return rejectSessionRequest(connection, "invalid player_tag");

        LobbyCode lobbyCode = DEFAULT_LOBBY_CODE;
        if (message.hasTag(Tags::LOBBY_CODE))
        {
            lobbyCode = message.getTag<std::string>(Tags::LOBBY_CODE);
            lobbyCode = lobbyCode.empty() ? DEFAULT_LOBBY_CODE : lobbyCode;
            if (!Validation::IsValidLobbyCode(lobbyCode))
                return rejectSessionRequest(connection, "invalid lobby_code");
        }

        if (connection.sessionCount() >= MAX_SESSIONS_PER_CONNECTION)
            return rejectSessionRequest(connection, "too many sessions on this connection");

        Matcher & matcher = GetInstance();
        if (!matcher.lobbyAvailable(lobbyCode))
            return rejectSessionRequest(connection, "too many active lobbies");

        auto session = matcher.createPlayerGameSession(connection, playerTag);
        matcher.addPlayer(session, lobbyCode);
        return session->getGameSessionID();
    }


    SessionRef createPlayerGameSession(ManagedConnection &connection, const PlayerTag& playerTag)
    {
        auto sessionID = sessionCounter.fetch_add(1, std::memory_order_relaxed);
        // Allow the regular server's per-move wait to be tuned via config so that
        // interactive (human) lobby players get enough time to think. Mirrors the
        // tournament server's MOVE_TIMEOUT_MS handling; defaults to 15s otherwise.
        std::chrono::milliseconds moveTimeout = std::chrono::seconds(15);
        if (EnvLoader && EnvLoader->has("MOVE_TIMEOUT_MS"))
        {
            moveTimeout = std::chrono::milliseconds(std::stoi(ENV_STRING("MOVE_TIMEOUT_MS")));
        }
        auto session = std::make_shared<PlayerGameSession>(sessionID, playerTag, connection,
                                                           /*starting_seq=*/1, moveTimeout);
        session->Setup();
        return session;
    }

    void addPlayer(const SessionRef& playerSession, const LobbyCode& lobbyCode)
    {
        // Session requests arrive concurrently from per-connection threads, so
        // the lobby map itself needs a lock. Match players outside of it: a
        // matched game does its (potentially slow) setup in Lobby::addPlayer,
        // which must not block session requests for other lobbies.
        Lobby* lobby;
        {
            std::lock_guard<std::mutex> lock(mLobbiesMtx);
            auto it = mLobbies.find(lobbyCode);
            if (it == mLobbies.end())
                it = mLobbies.emplace(std::piecewise_construct,
                                      std::forward_as_tuple(lobbyCode),
                                      std::forward_as_tuple(lobbyCode)).first;
            lobby = &it->second;
        }
        lobby->addPlayer(playerSession);
    }

    // Whether a session request for this lobby code can be accepted without
    // growing the lobby map past its cap.
    bool lobbyAvailable(const LobbyCode& lobbyCode)
    {
        std::lock_guard<std::mutex> lock(mLobbiesMtx);
        return mLobbies.size() < MAX_LOBBIES || mLobbies.find(lobbyCode) != mLobbies.end();
    }

private:
    // Reject a malformed/over-limit session request: tell the client why, keep
    // the connection alive, and create no session (0 = reserved "no session").
    static PlayerGameSessionID rejectSessionRequest(ManagedConnection &connection, const char* reason)
    {
        LOG("Rejected session request from %s:%d: %s",
            connection.clientIP(), connection.clientPort(), reason);
        Message::SessionMessage response(
            Message::Message(ServerMsgTypes::GAME_SESSION_RESPONSE, {
                {Tags::STATUS, ServerStatus::INVALID_REQUEST},
                {Tags::REASON, reason}
            }),
            /*sessionID=*/0, /*seqNum=*/0);
        connection.sendOnSession(response, 0);
        return 0;
    }

    std::atomic<PlayerGameSessionID> sessionCounter;
    std::mutex mLobbiesMtx;
    std::map<LobbyCode, Lobby> mLobbies;
};
}