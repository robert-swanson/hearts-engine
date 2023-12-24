#pragma once

#include <utility>

#include "../game/objects/player.h"

namespace Common::Server
{
class RemotePlayer: public Game::Player
{
public:
    explicit RemotePlayer(PlayerTagSession tagSession, const std::shared_ptr<PlayerGameSession>& gameSession) :
            Player(std::move(tagSession)), mGameSession(gameSession), mPlayerTagSession(gameSession->getPlayerTagSession()) {}

    void notifyStartGame(std::vector<PlayerTagSession> playerOrder) override
    {
        mGameSession->send({{
            {Tags::TYPE, ServerMsgTypes::START_GAME},
            {Tags::PLAYER_ORDER, playerOrder}
        }});
    }

    void notifyStartRound(int roundIndex, Game::PassDirection passDirection, Game::CardCollection hand) override
    {
        mGameSession->send({{
            {Tags::TYPE, ServerMsgTypes::START_ROUND},
            {Tags::ROUND_INDEX, roundIndex},
            {Tags::PASS_DIRECTION, PassDirectionToString(passDirection)},
            {Tags::CARDS, hand.getCardsAsStrings()}
        }});
    }

    Game::CardCollection getCardsToPass(Game::PassDirection direction) override
    {
        auto donatedCardsMsg = mGameSession->receive().getJson();
        Game::CardCollection cards(donatedCardsMsg[Tags::CARDS]);
        return cards;
    }

    void notifyReceivedCards(const Game::CardCollection& receivedCards) override
    {
        mGameSession->send({{
            {Tags::TYPE, ServerMsgTypes::RECEIVED_CARDS},
            {Tags::CARDS, receivedCards.getCardsAsStrings()}
        }});
    }

    void notifyStartTrick(int trickIndex, std::vector<PlayerTagSession> playerOrder) override
    {
        mGameSession->send({{
            {Tags::TYPE, ServerMsgTypes::START_TRICK},
            {Tags::TRICK_INDEX, trickIndex},
            {Tags::PLAYER_ORDER, playerOrder}
        }});
    }

    Game::Card getMove(const Game::CardCollection& legalPlays) override
    {
        mGameSession->send({{
            {Tags::TYPE, ServerMsgTypes::MOVE_REQUEST},
            {Tags::LEGAL_MOVES, legalPlays.getCardsAsStrings()}
        }});
        auto moveMsg = mGameSession->receive().getJson();
        return Game::Card(moveMsg[Tags::CARD]);
    }

    void notifyMove(PlayerTagSession playerID, Game::Card card) override
    {
        mGameSession->send({{
            {Tags::TYPE, ServerMsgTypes::MOVE_REPORT},
            {Tags::PLAYER_TAG, playerID},
            {Tags::CARD, card.getAbbreviation()}
        }});
    }

    void notifyEndTrick(PlayerTagSession winningPlayer) override
    {
        mGameSession->send({{
            {Tags::TYPE, ServerMsgTypes::END_TRICK},
            {Tags::WINNING_PLAYER, winningPlayer}
        }});
    }

    void notifyEndRound(std::map<PlayerTagSession, int> & roundScores) override
    {
        mGameSession->send({{
            {Tags::TYPE, ServerMsgTypes::END_ROUND},
            {Tags::PLAYER_TO_ROUND_POINTS, roundScores}
        }});
    }

    void notifyEndGame(std::map<PlayerTagSession, int> & gameScores, PlayerTagSession winner) override
    {
        mGameSession->send({{
            {Tags::TYPE, ServerMsgTypes::END_GAME},
            {Tags::PLAYER_TO_GAME_POINTS, gameScores},
            {Tags::WINNING_PLAYER, winner}
        }});
    }

private:
    std::shared_ptr<PlayerGameSession> mGameSession;
    PlayerTagSession mPlayerTagSession;
};
}
