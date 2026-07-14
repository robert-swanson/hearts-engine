#pragma once

#include <atomic>
#include <random>
#include <utility>

#include "../game/objects/player.h"

inline std::atomic<int> gAutoMoveLogCount{0};
static constexpr int kAutoMoveLogLimit = 100;

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
                            // Reject duplicate cards: passing the same card twice would
                            // otherwise abort the server when the round subtracts it from
                            // the hand twice (card_collection.h operator-).
                            for (int j = 0; j < i && valid; ++j)
                            {
                                if (cards[i] == cards[j])
                                {
                                    LOG("Client %s tried to pass duplicate card: %s",
                                        mPlayerTagSession.c_str(), cards[i].getAbbreviation().c_str());
                                    valid = false;
                                }
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

    // Clamp a client-derived latency to a sane range: negative (client clock
    // skew or a lying client) becomes "unavailable" (-1); values above an hour
    // are capped so summed stats can't be blown up by one absurd timestamp.
    static long clampLatency(long ms)
    {
        static constexpr long kMaxLatencyMs = 60L * 60L * 1000L;
        if (ms < 0) return -1;
        return ms > kMaxLatencyMs ? kMaxLatencyMs : ms;
    }

    // Returns wall-clock milliseconds since epoch.
    static long nowMs()
    {
        return static_cast<long>(std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count());
    }

    Game::Card getMove(const Game::CardCollection& legalPlays) override
    {
        long sentAt = nowMs();
        mGameSession->send({{
            {Tags::TYPE,          ServerMsgTypes::MOVE_REQUEST},
            {Tags::LEGAL_MOVES,   legalPlays.getCardsAsStrings()},
            {Tags::SENT_AT_MS,    sentAt},
            {Tags::PREV_LATENCY_MS, mLastC2SLatencyMs}  // c2s latency of the previous decided_move
        }});

        mLastMoveWasAuto    = false;
        mLastMoveWasGiveUp  = false;
        mLastS2CLatencyMs   = -1;
        mLastC2SLatencyMs   = -1;
        mLastThinkTimeMs    = -1;

        auto msg = mGameSession->receive();
        long receivedAt = nowMs();
        if (msg)
        {
            auto j = msg->getJson();
            if (j.contains(Tags::CARD))
            {
                try
                {
                    Game::Card card(j[Tags::CARD].get<std::string>());
                    if (legalPlays.contains(card))
                    {
                        // Extract latency metadata from the decided_move. Parsed in
                        // its own try/catch: the metadata is optional client-supplied
                        // telemetry, and a malformed value must not void a legal card
                        // (falling through would auto-play a different one). Values
                        // are clamped — client clocks are untrusted, and a bogus
                        // timestamp shouldn't poison the recorded stats with
                        // negative/absurd latencies.
                        try
                        {
                            if (j.contains(Tags::SENT_AT_MS))
                            {
                                long clientSentAt = j[Tags::SENT_AT_MS].get<long>();
                                mLastC2SLatencyMs  = clampLatency(receivedAt - clientSentAt);
                                if (j.contains(Tags::PREV_LATENCY_MS))
                                {
                                    mLastS2CLatencyMs = clampLatency(j[Tags::PREV_LATENCY_MS].get<long>());
                                    mLastThinkTimeMs  = (mLastS2CLatencyMs >= 0)
                                        ? clampLatency(clientSentAt - sentAt - mLastS2CLatencyMs) : -1;
                                }
                            }
                        }
                        catch (...)
                        {
                            mLastS2CLatencyMs = mLastC2SLatencyMs = mLastThinkTimeMs = -1;
                        }
                        return card;
                    }
                    LOG("Client %s played illegal card %s",
                        mPlayerTagSession.c_str(), card.getAbbreviation().c_str());
                }
                catch (...) { LOG("Client %s sent unparseable card", mPlayerTagSession.c_str()); }
            }
            else { LOG("Client %s move response missing card field", mPlayerTagSession.c_str()); }
        }
        else { LOG("Client %s timed out or disconnected during move", mPlayerTagSession.c_str()); }

        mLastMoveWasAuto   = true;
        mLastMoveWasGiveUp = mGameSession->lastReceiveWasGiveUp();
        return autoMoveCard(legalPlays);
    }

    void notifyMove(PlayerTagSession playerID, Game::Card card, bool autoMoved) override
    {
        long sentAt = nowMs();
        mGameSession->send({{
            {Tags::TYPE,          ServerMsgTypes::MOVE_REPORT},
            {Tags::PLAYER_TAG,    playerID},
            {Tags::CARD,          card.getAbbreviation()},
            {Tags::MOVE_SOURCE,   autoMoved ? MoveSource::SERVER : MoveSource::PLAYER},
            {Tags::SENT_AT_MS,    sentAt},
            {Tags::PREV_LATENCY_MS, mLastC2SLatencyMs}  // c2s latency of the decided_move that just arrived
        }});
    }

    long lastS2CLatencyMs() const override { return mLastS2CLatencyMs; }
    long lastC2SLatencyMs() const override { return mLastC2SLatencyMs; }
    long lastThinkTimeMs()  const override { return mLastThinkTimeMs;  }

    bool wasLastMoveAuto() const override { return mLastMoveWasAuto; }
    bool wasLastMoveGiveUp() const override { return mLastMoveWasGiveUp; }

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
        int n = ++gAutoMoveLogCount;
        if (n <= kAutoMoveLogLimit)
            LOG("Auto-moved %s for client %s%s", chosen.getAbbreviation().c_str(), mPlayerTagSession.c_str(),
                n == kAutoMoveLogLimit ? " (auto-move logging limit reached)" : "");
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
        int n = ++gAutoMoveLogCount;
        if (n <= kAutoMoveLogLimit)
            LOG("Auto-passed for client %s%s", mPlayerTagSession.c_str(),
                n == kAutoMoveLogLimit ? " (auto-move logging limit reached)" : "");
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
    bool mLastMoveWasGiveUp = false;  // auto-played immediately due to give-up mode ("#")
    long mLastS2CLatencyMs = -1;  // server→client latency of last move_request
    long mLastC2SLatencyMs = -1;  // client→server latency of last decided_move
    long mLastThinkTimeMs  = -1;  // client think time for last move
};
}
