#pragma once

// PyBridgePlayer — Common::Game::Player implementation that delegates to a
// Python Player instance via pybind11 (embedded interpreter).
//
// Goal: run the existing Python AIs (claude_v1, expert_player, claude_player,
// heuristic_active, …) inside the in-process bench runner with no source
// changes to the AIs. The AIs assume real Python `Round` and `Trick` objects
// passed to their notification hooks; we construct those here from the C++
// notifications and keep them current as state evolves through the round.
//
// State mirrored on the Python side:
//   - clients.python.api.Game.Game    (player_order, rounds)
//   - clients.python.api.Round.Round  (cards_in_hand, donating_cards,
//                                      received_cards, receiving_player,
//                                      donating_player, tricks)
//   - clients.python.api.Trick.Trick  (player_order, moves, winner)
//
// Each PyBridgePlayer holds its own Game/Round/Trick instances — Hearts AIs
// historically maintain their state via these references (see e.g.
// claude_v1.handle_new_round / get_move).
//
// Threading: pybind11 calls require the GIL. Bench games run in a single
// thread per game; the embedded interpreter is initialized once globally in
// bench_runner.cpp before any games start.
//
// Implementation note: this file is header-only because card.h/types.h/
// player.h define free functions without `inline`. Splitting bench_runner
// into multiple TUs that each include those headers would trigger duplicate
// symbol errors at link time. Keeping the bridge inline (single TU) avoids
// the issue without touching the shared engine headers.

#include <algorithm>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include <pybind11/embed.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "server/game/objects/player.h"

namespace Tools::BenchRunner
{

namespace py = pybind11;

class PyBridgePlayer final : public Common::Game::Player
{
public:
    // Construct a PyBridgePlayer. The constructor imports `moduleName`,
    // resolves `className`, and constructs an instance with a
    // PlayerTagSession derived from the C++ tag session (the player_tag is
    // the part before "(seat)").
    inline PyBridgePlayer(Common::Server::PlayerTagSession tagSession,
                          const std::string& moduleName,
                          const std::string& className);

    // --- decision methods ---------------------------------------------------
    inline Common::Game::CardCollection
    getCardsToPass(Common::Game::PassDirection direction) override;
    inline Common::Game::Card
    getMove(const Common::Game::CardCollection& legalPlays) override;

    // --- notification methods ----------------------------------------------
    inline void notifyStartGame(std::vector<Common::Game::PlayerID> playerOrder) override;
    inline void notifyStartRound(int roundIndex,
                                 Common::Game::PassDirection passDirection,
                                 Common::Game::CardCollection hand) override;
    inline void notifyReceivedCards(const Common::Game::CardCollection& receivedCards,
                                    const Common::Game::CardCollection& donatedCards) override;
    inline void notifyStartTrick(int trickIndex,
                                 std::vector<Common::Game::PlayerID> playerOrder) override;
    inline void notifyMove(Common::Game::PlayerID playerID,
                           Common::Game::Card card,
                           bool autoMoved) override;
    inline void notifyEndTrick(Common::Game::PlayerID winningPlayer) override;
    inline void notifyEndRound(std::map<Common::Game::PlayerID, int>& roundScores) override;
    inline void notifyEndGame(std::map<Common::Game::PlayerID, int>& gameScores,
                              Common::Game::PlayerID winner) override;

private:
    // Conversion helpers.
    inline static py::object pyCard(const Common::Game::Card& card);
    inline static Common::Game::Card cppCard(const py::object& pyCardObj);
    inline static py::list pyCardList(const Common::Game::CardCollection& cards);
    inline static py::object pyPassDirection(Common::Game::PassDirection dir);
    inline static py::object pyPlayerTagSession(const std::string& tagSession);
    inline static py::list pyPlayerOrder(const std::vector<Common::Game::PlayerID>& playerOrder);

    // Python class refs (cached for speed; bound once per bridge instance).
    py::object mPlayerTagCls;
    py::object mTagSessionCls;
    py::object mGameCls;
    py::object mRoundCls;
    py::object mTrickCls;
    py::object mMoveCls;

    // Live Python state objects mirroring the C++ Game/Round/Trick loop.
    py::object mPyPlayer;
    py::object mPyPlayerTagSession;
    py::object mPyGame;
    py::object mPyRound;
    py::object mPyTrick;
    std::vector<Common::Game::PlayerID> mPlayerOrder;
    Common::Game::PassDirection mPassDirection = Common::Game::Left;
};

// Convenience factory: given a spec like "claude_v1" or "claude_v1:ClaudeV1"
// or "tim.players.claude_v1:ClaudeV1", resolve the module + class. Resolution
// rules mirror scripts/bench.py:
//   - If spec contains '.', treat as a fully-qualified module name.
//   - Otherwise try "tim.players.<spec>" first, then
//     "clients.python.players.<spec>".
//   - If class name is absent, pick the first Player subclass defined in the
//     module.
//
// The returned player's C++ tagSession is set to "<player_tag>(<seatIdx>)",
// where <player_tag> is the Python class's declared player_tag attribute.
// This keeps the C++ and Python identifiers in lock-step so the engine's
// notifyMove identity checks line up on both sides.
// Throws std::runtime_error on failure.
inline std::shared_ptr<PyBridgePlayer> MakePyBridgePlayer(
    const std::string& placeholderTag,
    const std::string& spec,
    int seatIdx);

// ---------------------------------------------------------------------------
// Helpers (file-local-equivalent — these are not exposed beyond this TU).
// ---------------------------------------------------------------------------

namespace py_bridge_internal
{

inline std::string baseTagFromSession(const std::string& tagSession)
{
    auto pos = tagSession.find('(');
    if (pos == std::string::npos) return tagSession;
    return tagSession.substr(0, pos);
}

inline int seatIdFromSession(const std::string& tagSession)
{
    auto open = tagSession.find('(');
    auto close = tagSession.find(')');
    if (open == std::string::npos || close == std::string::npos || close <= open + 1)
    {
        return 0;
    }
    try
    {
        return std::stoi(tagSession.substr(open + 1, close - open - 1));
    }
    catch (...)
    {
        return 0;
    }
}

inline py::module_ tryImport(const std::string& moduleName)
{
    return py::module_::import(moduleName.c_str());
}

}  // namespace py_bridge_internal

// ---------------------------------------------------------------------------
// PyBridgePlayer implementation
// ---------------------------------------------------------------------------

inline PyBridgePlayer::PyBridgePlayer(Common::Server::PlayerTagSession tagSession,
                                      const std::string& moduleName,
                                      const std::string& className)
    : Common::Game::Player(std::move(tagSession))
{
    using namespace py_bridge_internal;

    py::module_ ptsMod = tryImport("clients.python.api.types.PlayerTagSession");
    py::module_ gameMod = tryImport("clients.python.api.Game");
    py::module_ roundMod = tryImport("clients.python.api.Round");
    py::module_ trickMod = tryImport("clients.python.api.Trick");

    mPlayerTagCls = ptsMod.attr("PlayerTag");
    mTagSessionCls = ptsMod.attr("PlayerTagSession");
    mGameCls = gameMod.attr("Game");
    mRoundCls = roundMod.attr("Round");
    mTrickCls = trickMod.attr("Trick");
    mMoveCls = trickMod.attr("Move");

    std::string fullTag = getTagSession();
    int seat = seatIdFromSession(fullTag);

    py::module_ playerMod = tryImport(moduleName);
    py::object cls = playerMod.attr(className.c_str());

    // The Python Player asserts that its PlayerTagSession.player_tag matches
    // the class's `player_tag` class attribute. Build the PlayerTagSession
    // from that — not from the C++ tag — so heterogeneous lineups (e.g. one
    // bridge per spec) all validate.
    py::object declaredPlayerTag = cls.attr("player_tag");
    py::object playerTagObj = mPlayerTagCls(declaredPlayerTag);
    mPyPlayerTagSession = mTagSessionCls(playerTagObj, seat);

    mPyPlayer = cls(mPyPlayerTagSession);
}

// --- conversion helpers ----------------------------------------------------

inline py::object PyBridgePlayer::pyCard(const Common::Game::Card& card)
{
    Common::Game::Card mutableCard = card;  // getAbbreviation isn't const
    py::module_ mod = py_bridge_internal::tryImport("clients.python.api.types.Card");
    return mod.attr("Card")(mutableCard.getAbbreviation());
}

inline Common::Game::Card PyBridgePlayer::cppCard(const py::object& pyCardObj)
{
    std::string s = py::str(pyCardObj.attr("__repr__")()).cast<std::string>();
    if (s.size() != 2)
    {
        throw std::runtime_error("PyBridgePlayer: Card repr was '" + s
                                 + "' (expected 2 chars)");
    }
    return Common::Game::Card(s);
}

inline py::list PyBridgePlayer::pyCardList(const Common::Game::CardCollection& cards)
{
    py::list out;
    Common::Game::CardCollection mutableCards = cards;  // begin/end not const
    py::module_ mod = py_bridge_internal::tryImport("clients.python.api.types.Card");
    py::object CardCls = mod.attr("Card");
    for (auto card : mutableCards)
    {
        out.append(CardCls(card.getAbbreviation()));
    }
    return out;
}

inline py::object PyBridgePlayer::pyPassDirection(Common::Game::PassDirection dir)
{
    py::module_ mod = py_bridge_internal::tryImport("clients.python.api.types.PassDirection");
    py::object PDCls = mod.attr("PassDirection");
    switch (dir)
    {
        case Common::Game::Left:   return PDCls.attr("LEFT");
        case Common::Game::Right:  return PDCls.attr("RIGHT");
        case Common::Game::Across: return PDCls.attr("ACROSS");
        case Common::Game::Keeper: return PDCls.attr("KEEPER");
    }
    throw std::runtime_error("unknown PassDirection");
}

inline py::object PyBridgePlayer::pyPlayerTagSession(const std::string& tagSession)
{
    py::module_ mod = py_bridge_internal::tryImport("clients.python.api.types.PlayerTagSession");
    return mod.attr("MakePlayerTagSession")(tagSession);
}

inline py::list PyBridgePlayer::pyPlayerOrder(
    const std::vector<Common::Game::PlayerID>& playerOrder)
{
    py::list out;
    for (auto& id : playerOrder) out.append(pyPlayerTagSession(id));
    return out;
}

// --- decisions -------------------------------------------------------------

inline Common::Game::CardCollection
PyBridgePlayer::getCardsToPass(Common::Game::PassDirection direction)
{
    py::object dirObj = pyPassDirection(direction);
    py::object receivingPlayer = dirObj.attr("get_receiving_player")(
        pyPlayerOrder(mPlayerOrder), mPyPlayerTagSession);

    py::list passed = mPyPlayer.attr("get_cards_to_pass")(dirObj, receivingPlayer);
    if (py::len(passed) != 3)
    {
        throw std::runtime_error("PyBridgePlayer: get_cards_to_pass returned "
                                 + std::to_string(py::len(passed))
                                 + " cards (expected 3)");
    }
    std::vector<Common::Game::Card> cards;
    cards.reserve(3);
    for (auto handle : passed)
    {
        cards.push_back(cppCard(py::reinterpret_borrow<py::object>(handle)));
    }
    if (!mPyRound.is_none())
    {
        mPyRound.attr("donating_cards") = passed;
        mPyRound.attr("receiving_player") = receivingPlayer;
    }
    return Common::Game::CardCollection(cards.begin(), cards.end());
}

inline Common::Game::Card
PyBridgePlayer::getMove(const Common::Game::CardCollection& legalPlays)
{
    py::list legal = pyCardList(legalPlays);
    py::object chosen = mPyPlayer.attr("get_move")(mPyTrick, legal);
    return cppCard(chosen);
}

// --- notifications ---------------------------------------------------------

inline void PyBridgePlayer::notifyStartGame(
    std::vector<Common::Game::PlayerID> playerOrder)
{
    mPlayerOrder = playerOrder;
    py::list order = pyPlayerOrder(playerOrder);
    mPyGame = mGameCls(order);
    mPyPlayer.attr("initialize_for_game")(mPyGame);
}

inline void PyBridgePlayer::notifyStartRound(int roundIndex,
                                             Common::Game::PassDirection passDirection,
                                             Common::Game::CardCollection hand)
{
    mPassDirection = passDirection;
    py::object pd = pyPassDirection(passDirection);
    py::list pyHand = pyCardList(hand);
    py::list order = pyPlayerOrder(mPlayerOrder);
    mPyRound = mRoundCls(roundIndex, pd, order, pyHand);
    mPyGame.attr("rounds").attr("append")(mPyRound);
    mPyPlayer.attr("handle_new_round")(mPyRound);
}

inline void PyBridgePlayer::notifyReceivedCards(
    const Common::Game::CardCollection& receivedCards,
    const Common::Game::CardCollection& donatedCards)
{
    py::list received = pyCardList(receivedCards);
    py::list donated = pyCardList(donatedCards);
    py::object dirObj = pyPassDirection(mPassDirection);
    if (!mPyRound.is_none())
    {
        mPyRound.attr("received_cards") = received;
        mPyRound.attr("donating_cards") = donated;
        py::object donatingPlayer = dirObj.attr("get_donating_player")(
            pyPlayerOrder(mPlayerOrder), mPyPlayerTagSession);
        mPyRound.attr("donating_player") = donatingPlayer;
        mPyPlayer.attr("receive_passed_cards")(received, dirObj, donatingPlayer);
    }
    else
    {
        // No round set up (shouldn't happen); fall back to a stub donor.
        py::object donatingPlayer = pyPlayerTagSession(getTagSession());
        mPyPlayer.attr("receive_passed_cards")(received, dirObj, donatingPlayer);
    }
}

inline void PyBridgePlayer::notifyStartTrick(int trickIndex,
                                             std::vector<Common::Game::PlayerID> playerOrder)
{
    py::list order = pyPlayerOrder(playerOrder);
    mPyTrick = mTrickCls(trickIndex, order);
    if (!mPyRound.is_none())
    {
        mPyRound.attr("tricks").attr("append")(mPyTrick);
    }
    mPyPlayer.attr("handle_new_trick")(mPyTrick);
}

inline void PyBridgePlayer::notifyMove(Common::Game::PlayerID playerID,
                                       Common::Game::Card card,
                                       bool /*autoMoved*/)
{
    py::object pyPlayerTag = pyPlayerTagSession(playerID);
    py::object pyC = pyCard(card);
    if (!mPyTrick.is_none())
    {
        mPyTrick.attr("moves").attr("append")(mMoveCls(pyPlayerTag, pyC));
    }
    // Mirror ActiveTrick: the framework removes the played card from the
    // actor's cards_in_hand. claude_v1 et al. rely on this list staying
    // current.
    if (!mPyRound.is_none() && playerID == getTagSession())
    {
        py::list hand = mPyRound.attr("cards_in_hand").cast<py::list>();
        py::list newHand;
        for (auto h : hand)
        {
            py::object c = py::reinterpret_borrow<py::object>(h);
            if (!c.attr("__eq__")(pyC).cast<bool>()) newHand.append(c);
        }
        mPyRound.attr("cards_in_hand") = newHand;
    }
    mPyPlayer.attr("handle_move")(pyPlayerTag, pyC);
}

inline void PyBridgePlayer::notifyEndTrick(Common::Game::PlayerID winningPlayer)
{
    py::object pyWinner = pyPlayerTagSession(winningPlayer);
    if (!mPyTrick.is_none()) mPyTrick.attr("winner") = pyWinner;
    mPyPlayer.attr("handle_finished_trick")(mPyTrick, pyWinner);
}

inline void PyBridgePlayer::notifyEndRound(
    std::map<Common::Game::PlayerID, int>& roundScores)
{
    py::dict pyRoundPoints;
    for (auto& [tag, pts] : roundScores)
    {
        pyRoundPoints[pyPlayerTagSession(tag)] = pts;
    }
    mPyPlayer.attr("handle_finished_round")(mPyRound, pyRoundPoints);
}

inline void PyBridgePlayer::notifyEndGame(
    std::map<Common::Game::PlayerID, int>& gameScores,
    Common::Game::PlayerID winner)
{
    py::dict pyPoints;
    for (auto& [tag, pts] : gameScores)
    {
        pyPoints[pyPlayerTagSession(tag)] = pts;
    }
    py::object pyWinner = pyPlayerTagSession(winner);
    if (!mPyGame.is_none())
    {
        mPyGame.attr("players_to_points") = pyPoints;
        mPyGame.attr("winner") = pyWinner;
    }
    mPyPlayer.attr("handle_end_game")(pyPoints, pyWinner);
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

inline std::shared_ptr<PyBridgePlayer> MakePyBridgePlayer(
    const std::string& /*placeholderTag — unused; we build the real tag below*/,
    const std::string& spec,
    int seatIdx)
{
    using namespace py_bridge_internal;

    std::string moduleSpec;
    std::string classSpec;
    auto colon = spec.find(':');
    if (colon == std::string::npos)
    {
        moduleSpec = spec;
    }
    else
    {
        moduleSpec = spec.substr(0, colon);
        classSpec = spec.substr(colon + 1);
    }

    std::vector<std::string> candidates;
    if (moduleSpec.find('.') == std::string::npos)
    {
        candidates.push_back("tim.players." + moduleSpec);
        candidates.push_back("clients.python.players." + moduleSpec);
    }
    else
    {
        candidates.push_back(moduleSpec);
    }

    py::object mod;
    std::string resolvedModule;
    std::string lastError;
    for (auto& cand : candidates)
    {
        try
        {
            mod = tryImport(cand);
            resolvedModule = cand;
            break;
        }
        catch (py::error_already_set& e)
        {
            if (!lastError.empty()) lastError += " | ";
            lastError += cand + ": " + std::string(e.what()).substr(0, 200);
            continue;
        }
    }
    if (resolvedModule.empty())
    {
        throw std::runtime_error("PyBridgePlayer: could not import any of the "
                                 "candidate modules for spec '" + spec
                                 + "'. Errors: " + lastError);
    }

    if (classSpec.empty())
    {
        py::module_ playerMod = tryImport("clients.python.api.Player");
        py::object PlayerBase = playerMod.attr("Player");
        py::object inspect = tryImport("inspect");
        py::object members = inspect.attr("getmembers")(mod, inspect.attr("isclass"));
        for (auto handle : members)
        {
            auto pair = py::reinterpret_borrow<py::tuple>(handle);
            std::string name = pair[0].cast<std::string>();
            py::object cls = pair[1];
            if (cls.is(PlayerBase)) continue;
            bool isSubclass = py::cast<bool>(
                py::module_::import("builtins").attr("issubclass")(cls, PlayerBase));
            if (!isSubclass) continue;
            std::string clsMod = cls.attr("__module__").cast<std::string>();
            if (clsMod != resolvedModule) continue;
            classSpec = name;
            break;
        }
        if (classSpec.empty())
        {
            throw std::runtime_error("PyBridgePlayer: no Player subclass found in "
                                     + resolvedModule);
        }
    }

    // Build the canonical C++ tag from the Python class's player_tag.
    py::object cls = mod.attr(classSpec.c_str());
    std::string playerTagStr = py::str(cls.attr("player_tag")).cast<std::string>();
    Common::Server::PlayerTagSession tag =
        playerTagStr + "(" + std::to_string(seatIdx) + ")";

    return std::make_shared<PyBridgePlayer>(tag, resolvedModule, classSpec);
}

}  // namespace Tools::BenchRunner
