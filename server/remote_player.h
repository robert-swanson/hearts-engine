#pragma once

#include "../game/objects/player.h"

namespace Common::Server
{
class RemotePlayer: public Game::Player
{
public:
    explicit RemotePlayer(PlayerID name, PlayerGameSession &gameSession) :
            Player(name), mGameSession(gameSession), mPlayerID(gameSession.getPlayerId()) {}

    void notifyStartGame(std::vector<Game::PlayerID> playerOrder) override
    {
        mGameSession.send({{
            {Tags::TYPE, ServerMsgTypes::START_GAME},
            {Tags::PLAYER_ORDER, playerOrder}
        }});
    }

    void notifyStartRound(int roundIndex, Game::PassDirection passDirection, Game::CardCollection hand) override
    {
        mGameSession.send({{
            {Tags::TYPE, ServerMsgTypes::START_ROUND},
            {Tags::ROUND_INDEX, roundIndex},
            {Tags::PASS_DIRECTION, PassDirectionToString(passDirection)},
            {Tags::CARDS, hand.getCardsAsStrings()}
        }});
    }

    Game::CardCollection getCardsToPass(Game::PassDirection direction) override
    {
        auto donatedCardsMsg = mGameSession.receive().getJson();
        Game::CardCollection cards(donatedCardsMsg[Tags::CARDS]);
        return cards;
    }

    void notifyReceivedCards(const Game::CardCollection& receivedCards) override
    {
        mGameSession.send({{
            {Tags::TYPE, ServerMsgTypes::RECEIVED_CARDS},
            {Tags::CARDS, receivedCards.getCardsAsStrings()}
        }});
    }

    void notifyStartTrick(int trickIndex, std::vector<Game::PlayerID> playerOrder) override
    {
        mGameSession.send({{
            {Tags::TYPE, ServerMsgTypes::START_TRICK},
            {Tags::TRICK_INDEX, trickIndex},
            {Tags::PLAYER_ORDER, playerOrder}
        }});
    }

    Game::Card getMove(const Game::CardCollection& legalPlays) override
    {
        mGameSession.send({{
            {Tags::TYPE, ServerMsgTypes::MOVE_REQUEST},
            {Tags::LEGAL_MOVES, legalPlays.getCardsAsStrings()}
        }});
        auto moveMsg = mGameSession.receive().getJson();
        return Game::Card(moveMsg[Tags::CARD]);
    }

    void notifyMove(Game::PlayerID playerID, Game::Card card) override
    {
        mGameSession.send({{
            {Tags::TYPE, ServerMsgTypes::MOVE_REPORT},
            {Tags::PLAYER_TAG, playerID},
            {Tags::CARD, card.getAbbreviation()}
        }});
    }

    void notifyEndTrick(Game::PlayerID winningPlayer) override
    {
        mGameSession.send({{
            {Tags::TYPE, ServerMsgTypes::END_TRICK},
            {Tags::WINNING_PLAYER, winningPlayer}
        }});
    }

    void notifyEndRound(std::map<Game::PlayerID, int> & roundScores) override
    {
        mGameSession.send({{
            {Tags::TYPE, ServerMsgTypes::END_ROUND},
            {Tags::PLAYER_TO_ROUND_POINTS, roundScores}
        }});
    }

    void notifyEndGame(std::map<Game::PlayerID, int> & gameScores, Game::PlayerID winner) override
    {
        mGameSession.send({{
            {Tags::TYPE, ServerMsgTypes::END_GAME},
            {Tags::PLAYER_TO_GAME_POINTS, gameScores},
            {Tags::WINNING_PLAYER, winner}
        }});
    }

private:
    PlayerGameSession &mGameSession;
    Game::PlayerID mPlayerID;
};
}
