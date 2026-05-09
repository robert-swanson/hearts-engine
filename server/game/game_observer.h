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
    virtual void onTrickComplete(const std::string& firstPlayer,
                                  const std::vector<std::string>& cards,  // in play order
                                  const std::string& winner, int points) {}
    virtual void onRoundComplete(int roundIdx, const std::map<std::string, int>& scores) {}
    virtual void onMove(const std::string& playerTag, long latencyMs, bool autoMoved) {}
    virtual void onMoonShot(const std::string& shooter) {}
    virtual void onGameComplete(const std::map<std::string, int>& finalScores,
                                 const std::string& winner) {}
};

} // namespace Common::Game
