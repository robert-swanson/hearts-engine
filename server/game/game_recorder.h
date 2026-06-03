#pragma once

// Shared game-recording machinery used by both the tournament server and the
// regular (lobby) server. A RecordingObserver accumulates per-game structure
// (rounds, passes, tricks, scores, latency) during play; the helpers below turn
// that into the browsable detail JSON the web UI reads.
//
// Tournament-specific fields (stage, placement points, slot mapping) live on the
// same GameResult struct but are simply left empty for lobby games.

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <map>
#include <mutex>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "game_observer.h"
#include "../util/constants.h"  // Common::Server::MoveSource

namespace Common::Game {

using json = nlohmann::json;

// ─── Game result collection ───────────────────────────────────────────────────

struct TrickRecord {
    std::string firstPlayer;
    std::vector<std::string> playerTags; // play order (playerTags[i] played cards[i])
    std::vector<std::string> cards;
    std::vector<std::string> moveSources; // play order: "player" | "timeout" | "give_up"
    std::string winner;
    int points;
};

struct RoundRecord {
    int roundIdx;
    std::string passDir;
    std::map<std::string, std::vector<std::string>> cardsPassed;   // playerTagSession → 3 cards passed
    std::map<std::string, std::vector<std::string>> handsAfterPass;
    std::vector<TrickRecord> tricks;
    std::map<std::string, int> roundScores;
};

struct GameResult {
    std::string gameId;
    std::string stage;
    std::vector<std::string> playerOrder; // actual seating order (rotation around table)
    std::map<std::string, int> finalScores;
    std::string winner;
    int roundsPlayed = 0;
    std::map<std::string, int> moonShots;
    std::map<std::string, long> totalMoveLatencyMs;
    std::map<std::string, int> autoMoveCount;
    // Latency breakdown (only for non-auto moves with metadata)
    std::map<std::string, long> totalS2CMs;       // server→client (move_request delivery)
    std::map<std::string, long> totalC2SMs;       // client→server (decided_move delivery)
    std::map<std::string, long> totalThinkMs;     // client think time
    std::map<std::string, long> maxThinkMs;       // per-player max think time
    std::map<std::string, long> maxS2CMs;         // per-player max s2c
    std::map<std::string, long> maxC2SMs;         // per-player max c2s
    std::map<std::string, long> maxMoveLatencyMs; // per-player max total move time (server wall clock)
    std::map<std::string, int>  latencyCount;     // number of moves with latency data

    // End-to-end move-time histogram, per player. moveTimeoutMs is divided into
    // 100ms buckets; bucket i (0..numBuckets-2) counts moves whose total latency
    // fell in [i*100, (i+1)*100) ms. The final bucket (index numBuckets-1) is the
    // "timeout" bucket: every auto/timed-out move lands here (rendered red in the
    // UI). numBuckets = moveTimeoutMs/100 + 1. Empty when moveTimeoutMs <= 0.
    long moveTimeoutMs = 0;
    std::map<std::string, std::vector<long>> latencyHistogram;

    std::vector<RoundRecord> rounds;

    // Placement points awarded in qualifying (tournament only)
    std::map<std::string, int> placementPoints;

    // Maps "playerTag(sessionId)" → slotId for score aggregation (tournament only)
    std::map<std::string, std::string> playerTagToSlotId;
};

class RecordingObserver : public GameObserver {
public:
    GameResult result;

    explicit RecordingObserver(const std::string& gameId, const std::string& stage = "lobby",
                               long moveTimeoutMs = 0)
    {
        result.gameId        = gameId;
        result.stage         = stage;
        result.moveTimeoutMs = moveTimeoutMs;
    }

    void onStartRound(int roundIdx, const std::string& passDir) override
    {
        RoundRecord r;
        r.roundIdx  = roundIdx;
        r.passDir   = passDir;
        result.rounds.push_back(std::move(r));
    }

    void onHandsAfterPass(const std::map<std::string, std::vector<std::string>>& hands) override
    {
        if (!result.rounds.empty())
            result.rounds.back().handsAfterPass = hands;
    }

    void onCardsPassed(const std::map<std::string, std::vector<std::string>>& passed) override
    {
        if (!result.rounds.empty())
            result.rounds.back().cardsPassed = passed;
    }

    void onTrickComplete(const std::vector<std::string>& playerOrder,
                          const std::vector<std::string>& cards,
                          const std::vector<std::string>& moveSources,
                          const std::string& winner, int points) override
    {
        std::string firstPlayer = playerOrder.empty() ? "" : playerOrder[0];
        if (!result.rounds.empty())
            result.rounds.back().tricks.push_back(
                {firstPlayer, playerOrder, cards, moveSources, winner, points});
    }

    void onRoundComplete(int /*roundIdx*/, const std::map<std::string, int>& scores) override
    {
        result.roundsPlayed++;
        if (!result.rounds.empty())
            result.rounds.back().roundScores = scores;
    }

    void onMove(const std::string& playerTag, long latencyMs, bool autoMoved,
                long s2cMs, long c2sMs, long thinkMs) override
    {
        result.totalMoveLatencyMs[playerTag] += latencyMs;
        result.maxMoveLatencyMs[playerTag]    = std::max(result.maxMoveLatencyMs[playerTag], latencyMs);

        // Histogram: 100ms buckets across [0, moveTimeoutMs), plus a final "timeout"
        // bucket for auto-moves (and the rare completed move at/over the timeout).
        if (result.moveTimeoutMs > 0)
        {
            int numBuckets = (int)(result.moveTimeoutMs / 100) + 1; // last = timeout bucket
            auto& hist = result.latencyHistogram[playerTag];
            if ((int)hist.size() != numBuckets) hist.assign(numBuckets, 0);
            int idx;
            if (autoMoved || latencyMs >= result.moveTimeoutMs)
            {
                idx = numBuckets - 1; // timeout bucket
            }
            else
            {
                idx = (int)(latencyMs / 100);
                if (idx > numBuckets - 2) idx = numBuckets - 2;
                if (idx < 0) idx = 0;
            }
            hist[idx]++;
        }

        if (autoMoved)
        {
            result.autoMoveCount[playerTag]++;
        }
        else if (s2cMs >= 0 && c2sMs >= 0 && thinkMs >= 0)
        {
            result.totalS2CMs[playerTag]   += s2cMs;
            result.totalC2SMs[playerTag]   += c2sMs;
            result.totalThinkMs[playerTag] += thinkMs;
            result.maxThinkMs[playerTag]    = std::max(result.maxThinkMs[playerTag], thinkMs);
            result.maxS2CMs[playerTag]      = std::max(result.maxS2CMs[playerTag], s2cMs);
            result.maxC2SMs[playerTag]      = std::max(result.maxC2SMs[playerTag], c2sMs);
            result.latencyCount[playerTag]++;
        }
    }

    void onMoonShot(const std::string& shooter) override
    {
        result.moonShots[shooter]++;
    }

    void onGameComplete(const std::map<std::string, int>& finalScores,
                         const std::string& winner) override
    {
        result.finalScores = finalScores;
        result.winner      = winner;
        // playerOrder is populated by the caller with the actual seating order.
    }
};

// ─── Player ID helpers ────────────────────────────────────────────────────────

// Standard player ID format: team/player_tag/slot/session_id
// Truncated from the right when components are unavailable.
//
// toFullId: converts "playerTag(sessionId)" → "team/player_tag/slot/session_id"
//   using the tagToSlotId map (which carries the team/player_tag/slot part).
//   For lobby games tagToSlotId is empty, so the raw "playerTag(sessionId)" is
//   returned unchanged — still internally consistent across all maps.
inline std::string toFullId(const std::string& playerTagSession,
                            const std::map<std::string, std::string>& tagToSlotId)
{
    auto it = tagToSlotId.find(playerTagSession);
    if (it == tagToSlotId.end()) return playerTagSession;          // fallback: unknown
    auto open  = playerTagSession.rfind('(');
    auto close = playerTagSession.rfind(')');
    if (open == std::string::npos || close == std::string::npos || close <= open)
        return it->second;                                         // slotId only
    return it->second + "/" + playerTagSession.substr(open + 1, close - open - 1);
}

// Remap keys of m through toFullId; values are preserved unchanged.
template<typename V>
inline json remapKeys(const std::map<std::string, V>& m,
                      const std::map<std::string, std::string>& tagToSlotId)
{
    json j = json::object();
    for (const auto& [k, v] : m)
        j[toFullId(k, tagToSlotId)] = v;
    return j;
}

// ─── Detail JSON (per-game rounds/tricks/hands) ───────────────────────────────

inline json gameResultToDetailJson(const GameResult& gr)
{
    json j;
    j["game_id"] = gr.gameId;

    // Seating order — lets readers map moves[i] to the correct player.
    // For each trick: find first_player's index in player_order, then moves[k]
    // is player_order[(first_player_idx + k) % 4]'s card.
    std::vector<std::string> fullOrder;
    for (const auto& ts : gr.playerOrder)
        fullOrder.push_back(toFullId(ts, gr.playerTagToSlotId));
    j["player_order"] = fullOrder;

    json rounds = json::array();
    for (const auto& r : gr.rounds)
    {
        json rj;
        rj["round_idx"]           = r.roundIdx;
        rj["pass_direction"]      = r.passDir;
        if (!r.cardsPassed.empty())
            rj["cards_passed"]    = remapKeys(r.cardsPassed, gr.playerTagToSlotId);
        rj["hands_after_passing"] = remapKeys(r.handsAfterPass, gr.playerTagToSlotId);

        json tricks = json::array();
        for (const auto& t : r.tricks)
        {
            json tj;
            tj["first_player"] = toFullId(t.firstPlayer, gr.playerTagToSlotId);
            tj["moves"]        = t.cards; // in play order starting from first_player
            // Per-move provenance aligned with moves[]: "player" | "timeout" | "give_up".
            // Omitted when every move was a normal player move, to keep typical games lean.
            if (std::any_of(t.moveSources.begin(), t.moveSources.end(),
                            [](const std::string& s){ return s != Common::Server::MoveSource::PLAYER; }))
                tj["move_sources"] = t.moveSources;
            tj["winner"]       = toFullId(t.winner, gr.playerTagToSlotId);
            tj["points"]       = t.points;
            tricks.push_back(tj);
        }
        rj["tricks"]       = tricks;
        rj["round_scores"] = remapKeys(r.roundScores, gr.playerTagToSlotId);
        rounds.push_back(rj);
    }
    j["rounds"] = rounds;
    return j;
}

// Compact the card arrays inside hands_after_passing sections of a JSON string.
// Every player's hand (array of 2–3-char strings) is collapsed to one line;
// the rest of the JSON keeps its normal indent.
inline std::string compactHandArrays(const std::string& raw)
{
    std::string out;
    out.reserve(raw.size());
    std::size_t i = 0;
    while (i < raw.size())
    {
        static const char kKey[] = "\"hands_after_passing\"";
        auto found = raw.find(kKey, i);
        if (found == std::string::npos) { out += raw.substr(i); break; }
        // Copy up to and including the key
        out += raw.substr(i, found - i + sizeof(kKey) - 1);
        i = found + sizeof(kKey) - 1;
        // Find the opening '{' of the value object
        auto braceOpen = raw.find('{', i);
        if (braceOpen == std::string::npos) { out += raw.substr(i); break; }
        out += raw.substr(i, braceOpen - i + 1);
        i = braceOpen + 1;
        // Scan the hands object, compacting each player's card array
        int depth = 1;
        while (i < raw.size() && depth > 0)
        {
            char c = raw[i];
            if      (c == '{') { ++depth; out += c; ++i; }
            else if (c == '}') { --depth; if (depth > 0) out += c; ++i; }
            else if (c == '[' && depth == 1)
            {
                // Compact this array to one line
                auto end = raw.find(']', i);
                if (end == std::string::npos) { out += c; ++i; continue; }
                out += '[';
                bool first = true;
                std::size_t q = i + 1;
                while (q <= end)
                {
                    auto q1 = raw.find('"', q);
                    if (q1 == std::string::npos || q1 > end) break;
                    auto q2 = raw.find('"', q1 + 1);
                    if (q2 == std::string::npos || q2 > end) break;
                    if (!first) out += ", ";
                    out += '"'; out += raw.substr(q1 + 1, q2 - q1 - 1); out += '"';
                    first = false;
                    q = q2 + 1;
                }
                out += ']';
                i = end + 1;
            }
            else { out += c; ++i; }
        }
        if (depth == 0) out += '}'; // closing brace of the hands object
    }
    return out;
}

// ─── Lobby result writing ─────────────────────────────────────────────────────
//
// Lobby (non-tournament) games are written under <resultsDir>/lobby/:
//   <resultsDir>/lobby/games/<game_id>.json   detail (same shape as tournaments)
//   <resultsDir>/lobby/index.json             append-only list of game metadata
//
// Concurrent games append to index.json under a process-wide mutex.

inline json gameResultToLobbyIndexEntry(const GameResult& gr, const std::string& playedAt)
{
    json j;
    j["game_id"]   = gr.gameId;
    j["played_at"] = playedAt;
    std::vector<std::string> order;
    for (const auto& ts : gr.playerOrder)
        order.push_back(toFullId(ts, gr.playerTagToSlotId));
    j["player_order"]  = order;
    j["winner"]        = toFullId(gr.winner, gr.playerTagToSlotId);
    j["final_scores"]  = remapKeys(gr.finalScores, gr.playerTagToSlotId);
    j["rounds_played"] = gr.roundsPlayed;
    return j;
}

inline void writeLobbyGameResult(const std::filesystem::path& resultsDir,
                                 const GameResult& gr, const std::string& playedAt)
{
    namespace fs = std::filesystem;
    fs::path lobbyDir = resultsDir / "lobby";
    fs::path gamesDir = lobbyDir / "games";
    fs::create_directories(gamesDir);

    // Per-game detail file.
    {
        std::ofstream f(gamesDir / (gr.gameId + ".json"));
        f << compactHandArrays(gameResultToDetailJson(gr).dump(2));
    }

    // Append to the lobby index (guarded; games run concurrently).
    static std::mutex sIndexMutex;
    std::lock_guard<std::mutex> lock(sIndexMutex);
    fs::path idxPath = lobbyDir / "index.json";
    json arr = json::array();
    if (fs::exists(idxPath))
    {
        std::ifstream in(idxPath);
        try { in >> arr; } catch (...) { arr = json::array(); }
        if (!arr.is_array()) arr = json::array();
    }
    arr.push_back(gameResultToLobbyIndexEntry(gr, playedAt));
    std::ofstream out(idxPath);
    out << arr.dump(2);
}

} // namespace Common::Game
