#pragma once

#include <random>
#include <utility>

#include "../game/objects/player.h"

namespace Common::Server
{
class RemotePlayer : public Game::Player
{
public:
    explicit RemotePlayer(PlayerTagSession tagSession, const std::shared_ptr<PlayerGameSession>& gameSession) :
            Player(std::move(tagSession)), mGameSession(gameSession), mPlayerTagSession(gameSession->getPlayerTagSession()),
            mLastMoveWasAuto(false) {}

    ~RemotePlayer() override = default;

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
        auto msg = mGameSession->receive();
        if (msg)
        {
            auto json = msg->getJson();
            if (json.contains(Tags::CARDS))
            {
                try
                {
                    Game::CardCollection cards(json[Tags::CARDS]);
                    if (cards.size() == 3)
                    {
                        bool valid = true;
                        for (int i = 0; i < 3 && valid; ++i)
                        {
                            if (!getHand().contains(cards[i]))
                            {
                                LOG("Client %s tried to pass card not in hand: %s",
                                    mPlayerTagSession.c_str(), cards[i].getAbbreviation().c_str());
                                valid = false;
                            }
                        }
                        if (valid)
                            return cards;
                    }
                }
                catch (...) { LOG("Client %s sent invalid pass cards", mPlayerTagSession.c_str()); }
            }
            else { LOG("Client %s pass response missing cards field", mPlayerTagSession.c_str()); }
        }
        else { LOG("Client %s timed out or disconnected during pass", mPlayerTagSession.c_str()); }
        return autoPassCards();
    }

    void notifyReceivedCards(const Game::CardCollection& receivedCards, const Game::CardCollection& donatedCards) override
    {
        mGameSession->send({{
            {Tags::TYPE, ServerMsgTypes::RECEIVED_CARDS},
            {Tags::CARDS, receivedCards.getCardsAsStrings()},
            {Tags::DONATED_CARDS, donatedCards.getCardsAsStrings()}
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

        mLastMoveWasAuto = false;
        auto msg = mGameSession->receive();
        if (msg)
        {
            auto json = msg->getJson();
            if (json.contains(Tags::CARD))
            {
                try
                {
                    Game::Card card(json[Tags::CARD].get<std::string>());
                    if (legalPlays.contains(card))
                        return card;
                    LOG("Client %s played illegal card %s",
                        mPlayerTagSession.c_str(), card.getAbbreviation().c_str());
                }
                catch (...) { LOG("Client %s sent unparseable card", mPlayerTagSession.c_str()); }
            }
            else { LOG("Client %s move response missing card field", mPlayerTagSession.c_str()); }
        }
        else { LOG("Client %s timed out or disconnected during move", mPlayerTagSession.c_str()); }

        mLastMoveWasAuto = true;
        return autoMoveCard(legalPlays);
    }

    void notifyMove(PlayerTagSession playerID, Game::Card card, bool autoMoved) override
    {
        mGameSession->send({{
            {Tags::TYPE, ServerMsgTypes::MOVE_REPORT},
            {Tags::PLAYER_TAG, playerID},
            {Tags::CARD, card.getAbbreviation()},
            {Tags::MOVE_SOURCE, autoMoved ? MoveSource::SERVER : MoveSource::PLAYER}
        }});
    }

    bool wasLastMoveAuto() const override { return mLastMoveWasAuto; }

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
    Game::Card autoMoveCard(const Game::CardCollection& legalPlays)
    {
        Game::Card chosen = randomCard(legalPlays);
        LOG("Auto-moved %s for client %s", chosen.getAbbreviation().c_str(), mPlayerTagSession.c_str());
        return chosen;
    }

    Game::CardCollection autoPassCards()
    {
        Game::CardCollection hand = getHand();
        std::vector<Game::Card> chosen;
        std::mt19937 rng{std::random_device{}()};
        std::vector<int> indices(hand.size());
        std::iota(indices.begin(), indices.end(), 0);
        std::shuffle(indices.begin(), indices.end(), rng);
        for (int i = 0; i < 3; ++i)
            chosen.push_back(hand[indices[i]]);
        LOG("Auto-passed for client %s", mPlayerTagSession.c_str());
        return Game::CardCollection(chosen.begin(), chosen.end());
    }

    static Game::Card randomCard(const Game::CardCollection& cards)
    {
        std::mt19937 rng{std::random_device{}()};
        std::uniform_int_distribution<int> dist(0, static_cast<int>(cards.size()) - 1);
        return cards[dist(rng)];
    }

    std::shared_ptr<PlayerGameSession> mGameSession;
    PlayerTagSession mPlayerTagSession;
    bool mLastMoveWasAuto;
};
}
