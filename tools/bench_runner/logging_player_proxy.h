#pragma once

// LoggingPlayerProxy — decorator that wraps any Common::Game::Player and
// emits one NDJSON record per decision (move + pass) to a shared file
// handle. All other Player virtual methods are forwarded verbatim to the
// inner player.
//
// PURPOSE
//   Generate training data for the neural-network player. Each emitted
//   record captures the *inputs* the AI saw plus the card it *chose*. A
//   `game_end` record per game records final scores so a downstream
//   supervised-loss function can weight decisions by outcome.
//
// STATE TRACKED PER PROXY
//   Each proxy mirrors the global game state from its own notify-hook
//   stream — these arrive identically at all four players, so each proxy
//   independently builds:
//     - player order + own seat
//     - current round index, pass direction
//     - current trick index, first seat of trick
//     - cards played so far this trick (seat + card)
//     - all cards played this round (played_so_far)
//     - hearts_broken
//     - per-seat round points (counted from each finished trick), and
//       cumulative per-seat game points
//   The owning seat's hand is read from the wrapped Player's `getHand()`
//   (the engine assigns/updates it directly on the underlying Player —
//   the proxy is the same Player object from the engine's perspective).
//
// CARD ENCODING
//   Two-char strings, e.g. "QS", "TH", "2C" — matches
//   Card::getAbbreviation() and the Python `Card.__str__` convention.
//
// GAME_END RECORD
//   Only the proxy at seat 0 emits the `game_end` line, to avoid four
//   duplicates per game. All proxies see the same final state.
//
// THREAD SAFETY
//   The bench runner is single-threaded per game (the embedded Python
//   interpreter is GIL-bound). We don't lock around fwrite — sufficient
//   for the current single-threaded runner.

#include <algorithm>
#include <cstdio>
#include <map>
#include <memory>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include "server/game/objects/player.h"

namespace Tools::BenchRunner
{

// Shared logging context passed to every proxy in a game. Holds the
// output file handle plus the current game index (incremented by the
// runner between games).
struct DecisionLogContext
{
    std::FILE* fp = nullptr;
    int gameIndex = 0;
};

class LoggingPlayerProxy final : public Common::Game::Player
{
public:
    LoggingPlayerProxy(std::shared_ptr<Common::Game::Player> inner,
                       int seat,
                       std::shared_ptr<DecisionLogContext> ctx)
        : Common::Game::Player(inner->getTagSession()),
          mInner(std::move(inner)),
          mSeat(seat),
          mCtx(std::move(ctx))
    {}

    // ---- decisions: log inputs, delegate, log output --------------------

    Common::Game::CardCollection
    getCardsToPass(Common::Game::PassDirection direction) override
    {
        // The engine holds proxies in its PlayerArray, so all hand
        // mutations (assignHand/removeCardsFromHand/receiveCards) land
        // on the proxy's inherited Player state, not the inner's. Sync
        // the inner before delegating so inner players that read their
        // own hand (e.g. RandomLocalPlayer/LowestLocalPlayer) see the
        // current hand.
        syncInnerHand();
        Common::Game::CardCollection hand = this->getHand();

        Common::Game::CardCollection chosen = mInner->getCardsToPass(direction);

        // Compute receiving seat from pass direction. (Direction is
        // relative to mPlayerOrder, which is seat-ordered.)
        int receivingSeat = receivingSeatForPass(direction);

        emitPassRecord(hand, direction, receivingSeat, chosen);
        return chosen;
    }

    Common::Game::Card
    getMove(const Common::Game::CardCollection& legalPlays) override
    {
        syncInnerHand();
        Common::Game::CardCollection hand = this->getHand();
        Common::Game::Card chosen = mInner->getMove(legalPlays);
        emitMoveRecord(hand, legalPlays, chosen);
        return chosen;
    }

    bool wasLastMoveAuto() const override
    {
        return mInner->wasLastMoveAuto();
    }

    // ---- notifications: update local state, delegate --------------------

    void notifyStartGame(std::vector<Common::Game::PlayerID> playerOrder) override
    {
        mPlayerOrder = playerOrder;
        mPlayerTags = playerOrder;  // tags-in-seat-order
        // Reset per-game cumulative scores.
        mGamePointsBySeat.assign(playerOrder.size(), 0);
        mInner->notifyStartGame(playerOrder);
    }

    void notifyStartRound(int roundIndex,
                          Common::Game::PassDirection passDirection,
                          Common::Game::CardCollection hand) override
    {
        mRoundIndex = roundIndex;
        mPassDirection = passDirection;
        mRoundPointsBySeat.assign(mPlayerOrder.size(), 0);
        mPlayedSoFarThisRound.clear();
        mHeartsBroken = false;
        mInner->notifyStartRound(roundIndex, passDirection, hand);
    }

    void notifyReceivedCards(const Common::Game::CardCollection& receivedCards,
                             const Common::Game::CardCollection& donatedCards) override
    {
        mInner->notifyReceivedCards(receivedCards, donatedCards);
    }

    void notifyStartTrick(int trickIndex,
                          std::vector<Common::Game::PlayerID> playerOrder) override
    {
        mTrickIndex = trickIndex;
        mTrickPlayerOrder = playerOrder;
        mTrickSoFar.clear();
        mFirstSeat = seatOf(playerOrder.front());
        mInner->notifyStartTrick(trickIndex, playerOrder);
    }

    void notifyMove(Common::Game::PlayerID playerID,
                    Common::Game::Card card,
                    bool autoMoved) override
    {
        int actingSeat = seatOf(playerID);
        mTrickSoFar.push_back({actingSeat, card});
        mPlayedSoFarThisRound.push_back(card);
        if (card.getSuit() == Common::Game::HEARTS) mHeartsBroken = true;
        mInner->notifyMove(playerID, card, autoMoved);
    }

    void notifyEndTrick(Common::Game::PlayerID winningPlayer) override
    {
        // Score the trick: count hearts + QS, credit to winning seat.
        int trickPoints = 0;
        for (auto& move : mTrickSoFar)
        {
            if (move.card.getSuit() == Common::Game::HEARTS) trickPoints += 1;
            if (move.card.getRank() == Common::Game::QUEEN
                && move.card.getSuit() == Common::Game::SPADES)
            {
                trickPoints += 13;
            }
        }
        int winningSeat = seatOf(winningPlayer);
        if (winningSeat >= 0
            && winningSeat < static_cast<int>(mRoundPointsBySeat.size()))
        {
            mRoundPointsBySeat[winningSeat] += trickPoints;
        }
        mInner->notifyEndTrick(winningPlayer);
    }

    void notifyEndRound(std::map<Common::Game::PlayerID, int>& roundScores) override
    {
        // Handle shoot-the-moon: if any seat earned 26 in this round, the
        // engine flips so they get 0 and everyone else gets 26. Mirror
        // that here so game_points stays consistent with the engine.
        bool shotMoon = false;
        int shooterSeat = -1;
        for (int s = 0; s < static_cast<int>(mRoundPointsBySeat.size()); ++s)
        {
            if (mRoundPointsBySeat[s] == 26) { shotMoon = true; shooterSeat = s; break; }
        }
        if (shotMoon)
        {
            for (int s = 0; s < static_cast<int>(mRoundPointsBySeat.size()); ++s)
            {
                mRoundPointsBySeat[s] = (s == shooterSeat) ? 0 : 26;
            }
        }
        // Roll into cumulative game points.
        for (int s = 0; s < static_cast<int>(mRoundPointsBySeat.size()); ++s)
        {
            mGamePointsBySeat[s] += mRoundPointsBySeat[s];
        }
        mInner->notifyEndRound(roundScores);
    }

    void notifyEndGame(std::map<Common::Game::PlayerID, int>& gameScores,
                       Common::Game::PlayerID winner) override
    {
        // Only the seat-0 proxy emits the game_end record so each game
        // produces exactly one such line.
        if (mSeat == 0 && mCtx && mCtx->fp)
        {
            emitGameEndRecord(gameScores, winner);
        }
        mInner->notifyEndGame(gameScores, winner);
    }

private:
    // ---- emit helpers --------------------------------------------------

    void emitMoveRecord(const Common::Game::CardCollection& hand,
                        const Common::Game::CardCollection& legalPlays,
                        const Common::Game::Card& chosen)
    {
        if (!mCtx || !mCtx->fp) return;
        std::string out;
        out.reserve(512);
        out += "{\"type\":\"move\",\"game\":";
        out += std::to_string(mCtx->gameIndex);
        out += ",\"round\":";
        out += std::to_string(mRoundIndex);
        out += ",\"trick\":";
        out += std::to_string(mTrickIndex);
        out += ",\"seat\":";
        out += std::to_string(mSeat);
        out += ",\"player_tag\":";
        appendJsonString(out, basePlayerTag());
        out += ",\"hand\":";
        appendCardArray(out, hand);
        out += ",\"legal_moves\":";
        appendCardArray(out, legalPlays);
        out += ",\"trick_so_far\":";
        appendTrickSoFar(out);
        out += ",\"first_seat\":";
        out += std::to_string(mFirstSeat);
        out += ",\"hearts_broken\":";
        out += mHeartsBroken ? "true" : "false";
        out += ",\"played_so_far\":";
        appendCardVector(out, mPlayedSoFarThisRound);
        out += ",\"round_points_by_seat\":";
        appendIntArray(out, mRoundPointsBySeat);
        out += ",\"game_points_by_seat\":";
        appendIntArray(out, mGamePointsBySeat);
        out += ",\"chosen\":";
        appendCardStringJson(out, mutableCopy(chosen));
        out += "}\n";
        std::fwrite(out.data(), 1, out.size(), mCtx->fp);
    }

    void emitPassRecord(const Common::Game::CardCollection& hand,
                        Common::Game::PassDirection direction,
                        int receivingSeat,
                        const Common::Game::CardCollection& chosen)
    {
        if (!mCtx || !mCtx->fp) return;
        std::string out;
        out.reserve(256);
        out += "{\"type\":\"pass\",\"game\":";
        out += std::to_string(mCtx->gameIndex);
        out += ",\"round\":";
        out += std::to_string(mRoundIndex);
        out += ",\"seat\":";
        out += std::to_string(mSeat);
        out += ",\"player_tag\":";
        appendJsonString(out, basePlayerTag());
        out += ",\"pass_dir\":";
        appendJsonString(out, passDirectionString(direction));
        out += ",\"receiving_seat\":";
        out += std::to_string(receivingSeat);
        out += ",\"hand\":";
        appendCardArray(out, hand);
        out += ",\"chosen\":";
        appendCardArray(out, chosen);
        out += "}\n";
        std::fwrite(out.data(), 1, out.size(), mCtx->fp);
    }

    void emitGameEndRecord(std::map<Common::Game::PlayerID, int>& gameScores,
                           Common::Game::PlayerID winner)
    {
        std::vector<int> finalBySeat(mPlayerOrder.size(), 0);
        for (int s = 0; s < static_cast<int>(mPlayerOrder.size()); ++s)
        {
            auto it = gameScores.find(mPlayerOrder[s]);
            finalBySeat[s] = (it == gameScores.end()) ? 0 : it->second;
        }
        int winnerSeat = seatOf(winner);

        std::string out;
        out.reserve(256);
        out += "{\"type\":\"game_end\",\"game\":";
        out += std::to_string(mCtx->gameIndex);
        out += ",\"final_scores\":";
        appendIntArray(out, finalBySeat);
        out += ",\"winner_seat\":";
        out += std::to_string(winnerSeat);
        out += ",\"player_tags\":[";
        for (size_t s = 0; s < mPlayerOrder.size(); ++s)
        {
            if (s) out += ",";
            appendJsonString(out, basePlayerTagFromSession(mPlayerOrder[s]));
        }
        out += "]}\n";
        std::fwrite(out.data(), 1, out.size(), mCtx->fp);
    }

    // ---- small utility helpers -----------------------------------------

    void syncInnerHand()
    {
        // assignHand replaces the inner's hand wholesale — safe to call
        // repeatedly. We do not bother keeping the inner's
        // mTrickPlayedCards / mScore in sync because the engine reads
        // those off the proxy (it only ever holds the proxy in its
        // PlayerArray), and the bundled local players don't consult
        // their own copies.
        mInner->assignHand(this->getHand());
    }

    static Common::Game::Card mutableCopy(const Common::Game::Card& c) { return c; }

    static std::string basePlayerTagFromSession(const std::string& tagSession)
    {
        // Tag sessions are formatted "<player_tag>(<seat>)". Strip the
        // "(<seat>)" suffix to recover the model identifier.
        auto pos = tagSession.find('(');
        if (pos == std::string::npos) return tagSession;
        return tagSession.substr(0, pos);
    }

    std::string basePlayerTag()
    {
        // Player::getTagSession() is non-const in the engine, so this
        // helper has to be non-const as well.
        std::string tag = mInner->getTagSession();
        auto pos = tag.find('(');
        if (pos == std::string::npos) return tag;
        return tag.substr(0, pos);
    }

    int seatOf(const Common::Game::PlayerID& id) const
    {
        for (size_t i = 0; i < mPlayerOrder.size(); ++i)
        {
            if (mPlayerOrder[i] == id) return static_cast<int>(i);
        }
        return -1;
    }

    int receivingSeatForPass(Common::Game::PassDirection dir) const
    {
        int n = static_cast<int>(mPlayerOrder.size());
        if (n <= 0) return -1;
        switch (dir)
        {
            case Common::Game::Left:   return (mSeat + 1) % n;
            case Common::Game::Right:  return (mSeat - 1 + n) % n;
            case Common::Game::Across: return (mSeat + 2) % n;
            case Common::Game::Keeper: return mSeat;
        }
        return -1;
    }

    static std::string passDirectionString(Common::Game::PassDirection dir)
    {
        switch (dir)
        {
            case Common::Game::Left:   return "LEFT";
            case Common::Game::Right:  return "RIGHT";
            case Common::Game::Across: return "ACROSS";
            case Common::Game::Keeper: return "KEEPER";
        }
        return "UNKNOWN";
    }

    // ---- JSON serialization (hand-rolled; no quoting needed for the
    //      values we emit — card abbreviations, integers, booleans, and
    //      ascii player tags). We escape backslash and double-quote
    //      defensively for player tag strings.

    static void appendJsonString(std::string& out, const std::string& s)
    {
        out += '"';
        for (char c : s)
        {
            if (c == '"' || c == '\\') { out += '\\'; out += c; }
            else if (static_cast<unsigned char>(c) < 0x20)
            {
                // Control char: emit \u00XX.
                char buf[8];
                std::snprintf(buf, sizeof(buf), "\\u%04x",
                              static_cast<unsigned int>(static_cast<unsigned char>(c)));
                out += buf;
            }
            else out += c;
        }
        out += '"';
    }

    static void appendCardStringJson(std::string& out, Common::Game::Card c)
    {
        out += '"';
        out += c.getAbbreviation();
        out += '"';
    }

    static void appendCardArray(std::string& out, const Common::Game::CardCollection& cards)
    {
        out += '[';
        // CardCollection's begin/end aren't const, so copy.
        Common::Game::CardCollection mutableCards = cards;
        bool first = true;
        for (auto c : mutableCards)
        {
            if (!first) out += ',';
            first = false;
            appendCardStringJson(out, c);
        }
        out += ']';
    }

    static void appendCardVector(std::string& out,
                                 const std::vector<Common::Game::Card>& cards)
    {
        out += '[';
        bool first = true;
        for (auto c : cards)
        {
            if (!first) out += ',';
            first = false;
            appendCardStringJson(out, c);
        }
        out += ']';
    }

    void appendTrickSoFar(std::string& out) const
    {
        out += '[';
        for (size_t i = 0; i < mTrickSoFar.size(); ++i)
        {
            if (i) out += ',';
            out += "{\"seat\":";
            out += std::to_string(mTrickSoFar[i].seat);
            out += ",\"card\":";
            appendCardStringJson(out, mTrickSoFar[i].card);
            out += '}';
        }
        out += ']';
    }

    static void appendIntArray(std::string& out, const std::vector<int>& v)
    {
        out += '[';
        for (size_t i = 0; i < v.size(); ++i)
        {
            if (i) out += ',';
            out += std::to_string(v[i]);
        }
        out += ']';
    }

    // ---- state ---------------------------------------------------------

    struct SeatedMove { int seat; Common::Game::Card card; };

    std::shared_ptr<Common::Game::Player> mInner;
    int mSeat;
    std::shared_ptr<DecisionLogContext> mCtx;

    // Player ordering (tagSession strings) in seat order.
    std::vector<Common::Game::PlayerID> mPlayerOrder;
    std::vector<Common::Game::PlayerID> mPlayerTags;

    // Round state.
    int mRoundIndex = 0;
    Common::Game::PassDirection mPassDirection = Common::Game::Left;
    bool mHeartsBroken = false;
    std::vector<Common::Game::Card> mPlayedSoFarThisRound;
    std::vector<int> mRoundPointsBySeat;
    std::vector<int> mGamePointsBySeat;

    // Trick state.
    int mTrickIndex = 0;
    int mFirstSeat = 0;
    std::vector<SeatedMove> mTrickSoFar;
    std::vector<Common::Game::PlayerID> mTrickPlayerOrder;
};

}  // namespace Tools::BenchRunner
