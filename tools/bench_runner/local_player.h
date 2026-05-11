#pragma once

// LocalPlayer: in-process player implementations for the headless bench
// runner. These extend Common::Game::Player directly and provide the same
// hooks as RemotePlayer, but without TCP/JSON. The Game/Round/Trick loop
// in //server/game is reused unchanged.
//
// Two trivial built-ins are provided so the runner can produce real games
// before any Python/pybind11 plumbing exists:
//
//   RandomLocalPlayer  — uniform random over legal moves; shuffled passes.
//                        Matches the behaviour of clients/python/players/
//                        random_player.py.
//   LowestLocalPlayer  — always plays the lowest legal card; passes the
//                        three highest cards. Provides a deterministic
//                        sanity baseline (a "rock" opponent).
//
// A future PyBridgePlayer (not yet present) will subclass Player the same
// way and forward each virtual method into a Python Player instance held
// via pybind11. Adding it does not require changes to Game/Round/Trick or
// to this header — see bench_runner.cpp for the integration plan.

#include <algorithm>
#include <memory>
#include <random>
#include <string>
#include <utility>
#include <vector>

#include "server/game/objects/player.h"

namespace Tools::BenchRunner
{

// Base class for in-process players. Implements the trivial notify-* hooks
// as no-ops (they exist for state tracking, which most AIs don't need at
// this level — anything that does, override the hooks). Subclasses must
// implement getCardsToPass and getMove.
class LocalPlayer : public Common::Game::Player
{
public:
    explicit LocalPlayer(Common::Server::PlayerTagSession tagSession)
        : Player(std::move(tagSession)) {}

    void notifyStartGame(std::vector<Common::Game::PlayerID>) override {}
    void notifyStartRound(int, Common::Game::PassDirection,
                          Common::Game::CardCollection) override {}
    void notifyReceivedCards(const Common::Game::CardCollection&,
                             const Common::Game::CardCollection&) override {}
    void notifyStartTrick(int, std::vector<Common::Game::PlayerID>) override {}
    void notifyMove(Common::Game::PlayerID, Common::Game::Card, bool) override {}
    void notifyEndTrick(Common::Game::PlayerID) override {}
    void notifyEndRound(std::map<Common::Game::PlayerID, int>&) override {}
    void notifyEndGame(std::map<Common::Game::PlayerID, int>&,
                       Common::Game::PlayerID) override {}
};

class RandomLocalPlayer final : public LocalPlayer
{
public:
    explicit RandomLocalPlayer(Common::Server::PlayerTagSession tagSession,
                               std::mt19937::result_type seed)
        : LocalPlayer(std::move(tagSession)), mRng(seed) {}

    Common::Game::CardCollection getCardsToPass(Common::Game::PassDirection) override
    {
        Common::Game::CardCollection hand = getHand();
        std::vector<int> indices(hand.size());
        std::iota(indices.begin(), indices.end(), 0);
        std::shuffle(indices.begin(), indices.end(), mRng);
        std::vector<Common::Game::Card> chosen;
        chosen.reserve(3);
        for (int i = 0; i < 3; ++i)
            chosen.push_back(hand[indices[i]]);
        return Common::Game::CardCollection(chosen.begin(), chosen.end());
    }

    Common::Game::Card getMove(const Common::Game::CardCollection& legalPlays) override
    {
        std::uniform_int_distribution<int> dist(0, static_cast<int>(legalPlays.size()) - 1);
        return legalPlays[dist(mRng)];
    }

private:
    std::mt19937 mRng;
};

// Plays the lowest legal card; passes the three highest by rank+suit order.
// Useful as a deterministic baseline / smoke-test opponent.
class LowestLocalPlayer final : public LocalPlayer
{
public:
    explicit LowestLocalPlayer(Common::Server::PlayerTagSession tagSession)
        : LocalPlayer(std::move(tagSession)) {}

    Common::Game::CardCollection getCardsToPass(Common::Game::PassDirection) override
    {
        std::vector<Common::Game::Card> cards;
        for (auto& c : getHand()) cards.push_back(c);
        std::sort(cards.begin(), cards.end());  // ascending
        // Pass the three highest.
        std::vector<Common::Game::Card> chosen(cards.end() - 3, cards.end());
        return Common::Game::CardCollection(chosen.begin(), chosen.end());
    }

    Common::Game::Card getMove(const Common::Game::CardCollection& legalPlays) override
    {
        Common::Game::Card best = legalPlays[0];
        for (int i = 1; i < static_cast<int>(legalPlays.size()); ++i)
        {
            Common::Game::Card c = legalPlays[i];
            if (c < best) best = c;
        }
        return best;
    }
};

}  // namespace Tools::BenchRunner
