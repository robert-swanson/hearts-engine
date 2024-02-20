#pragma once

#include "../api/game_session.h"
#include "../remote_player.h"
#include "../../util/dates.h"
#include "lobby.h"

namespace Common::Server
{

class Matcher
{
private:
    static Matcher instance;

    Matcher(): sessionCounter(0)
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
        }

        Matcher & matcher = GetInstance();
        auto session = matcher.createPlayerGameSession(connection, playerTag);
        matcher.addPlayer(session, lobbyCode);
        return session->getGameSessionID();
    }


    SessionRef createPlayerGameSession(ManagedConnection &connection, const PlayerTag& playerTag)
    {
        auto sessionID = sessionCounter.fetch_add(1, std::memory_order_relaxed);
        auto session = std::make_shared<PlayerGameSession>(sessionID, playerTag, connection);
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