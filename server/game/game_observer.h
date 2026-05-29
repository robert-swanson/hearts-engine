#pragma once
#include <map>
#include <string>
#include <vector>

namespace Common::Game {

// Observer called by Game/Round/Trick during execution.
// All methods are no-ops by default; implementors override what they need.
class GameObserver {
public:
    virtual ~GameObserver() = default;

    virtual void onStartRound(int roundIdx, const std::string& passDir) {}
    virtual void onHandsAfterPass(const std::map<std::string, std::vector<std::string>>& hands) {}
    // passedByPlayer: playerTagSession → 3 cards they passed (empty map on Keeper rounds)
    virtual void onCardsPassed(const std::map<std::string, std::vector<std::string>>& passedByPlayer) {}
    virtual void onTrickComplete(const std::vector<std::string>& playerOrder, // play order
                                  const std::vector<std::string>& cards,       // play order
                                  const std::string& winner, int points) {}
    virtual void onRoundComplete(int roundIdx, const std::map<std::string, int>& scores) {}
    virtual void onMove(const std::string& playerTag, long latencyMs, bool autoMoved,
                        long s2cMs, long c2sMs, long thinkMs) {}
    virtual void onMoonShot(const std::string& shooter) {}
    virtual void onGameComplete(const std::map<std::string, int>& finalScores,
                                 const std::string& winner) {}
};

} // namespace Common::Game
