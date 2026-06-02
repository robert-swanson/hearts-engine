#pragma once

#include <chrono>

#include "server/api/game_session.h"
#include "server/game/remote_player.h"
#include "server/util/dates.h"
#include "server/util/env.h"
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

    static PlayerGameSessionID HandleSessionRequest(ManagedConnection &connection, Message::Message message)
    {
        auto playerTag = message.getTag<PlayerTag>(Tags::PLAYER_TAG);
        LobbyCode lobbyCode = DEFAULT_LOBBY_CODE;
        if (message.hasTag(Tags::LOBBY_CODE))
        {
            lobbyCode = message.getTag<std::string>(Tags::LOBBY_CODE);
            lobbyCode = lobbyCode.empty() ? DEFAULT_LOBBY_CODE : lobbyCode;
        }

        Matcher & matcher = GetInstance();
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
        if (mLobbies.find(lobbyCode) == mLobbies.end())
        {
            mLobbies.emplace(lobbyCode, lobbyCode);
        }
        mLobbies.at(lobbyCode).addPlayer(playerSession);
    }


private:
    std::atomic<PlayerGameSessionID> sessionCounter;
    std::map<LobbyCode, Lobby> mLobbies;
};
}