/**
 * tournament_server — two-stage Hearts tournament binary.
 *
 * Usage:
 *   tournament_server <config_env> --start-at=<unix_timestamp>
 *
 * Config keys (in addition to standard SERVER_PORT / LOG_DIR):
 *   TOURNAMENT_PORT              port to listen on (overrides SERVER_PORT if present)
 *   QUALIFYING_GAMES             total games in stage 1
 *   FINALS_GAMES                 games in stage 2 (top-4 playoff)
 *   MAX_PLAYERS_PER_TEAM         must be a multiple of 4
 *   QUALIFYING_POINTS            comma-separated 1st,2nd,3rd,4th place points
 *   ALLOW_MULTI_TEAM_FINALS      0 or 1
 *   TEAMS                        name:password,name:password,...
 *   FALLBACK_PLAYER_TAG          player_tag of the always-available fallback client
 *   RESULTS_DIR                  directory for JSON result files
 */

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <filesystem>
#include <fstream>
#include <future>
#include <map>
#include <mutex>
#include <numeric>
#include <random>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include <sys/socket.h>
#include <boost/asio.hpp>
#include <nlohmann/json.hpp>

#include "server/api/managed_connection.h"
#include "server/api/game_session.h"
#include "server/game/game.h"
#include "server/game/game_observer.h"
#include "server/game/remote_player.h"
#include "server/util/assertions.h"
#include "server/util/constants.h"
#include "server/util/dates.h"
#include "server/util/env.h"
#include "server/util/logging.h"
#include "server/util/types.h"

using namespace boost::asio;
using namespace Common;
using namespace Common::Server;
using json = nlohmann::json;

// ─── Config ──────────────────────────────────────────────────────────────────

struct TournamentConfig {
    int port;
    int qualifyingGames;
    int finalsGames;
    int maxPlayersPerTeam;
    std::vector<int> qualifyingPoints; // [1st, 2nd, 3rd, 4th]
    bool allowMultiTeamFinals;
    std::map<std::string, std::string> teams; // name → password
    std::string fallbackPlayerTag;
    std::string resultsDir;
    int autoMoveAfterTimeouts; // consecutive receive timeouts before auto-move (0 = never)
    int64_t startAt; // unix timestamp
};

static TournamentConfig loadConfig(int64_t startAt)
{
    TournamentConfig cfg;
    cfg.startAt = startAt;

    // Port: TOURNAMENT_PORT takes precedence
    cfg.port = std::stoi(
        EnvLoader->has("TOURNAMENT_PORT") ? ENV_STRING("TOURNAMENT_PORT")
                                          : ENV_STRING("SERVER_PORT"));
    cfg.qualifyingGames    = std::stoi(ENV_STRING("QUALIFYING_GAMES"));
    cfg.finalsGames        = std::stoi(ENV_STRING("FINALS_GAMES"));
    cfg.maxPlayersPerTeam  = std::stoi(ENV_STRING("MAX_PLAYERS_PER_TEAM"));
    cfg.allowMultiTeamFinals = ENV_STRING("ALLOW_MULTI_TEAM_FINALS") == "1";
    cfg.fallbackPlayerTag  = ENV_STRING("FALLBACK_PLAYER_TAG");
    cfg.resultsDir         = ENV_STRING("RESULTS_DIR");
    cfg.autoMoveAfterTimeouts = EnvLoader->has("AUTO_MOVE_AFTER_TIMEOUTS")
        ? std::stoi(ENV_STRING("AUTO_MOVE_AFTER_TIMEOUTS")) : 2;

    // Qualifying points: "10,5,3,1"
    std::string pts = ENV_STRING("QUALIFYING_POINTS");
    std::stringstream ss(pts);
    std::string tok;
    while (std::getline(ss, tok, ','))
        cfg.qualifyingPoints.push_back(std::stoi(tok));
    ASRT_EQ((int)cfg.qualifyingPoints.size(), 4);

    // Teams: "alpha:pw1,beta:pw2"
    std::string teamsStr = ENV_STRING("TEAMS");
    std::stringstream ts(teamsStr);
    std::string entry;
    while (std::getline(ts, entry, ','))
    {
        auto colon = entry.find(':');
        if (colon != std::string::npos)
            cfg.teams[entry.substr(0, colon)] = entry.substr(colon + 1);
    }

    return cfg;
}

// ─── Registration ─────────────────────────────────────────────────────────────

struct RegisteredPlayer {
    std::string teamName;
    std::string playerTag;
    int priorityScore;
    std::shared_ptr<PlayerGameSession> controlSession;
    ManagedConnection* connection;
};

struct TournamentLobby {
    std::mutex mtx;
    std::vector<RegisteredPlayer> players;
    const TournamentConfig& cfg;
    std::atomic<PlayerGameSessionID> sessionCounter{1000};

    explicit TournamentLobby(const TournamentConfig& c) : cfg(c) {}

    // Returns session ID of the new control session, or 0 on auth failure.
    PlayerGameSessionID handleRegister(ManagedConnection& conn, const Message::Message& msg)
    {
        auto j = msg.getJson();
        std::string team     = j.value(Tags::Tournament::TEAM_NAME, "");
        std::string password = j.value(Tags::Tournament::PASSWORD, "");
        std::string tag      = j.value(Tags::PLAYER_TAG, "");
        int score            = j.value(Tags::Tournament::PRIORITY_SCORE, 0);

        auto it = cfg.teams.find(team);
        if (it == cfg.teams.end() || it->second != password)
        {
            const char* reason = (it == cfg.teams.end()) ? "unknown team" : "wrong password";
            LOG("Registration rejected (%s): '%s' from %s:%d",
                reason, team.c_str(), conn.clientIP(), conn.clientPort());
            // Close the socket so the client sees an immediate connection drop rather
            // than having to wait out a timeout before retrying.
            conn.shutdownSocket();
            return 0;
        }

        PlayerGameSessionID sid = sessionCounter.fetch_add(1);
        // starting_seq = 1 because client's register was seq 0
        auto session = std::make_shared<PlayerGameSession>(sid, PlayerTag(tag), conn, /*starting_seq=*/1);
        conn.addSession(sid);
        session->Setup(); // sends game_session_response with status:success reused as tournament_queued

        // Overwrite with proper tournament_queued message
        session->send({{
            {Tags::TYPE, ServerMsgTypes::Tournament::QUEUED},
            {Tags::Tournament::START_AT, cfg.startAt}
        }});

        std::lock_guard<std::mutex> lock(mtx);
        players.push_back({team, tag, score, session, &conn});
        LOG("Registered %s/%s/%lld — %s:%d (score=%d)",
            team.c_str(), tag.c_str(), (long long)sid,
            conn.clientIP(), conn.clientPort(), score);
        return sid;
    }

    bool isRegistrationMessage(const Message::Message& m)
    {
        return m.getJson().value(Tags::TYPE, "") == ClientMsgTypes::TOURNAMENT_REGISTER;
    }
};

// ─── Roster building ──────────────────────────────────────────────────────────

struct PlayerSlot {
    std::string teamName;
    std::string playerTag;
    int slotIndex; // which duplicate copy (0 = original)
    RegisteredPlayer* source; // nullptr for fallback slots
    std::string slotId; // stable unique id: "teamName/playerTag/slotIndex"
};

static std::vector<PlayerSlot> buildRoster(
    const std::string& teamName,
    std::vector<RegisteredPlayer*>& teamPlayers,
    int maxPlayers,
    RegisteredPlayer* fallback)
{
    // Sort descending by priority score
    std::sort(teamPlayers.begin(), teamPlayers.end(),
        [](RegisteredPlayer* a, RegisteredPlayer* b){ return a->priorityScore > b->priorityScore; });

    auto makeSlot = [&](const std::string& tag, int idx, RegisteredPlayer* src) -> PlayerSlot {
        return {teamName, tag, idx, src, teamName + "/" + tag + "/" + std::to_string(idx)};
    };

    int n = (int)teamPlayers.size();
    if (n == 0)
    {
        std::vector<PlayerSlot> slots;
        std::string tag = fallback ? fallback->playerTag : "fallback";
        for (int i = 0; i < maxPlayers; i++)
            slots.push_back(makeSlot(tag, i, fallback));
        return slots;
    }

    // Trim to maxPlayers if needed (lowest-scored are excluded)
    if (n > maxPlayers)
    {
        teamPlayers.resize(maxPlayers);
        n = maxPlayers;
    }

    // Distribute copies: each player gets base copies; extras go greedily to the
    // highest-scored players. Within a tied score group the extras are shared evenly
    // (floor per player), with any remainder going to the first in the group.
    std::vector<int> copies(n, maxPlayers / n);
    int extras = maxPlayers % n;
    int i = 0;
    while (extras > 0 && i < n)
    {
        int j = i;
        while (j < n && teamPlayers[j]->priorityScore == teamPlayers[i]->priorityScore)
            ++j;
        int groupSize = j - i;
        int perPlayer = extras / groupSize;
        int remainder = extras % groupSize;
        for (int k = i; k < j; ++k)
            copies[k] += perPlayer;
        copies[i] += remainder;
        extras = 0; // entire extras batch consumed by this group
        i = j;
    }

    std::vector<PlayerSlot> slots;
    int slotIdx = 0;
    for (int p = 0; p < n; ++p)
        for (int c = 0; c < copies[p]; ++c)
            slots.push_back(makeSlot(teamPlayers[p]->playerTag, slotIdx++, teamPlayers[p]));
    return slots;
}

// ─── Scheduling algorithm ─────────────────────────────────────────────────────

struct GameAssignment {
    std::string gameId;
    std::string stage;
    std::vector<PlayerSlot*> players; // exactly 4
};

static std::vector<GameAssignment> scheduleGames(
    std::map<std::string, std::vector<PlayerSlot>>& teamRosters,
    int numGames,
    const std::string& stage)
{
    std::mt19937 rng{std::random_device{}()};

    // Collect team names and shuffle once (order fixed for the whole stage)
    std::vector<std::string> teamNames;
    for (auto& [name, _] : teamRosters) teamNames.push_back(name);
    std::shuffle(teamNames.begin(), teamNames.end(), rng);

    int numTeams = (int)teamNames.size();

    // Per-team 3-array state:
    //   available — players ready to be picked (array 1)
    //   resting   — players who have recently played (array 3)
    //   array 2 is the transient "chosen for this game" vector
    struct TeamState {
        std::vector<PlayerSlot*> available;
        std::vector<PlayerSlot*> resting;
    };
    std::map<std::string, TeamState> states;
    for (auto& name : teamNames)
    {
        TeamState st;
        for (auto& slot : teamRosters[name]) st.available.push_back(&slot);
        std::shuffle(st.available.begin(), st.available.end(), rng);
        states[name] = std::move(st);
    }

    std::vector<GameAssignment> assignments;
    assignments.reserve(numGames);

    for (int g = 0; g < numGames; g++)
    {
        GameAssignment game;
        game.gameId = stage + "_" + std::to_string(g + 1);
        game.stage  = stage;

        // Pick 4 teams for this game (rotating through the shuffled list)
        std::vector<std::string> gameTeams;
        for (int t = 0; t < 4; t++)
            gameTeams.push_back(teamNames[(g * 4 + t) % numTeams]);

        // For each team pick one player using the 3-array algorithm.
        // Track per-team whether it had to refresh this game.
        std::vector<bool> teamRefreshed(4, false);
        std::vector<PlayerSlot*> chosen(4, nullptr);

        for (int t = 0; t < 4; t++)
        {
            auto& st = states[gameTeams[t]];
            if (st.available.empty())
            {
                // Array 1 exhausted: move array 3 → array 1 (shuffle)
                st.available = st.resting;
                st.resting.clear();
                std::shuffle(st.available.begin(), st.available.end(), rng);
                teamRefreshed[t] = true;
            }
            std::uniform_int_distribution<int> dist(0, (int)st.available.size() - 1);
            int idx = dist(rng);
            chosen[t] = st.available[idx];
            st.available.erase(st.available.begin() + idx);
        }

        game.players = chosen;
        assignments.push_back(game);

        // Post-game: move each chosen player to the right array.
        //   Normal:    chosen → array 3 (resting), will be cycled back later.
        //   Refreshed: chosen → array 1 (available) at a random position >= min(4, size),
        //              so it won't be selected again immediately.
        for (int t = 0; t < 4; t++)
        {
            auto& st = states[gameTeams[t]];
            if (!teamRefreshed[t])
            {
                st.resting.push_back(chosen[t]);
            }
            else
            {
                int minPos = std::min(4, (int)st.available.size());
                std::uniform_int_distribution<int> posDist(minPos, (int)st.available.size());
                st.available.insert(st.available.begin() + posDist(rng), chosen[t]);
            }
        }
    }

    return assignments;
}

// ─── Game result collection ───────────────────────────────────────────────────

struct TrickRecord {
    std::string firstPlayer;
    std::vector<std::string> playerTags; // play order (playerTags[i] played cards[i])
    std::vector<std::string> cards;
    std::string winner;
    int points;
};

struct RoundRecord {
    int roundIdx;
    std::string passDir;
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
    std::vector<RoundRecord> rounds;

    // Placement points awarded in qualifying
    std::map<std::string, int> placementPoints;

    // Maps "playerTag(sessionId)" → slotId for score aggregation
    std::map<std::string, std::string> playerTagToSlotId;
};

class RecordingObserver : public Game::GameObserver {
public:
    GameResult result;

    explicit RecordingObserver(const std::string& gameId, const std::string& stage)
    {
        result.gameId = gameId;
        result.stage  = stage;
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

    void onTrickComplete(const std::vector<std::string>& playerOrder,
                          const std::vector<std::string>& cards,
                          const std::string& winner, int points) override
    {
        std::string firstPlayer = playerOrder.empty() ? "" : playerOrder[0];
        if (!result.rounds.empty())
            result.rounds.back().tricks.push_back({firstPlayer, playerOrder, cards, winner, points});
    }

    void onRoundComplete(int /*roundIdx*/, const std::map<std::string, int>& scores) override
    {
        result.roundsPlayed++;
        if (!result.rounds.empty())
            result.rounds.back().roundScores = scores;
    }

    void onMove(const std::string& playerTag, long latencyMs, bool autoMoved) override
    {
        result.totalMoveLatencyMs[playerTag] += latencyMs;
        if (autoMoved)
            result.autoMoveCount[playerTag]++;
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
        // playerOrder is populated with the actual seating order in runOneGame.
    }
};

// ─── Result JSON writing ──────────────────────────────────────────────────────

// Standard player ID format: team/player_tag/slot/session_id
// Truncated from the right when components are unavailable.
//
// toFullId: converts "playerTag(sessionId)" → "team/player_tag/slot/session_id"
//   using the tagToSlotId map (which carries the team/player_tag/slot part).
static std::string toFullId(const std::string& playerTagSession,
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
static json remapKeys(const std::map<std::string, V>& m,
                      const std::map<std::string, std::string>& tagToSlotId)
{
    json j = json::object();
    for (const auto& [k, v] : m)
        j[toFullId(k, tagToSlotId)] = v;
    return j;
}

static json gameResultToSummaryJson(const GameResult& gr)
{
    json j;
    j["game_id"]   = gr.gameId;
    j["stage"]     = gr.stage;
    j["winner"]                = toFullId(gr.winner,              gr.playerTagToSlotId);
    j["rounds_played"]         = gr.roundsPlayed;
    j["moon_shots"]            = remapKeys(gr.moonShots,          gr.playerTagToSlotId);
    j["total_move_latency_ms"] = remapKeys(gr.totalMoveLatencyMs, gr.playerTagToSlotId);
    j["auto_move_count"]       = remapKeys(gr.autoMoveCount,      gr.playerTagToSlotId);
    j["detail_file"]           = "games/" + gr.gameId + ".json";

    // Players ordered by game score ascending (lowest = winner in Hearts).
    std::vector<std::pair<std::string, int>> ranked(gr.finalScores.begin(), gr.finalScores.end());
    std::sort(ranked.begin(), ranked.end(), [](const auto& a, const auto& b){
        return a.second < b.second;
    });
    json players = json::array();
    for (auto& [tagSession, score] : ranked)
    {
        std::string fullId_ = toFullId(tagSession, gr.playerTagToSlotId);
        std::string slotId  = gr.playerTagToSlotId.count(tagSession)
            ? gr.playerTagToSlotId.at(tagSession) : tagSession;
        int pts = gr.placementPoints.count(slotId) ? gr.placementPoints.at(slotId) : 0;
        json entry;
        entry[fullId_] = {{"game_score", score}, {"tournament_points", pts}};
        players.push_back(entry);
    }
    j["players"] = players;
    return j;
}

static json gameResultToDetailJson(const GameResult& gr)
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
        rj["hands_after_passing"] = remapKeys(r.handsAfterPass, gr.playerTagToSlotId);

        json tricks = json::array();
        for (const auto& t : r.tricks)
        {
            json tj;
            tj["first_player"] = toFullId(t.firstPlayer, gr.playerTagToSlotId);
            tj["moves"]        = t.cards; // in play order starting from first_player
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
static std::string compactHandArrays(const std::string& raw)
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

static void writeResults(
    const std::string& resultsDir,
    const std::string& tournamentId,
    const std::vector<GameResult>& qualifying,
    const std::vector<GameResult>& finals,
    const std::map<std::string, int>& qualTotals,
    const std::map<std::string, int>& finalTotals)
{
    namespace fs = std::filesystem;
    fs::path tDir = fs::path(resultsDir) / tournamentId;
    fs::path gDir = tDir / "games";
    fs::create_directories(gDir);

    // Per-game detail files
    auto writeGame = [&](const GameResult& gr) {
        std::ofstream f(gDir / (gr.gameId + ".json"));
        f << compactHandArrays(gameResultToDetailJson(gr).dump(2));
    };
    for (const auto& g : qualifying) writeGame(g);
    for (const auto& g : finals)     writeGame(g);

    // Summary
    json summary;
    summary["tournament_id"] = tournamentId;
    json q = json::array(), fn = json::array();
    for (const auto& g : qualifying) q.push_back(gameResultToSummaryJson(g));
    for (const auto& g : finals)     fn.push_back(gameResultToSummaryJson(g));
    summary["qualifying"]       = q;
    summary["finals"]           = fn;
    summary["qualifying_totals"] = qualTotals;
    summary["finals_totals"]    = finalTotals;

    std::ofstream sf(tDir / "summary.json");
    sf << summary.dump(2);

    // Append to competition index
    fs::path idxPath = fs::path(resultsDir) / "competition.json";
    json idx = json::array();
    if (fs::exists(idxPath)) {
        std::ifstream f(idxPath);
        try { f >> idx; } catch(...) {}
    }
    json entry;
    entry["tournament_id"] = tournamentId;
    entry["summary"]       = tournamentId + "/summary.json";
    idx.push_back(entry);
    std::ofstream idxOut(idxPath);
    idxOut << idx.dump(2);

    LOG("Results written to %s/%s", resultsDir.c_str(), tournamentId.c_str());
}

// ─── Running one game ─────────────────────────────────────────────────────────

static std::atomic<PlayerGameSessionID> gameSessionCounter{100000};

static GameResult runOneGame(
    const GameAssignment& assignment,
    const std::string& resultsDir,
    std::atomic<PlayerGameSessionID>& sessionCounter,
    const std::shared_ptr<Common::GameLogger>& nullLogger,
    int autoMoveAfterTimeouts = 2)
{
    auto observer = std::make_shared<RecordingObserver>(assignment.gameId, assignment.stage);

    // Create a game session per player-slot
    std::vector<std::shared_ptr<PlayerGameSession>> sessions;
    std::vector<Game::PlayerRef> players;

    for (auto* slot : assignment.players)
    {
        if (slot->source == nullptr)
        {
            LOG("Slot %s has no source player — skipping game %s",
                slot->slotId.c_str(), assignment.gameId.c_str());
            observer->result.winner = "no_players";
            return observer->result;
        }

        PlayerGameSessionID sid = sessionCounter.fetch_add(1);
        // Use the plain playerTag (not slotId) so the client can match itself in player_order.
        // starting_seq=0: server sends start_game as very first message
        auto session = std::make_shared<PlayerGameSession>(
            sid, PlayerTag(slot->playerTag), *slot->source->connection, /*starting_seq=*/0);
        slot->source->connection->addSession(sid, autoMoveAfterTimeouts);

        // Record playerTagSession → slotId so tabulation can aggregate by slot across games.
        std::string tagSession = slot->playerTag + "(" + std::to_string(sid) + ")";
        observer->result.playerTagToSlotId[tagSession] = slot->slotId;
        observer->result.playerOrder.push_back(tagSession); // actual seating order

        slot->source->controlSession->send({{
            {Tags::TYPE,                        ServerMsgTypes::Tournament::GAME_ASSIGNMENT},
            {Tags::Tournament::GAME_SESSION_ID, (long long)sid},
            {Tags::Tournament::GAME_ID,         assignment.gameId},
            {Tags::Tournament::STAGE,           assignment.stage}
        }});

        sessions.push_back(session);
        players.push_back(std::make_shared<RemotePlayer>(
            session->getPlayerTagSession(), session));
    }

    ASRT_EQ((int)players.size(), 4);

    Game::PlayerArray arr = {players[0], players[1], players[2], players[3]};
    Game::Game game(arr, nullLogger, observer.get());
    try {
        game.runGame();
    } catch (boost::system::system_error& e) {
        LOG("Game %s terminated early (network error): %s", assignment.gameId.c_str(), e.what());
    } catch (std::exception& e) {
        LOG("Game %s terminated early: %s", assignment.gameId.c_str(), e.what());
    }

    observer->result.roundsPlayed = game.getRoundsPlayed();
    return observer->result;
}

// ─── Tabulation ──────────────────────────────────────────────────────────────

static std::map<std::string, int> tabulateQualifyingPoints(
    std::vector<GameResult>& games,
    const std::vector<int>& pointTable)
{
    std::map<std::string, int> totals;
    for (auto& gr : games)
    {
        // Sort players by score ascending (lowest = best in Hearts)
        std::vector<std::pair<std::string, int>> ranked(gr.finalScores.begin(), gr.finalScores.end());
        std::sort(ranked.begin(), ranked.end(), [](const auto& a, const auto& b){
            return a.second < b.second;
        });
        for (int place = 0; place < (int)ranked.size() && place < (int)pointTable.size(); place++)
        {
            const auto& tagSession = ranked[place].first; // "playerTag(sessionId)"
            // Map to the stable slotId for cross-game aggregation
            std::string slotId = gr.playerTagToSlotId.count(tagSession)
                ? gr.playerTagToSlotId.at(tagSession)
                : tagSession; // fallback: use raw key
            int pts = pointTable[place];
            gr.placementPoints[slotId] = pts;
            totals[slotId] += pts;
        }
    }
    return totals;
}

static std::vector<std::string> selectFinalists(
    const std::map<std::string, int>& qualTotals,
    bool allowMultiTeam)
{
    // qualTotals keys are slotIds: "teamName/playerTag/slotIndex"
    // Extract team from the prefix before the first '/'.
    auto teamOf = [](const std::string& slotId) {
        auto pos = slotId.find('/');
        return pos == std::string::npos ? slotId : slotId.substr(0, pos);
    };

    std::vector<std::pair<std::string, int>> ranked(qualTotals.begin(), qualTotals.end());
    std::sort(ranked.begin(), ranked.end(), [](const auto& a, const auto& b){
        return a.second > b.second;
    });

    std::vector<std::string> finalists;
    std::set<std::string> usedTeams;
    for (const auto& [slotId, pts] : ranked)
    {
        if ((int)finalists.size() >= 4) break;
        std::string team = teamOf(slotId);
        if (!allowMultiTeam && usedTeams.count(team)) continue;
        finalists.push_back(slotId);
        usedTeams.insert(team);
    }
    // Pad with top remaining if not enough (e.g. allowMultiTeam=false but <4 teams)
    if ((int)finalists.size() < 4)
    {
        for (const auto& [slotId, pts] : ranked)
        {
            if ((int)finalists.size() >= 4) break;
            if (std::find(finalists.begin(), finalists.end(), slotId) == finalists.end())
                finalists.push_back(slotId);
        }
    }
    return finalists;
}

// ─── Main ────────────────────────────────────────────────────────────────────

int main(int argc, char** argv)
{
    ASRT(argc >= 2, "Usage: tournament_server <config_env> [--start-at=<unix_ts>]");
    EnvLoader = EnvironmentLoader(argv[1]);

    int64_t startAt = 0;
    for (int i = 2; i < argc; i++)
    {
        std::string arg = argv[i];
        if (arg.substr(0, 11) == "--start-at=")
            startAt = std::stoll(arg.substr(11));
    }
    if (startAt == 0)
        startAt = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now()) + 30;

    TournamentConfig cfg = loadConfig(startAt);
    std::string tournamentId = Common::Dates::GetStrDate('-') + "_" + Common::Dates::GetStrTime('-');

    LOG("Tournament server starting on port %d, tournament starts at %lld", cfg.port, startAt);

    // ── Registration phase ──────────────────────────────────────────────────

    TournamentLobby lobby(cfg);

    io_context ioContext;
    ip::tcp::endpoint endpoint(ip::tcp::v4(), cfg.port);

    // Open acceptor manually so we can set SO_REUSEPORT before binding.
    // SO_REUSEADDR is set automatically by the acceptor constructor; SO_REUSEPORT
    // (macOS/Linux) lets the next tournament bind the same port immediately even if
    // the previous process's socket is still in TIME_WAIT.
    ip::tcp::acceptor acceptor(ioContext);
    acceptor.open(ip::tcp::v4());
    acceptor.set_option(ip::tcp::acceptor::reuse_address(true));
#ifdef SO_REUSEPORT
    {
        int optval = 1;
        ::setsockopt(acceptor.native_handle(), SOL_SOCKET, SO_REUSEPORT,
                     &optval, sizeof(optval));
    }
#endif
    acceptor.bind(endpoint);
    acceptor.listen();

    std::vector<std::unique_ptr<ManagedConnection>> connections;
    std::vector<std::thread> listenerThreads; // kept joinable so we can clean up cleanly
    std::mutex connMtx;

    // Accept connections until start_at.
    std::thread acceptThread([&]() {
        while (true)
        {
            int64_t now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
            if (now >= startAt) break;
            try
            {
                SocketPtr socket = std::make_shared<ip::tcp::socket>(ioContext);
                acceptor.accept(*socket);
                std::lock_guard<std::mutex> lock(connMtx);
                connections.emplace_back(std::make_unique<ManagedConnection>(socket));
                auto* conn_ptr = connections.back().get(); // raw ptr survives vector reallocation
                if (conn_ptr->isConnected()) // skip probe connections that disconnected during handshake
                {
                    listenerThreads.emplace_back([conn_ptr, &lobby]() {
                        conn_ptr->ConnectionListener(
                            [&lobby](ManagedConnection& mc, Message::Message msg) -> PlayerGameSessionID {
                                return lobby.handleRegister(mc, msg);
                            },
                            [](const Message::Message& m) {
                                return m.getJson().value(Tags::TYPE, "") == ClientMsgTypes::TOURNAMENT_REGISTER;
                            });
                    });
                }
            }
            catch (...) { break; }
        }
    });

    // Wait until start_at.
    {
        int64_t now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
        if (now < startAt)
        {
            LOG("Waiting %lld seconds for clients to connect...", startAt - now);
            std::this_thread::sleep_for(std::chrono::seconds(startAt - now));
        }
    }
    // Close the acceptor to unblock any pending synchronous accept() in the thread.
    try { acceptor.close(); } catch (...) {}
    ioContext.stop();
    acceptThread.join();

    LOG("Tournament starting. %d players registered.", (int)lobby.players.size());

    // ── Build rosters ───────────────────────────────────────────────────────

    // Find fallback player
    RegisteredPlayer* fallback = nullptr;
    for (auto& p : lobby.players)
        if (p.playerTag == cfg.fallbackPlayerTag) { fallback = &p; break; }

    // Group by team
    std::map<std::string, std::vector<RegisteredPlayer*>> byTeam;
    for (auto& p : lobby.players)
        byTeam[p.teamName].push_back(&p);

    std::map<std::string, std::vector<PlayerSlot>> teamRosters;
    for (auto& [name, _] : cfg.teams)
    {
        // If fallback is disabled ("none") and the team submitted no players, exclude them entirely.
        if (byTeam[name].empty() && cfg.fallbackPlayerTag == "none") continue;
        teamRosters[name] = buildRoster(name, byTeam[name], cfg.maxPlayersPerTeam, fallback);
    }

    // Validate qualifying game count
    int totalPlayers = 0;
    for (auto& [_, slots] : teamRosters) totalPlayers += (int)slots.size();
    int required = totalPlayers / 4;
    if (cfg.qualifyingGames % required != 0)
    {
        int rounded = ((cfg.qualifyingGames + required - 1) / required) * required;
        LOG("Rounding qualifying games from %d to %d (multiple of %d)", cfg.qualifyingGames, rounded, required);
        cfg.qualifyingGames = rounded;
    }

    // Detailed roster log — one line per slot, grouped by team.
    LOG("Tournament roster — %d teams, %d slots, %d qualifying games:",
        (int)teamRosters.size(), totalPlayers, cfg.qualifyingGames);
    for (const auto& [teamName, slots] : teamRosters)
    {
        bool hasRealPlayers = !byTeam[teamName].empty();
        if (hasRealPlayers)
            LOG("  %s (%d slot%s):", teamName.c_str(), (int)slots.size(), (int)slots.size() == 1 ? "" : "s");
        else
            LOG("  %s (%d slot%s) [autofilled with '%s' — submitted no players]:",
                teamName.c_str(), (int)slots.size(), (int)slots.size() == 1 ? "" : "s",
                fallback ? fallback->playerTag.c_str() : "?");
        for (const auto& slot : slots)
        {
            long long sessId = (slot.source && slot.source->controlSession)
                ? (long long)slot.source->controlSession->getGameSessionID() : 0;
            LOG("    %s  sess=%lld", slot.slotId.c_str(), sessId);
        }
    }

    // Shared null logger (game events captured by observer, not log files)
    std::filesystem::create_directories(cfg.resultsDir);
    auto nullLogger = std::make_shared<GameLogger>(stdout);

    // ── Stage 1: Qualifying ─────────────────────────────────────────────────

    auto qAssignments = scheduleGames(teamRosters, cfg.qualifyingGames, "qualifying");

    std::vector<std::future<GameResult>> qFutures;
    qFutures.reserve(qAssignments.size());
    for (const auto& a : qAssignments)
        qFutures.push_back(std::async(std::launch::async, runOneGame,
            std::cref(a), std::cref(cfg.resultsDir), std::ref(gameSessionCounter),
            nullLogger, cfg.autoMoveAfterTimeouts));
    std::vector<GameResult> qualifyingResults;
    qualifyingResults.reserve(qFutures.size());
    for (auto& f : qFutures)
        qualifyingResults.push_back(f.get());

    LOG("Qualifying complete. Tabulating scores...");

    auto qualTotals = tabulateQualifyingPoints(qualifyingResults, cfg.qualifyingPoints);

    // Notify all clients of stage completion
    {
        json stageResult;
        for (const auto& [player, pts] : qualTotals)
            stageResult[player] = pts;
        std::lock_guard<std::mutex> lock(lobby.mtx);
        for (auto& rp : lobby.players)
        {
            rp.controlSession->send({{
                {Tags::TYPE, ServerMsgTypes::Tournament::STAGE_COMPLETE},
                {"stage", "qualifying"},
                {Tags::Tournament::RESULTS, stageResult}
            }});
        }
    }

    // ── Stage 2: Finals ─────────────────────────────────────────────────────

    // Build slotId → RegisteredPlayer* map from the qualifying rosters
    std::map<std::string, RegisteredPlayer*> slotIdToPlayer;
    for (auto& [teamName, slots] : teamRosters)
        for (auto& slot : slots)
            slotIdToPlayer[slot.slotId] = slot.source;

    auto finalistTags = selectFinalists(qualTotals, cfg.allowMultiTeamFinals);
    LOG("Finalists: %s, %s, %s, %s",
        finalistTags[0].c_str(), finalistTags[1].c_str(),
        finalistTags[2].c_str(), finalistTags[3].c_str());

    std::map<std::string, std::vector<PlayerSlot>> finalsRosters;
    for (int i = 0; i < 4; i++)
    {
        const auto& qualSlotId = finalistTags[i]; // "teamName/playerTag/slotIndex"
        // Each finalist needs a unique key in finalsRosters so the scheduling algorithm
        // treats them as separate teams (even if two finalists share an original team).
        std::string schedKey = "finals_seat_" + std::to_string(i);

        // Extract the original playerTag from the qualifying slotId so game sessions
        // use the same tag the client registered with (required for client assertions).
        // slotId format: "teamName/playerTag/slotIndex"
        auto firstSlash = qualSlotId.find('/');
        auto lastSlash  = qualSlotId.rfind('/');
        std::string origPlayerTag = (firstSlash != std::string::npos && lastSlash != firstSlash)
            ? qualSlotId.substr(firstSlash + 1, lastSlash - firstSlash - 1)
            : qualSlotId;

        PlayerSlot slot;
        slot.teamName  = schedKey;      // only used as map key for scheduling
        slot.playerTag = origPlayerTag; // must match the client's registered player_tag
        slot.slotIndex = 0;
        slot.slotId    = qualSlotId;    // preserve qualifying identity in all output JSON
        slot.source    = slotIdToPlayer.count(qualSlotId) ? slotIdToPlayer.at(qualSlotId) : fallback;
        finalsRosters[schedKey] = {slot};
    }

    auto fAssignments = scheduleGames(finalsRosters, cfg.finalsGames, "finals");
    std::vector<std::future<GameResult>> fFutures;
    fFutures.reserve(fAssignments.size());
    for (const auto& a : fAssignments)
        fFutures.push_back(std::async(std::launch::async, runOneGame,
            std::cref(a), std::cref(cfg.resultsDir), std::ref(gameSessionCounter),
            nullLogger, cfg.autoMoveAfterTimeouts));
    std::vector<GameResult> finalsResults;
    finalsResults.reserve(fFutures.size());
    for (auto& f : fFutures)
        finalsResults.push_back(f.get());

    LOG("Finals complete.");

    // ── Notify clients and write results ────────────────────────────────────

    // Finals use the same point table as qualifying; winner = most finals points.
    auto finalTotals = tabulateQualifyingPoints(finalsResults, cfg.qualifyingPoints);

    {
        json completeMsg;
        completeMsg["qualifying_totals"] = qualTotals;
        completeMsg["finals_totals"]     = finalTotals;

        std::lock_guard<std::mutex> lock(lobby.mtx);
        for (auto& rp : lobby.players)
        {
            rp.controlSession->send({{
                {Tags::TYPE, ServerMsgTypes::Tournament::COMPLETE},
                {Tags::Tournament::RESULTS, completeMsg}
            }});
        }
    }

    writeResults(cfg.resultsDir, tournamentId, qualifyingResults, finalsResults, qualTotals, finalTotals);

    LOG("Tournament %s complete.", tournamentId.c_str());

    // Shut down sockets first — this unblocks ConnectionListener threads (they get
    // a socket error and exit their loops).  Join after so no thread accesses a
    // destroyed ManagedConnection object.  Destroy connections last.
    for (auto& conn : connections)
        conn->shutdownSocket();
    for (auto& t : listenerThreads)
        if (t.joinable()) t.join();
    connections.clear();

    return 0;
}
