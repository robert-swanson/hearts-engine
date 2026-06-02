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
#include <functional>
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
#include "server/game/game_recorder.h"
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

// Game-recording machinery shared with the regular (lobby) server.
using Common::Game::TrickRecord;
using Common::Game::RoundRecord;
using Common::Game::GameResult;
using Common::Game::RecordingObserver;
using Common::Game::toFullId;
using Common::Game::remapKeys;
using Common::Game::gameResultToDetailJson;
using Common::Game::compactHandArrays;

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
    int autoMoveAfterTimeouts;            // consecutive receive timeouts before auto-move (0 = never)
    int moveTimeoutMs;                    // ms to wait for a client move before counting a timeout
    int maxConcurrentGamesPerTeam;        // 0 = unlimited
    int gameParallelism;                  // worker threads running games at once (0 = auto)
    int64_t startAt;                      // unix timestamp
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
    cfg.moveTimeoutMs = EnvLoader->has("MOVE_TIMEOUT_MS")
        ? std::stoi(ENV_STRING("MOVE_TIMEOUT_MS")) : 15000;
    cfg.maxConcurrentGamesPerTeam = EnvLoader->has("MAX_CONCURRENT_GAMES_PER_TEAM")
        ? std::stoi(ENV_STRING("MAX_CONCURRENT_GAMES_PER_TEAM")) : 0;
    // Number of games to run in parallel. Games are I/O-bound (each move is a
    // network round-trip to a remote client), so the sweet spot is well above
    // the core count. 0 => pick a sensible default from hardware concurrency.
    cfg.gameParallelism = EnvLoader->has("GAME_PARALLELISM")
        ? std::stoi(ENV_STRING("GAME_PARALLELISM")) : 0;

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

static int64_t nowUnix()
{
    return std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
}

// Publish the live registration/countdown status the web UI polls. Written to
// <resultsDir>/<competitionId>/live.json (or <resultsDir>/live.json in the legacy
// flat layout). `state` is "registering" while the window is open and "running"
// once it closes; the frontend derives a countdown from `startAt`.
static void writeLiveStatus(
    const std::string& resultsDir, const std::string& competitionId,
    const std::string& tournamentIndex, const std::string& state, int64_t startAt,
    const std::vector<std::pair<std::string, std::string>>& registered)
{
    try
    {
        namespace fs = std::filesystem;
        fs::path dir = competitionId.empty() ? fs::path(resultsDir)
                                             : fs::path(resultsDir) / competitionId;
        fs::create_directories(dir);

        nlohmann::json j;
        j["competition_id"]   = competitionId;
        j["tournament_index"] = tournamentIndex;
        j["state"]            = state;
        j["start_at"]         = startAt;
        j["updated_at"]       = nowUnix();
        nlohmann::json arr = nlohmann::json::array();
        for (const auto& [team, tag] : registered)
            arr.push_back({{"team", team}, {"tag", tag}});
        j["registered"] = arr;

        // Write to a temp file then rename so a polling reader never sees a partial file.
        fs::path tmp = dir / "live.json.tmp";
        { std::ofstream out(tmp); out << j.dump(); }
        fs::rename(tmp, dir / "live.json");
    }
    catch (const std::exception& e)
    {
        LOG("Could not write live status: %s", e.what());
    }
}

struct RegisteredPlayer {
    std::string teamName;
    std::string playerTag;
    int priorityScore;
    std::shared_ptr<PlayerGameSession> controlSession;
    ManagedConnection* connection;
    int64_t lastSeen;   // unix ts of last register/heartbeat; drives the 15s timeout
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
        players.push_back({team, tag, score, session, &conn, nowUnix()});
        LOG("Registered %s/%s/%lld — %s:%d (score=%d)",
            team.c_str(), tag.c_str(), (long long)sid,
            conn.clientIP(), conn.clientPort(), score);
        return sid;
    }

    // A queued client sends these periodically; refresh its liveness timestamp so
    // the reaper doesn't drop it. Matched by (team, tag) — the same identity the
    // client registered with.
    void handleHeartbeat(const Message::Message& msg)
    {
        auto j = msg.getJson();
        std::string team = j.value(Tags::Tournament::TEAM_NAME, "");
        std::string tag  = j.value(Tags::PLAYER_TAG, "");
        int64_t now = nowUnix();
        std::lock_guard<std::mutex> lock(mtx);
        for (auto& p : players)
            if (p.teamName == team && p.playerTag == tag)
                p.lastSeen = now;
    }

    // Single entry point for the connection listener: dispatches register vs
    // heartbeat. Returns the new control-session id for a registration, or 0 for a
    // heartbeat / auth failure (no session created).
    PlayerGameSessionID handleLobbyMessage(ManagedConnection& conn, const Message::Message& msg)
    {
        if (msg.getJson().value(Tags::TYPE, "") == ClientMsgTypes::TOURNAMENT_HEARTBEAT)
        {
            handleHeartbeat(msg);
            return 0;
        }
        return handleRegister(conn, msg);
    }

    bool isLobbyMessage(const Message::Message& m)
    {
        auto t = m.getJson().value(Tags::TYPE, "");
        return t == ClientMsgTypes::TOURNAMENT_REGISTER
            || t == ClientMsgTypes::TOURNAMENT_HEARTBEAT;
    }

    // Drop players whose client has disconnected or has not sent a heartbeat within
    // `timeoutSec`. Returns the number removed.
    int pruneDeadPlayers(int64_t timeoutSec)
    {
        int64_t now = nowUnix();
        std::lock_guard<std::mutex> lock(mtx);
        size_t before = players.size();
        players.erase(std::remove_if(players.begin(), players.end(),
            [&](RegisteredPlayer& p) {
                bool disconnected = p.connection->anySessionDisconnected();
                bool timedOut = (now - p.lastSeen) > timeoutSec;
                if (disconnected || timedOut)
                    LOG("Unregistered %s/%s (%s)", p.teamName.c_str(), p.playerTag.c_str(),
                        disconnected ? "disconnected" : "heartbeat timeout");
                return disconnected || timedOut;
            }), players.end());
        return (int)(before - players.size());
    }

    // (team, tag) of every currently-registered player, for the live status feed.
    std::vector<std::pair<std::string, std::string>> snapshotRegistered()
    {
        std::lock_guard<std::mutex> lock(mtx);
        std::vector<std::pair<std::string, std::string>> out;
        out.reserve(players.size());
        for (auto& p : players)
            out.emplace_back(p.teamName, p.playerTag);
        return out;
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

    // Per-team round-robin queue. Fairness guarantee (see issue #69): every slot
    // on a team must play the *exact* same number of games. The team-rotation
    // below ((4g+t) % numTeams) walks the consecutive integers 0..4*numGames-1,
    // so when numTeams divides 4*numGames — which the qualifying-game count is
    // rounded up to ensure — each team is selected exactly the same number of
    // times, M. Because every team has the same roster size R (buildRoster pads
    // to MAX_PLAYERS_PER_TEAM) and R divides M, draining each team's queue in
    // full R-slot cycles (reshuffled per cycle for random combinations) hands
    // every slot exactly M/R games. No slot can be over- or under-played.
    struct TeamState {
        std::vector<PlayerSlot*> roster;  // all slots, fixed for the whole stage
        std::vector<PlayerSlot*> queue;   // slots not yet used in the current cycle
    };
    std::map<std::string, TeamState> states;
    for (auto& name : teamNames)
    {
        TeamState st;
        for (auto& slot : teamRosters[name]) st.roster.push_back(&slot);
        states[name] = std::move(st);
    }

    // Hand out the next slot for a team, reshuffling a fresh cycle when the
    // current one is exhausted. One slot per (team, cycle) ⇒ equal play.
    auto nextSlot = [&](TeamState& st) -> PlayerSlot* {
        if (st.queue.empty())
        {
            st.queue = st.roster;
            std::shuffle(st.queue.begin(), st.queue.end(), rng);
        }
        PlayerSlot* p = st.queue.back();
        st.queue.pop_back();
        return p;
    };

    std::vector<GameAssignment> assignments;
    assignments.reserve(numGames);

    for (int g = 0; g < numGames; g++)
    {
        GameAssignment game;
        game.gameId = stage + "_" + std::to_string(g + 1);
        game.stage  = stage;

        // Pick 4 teams for this game (rotating through the shuffled list). With
        // numTeams >= 4 these four consecutive residues are always distinct, so
        // no team faces itself and each team's slots only meet other teams.
        std::vector<PlayerSlot*> chosen(4, nullptr);
        for (int t = 0; t < 4; t++)
        {
            const std::string& team = teamNames[(g * 4 + t) % numTeams];
            chosen[t] = nextSlot(states[team]);
        }

        // Randomize seating per game: the 4 players sit in a random order at the
        // table (and that order then persists across all rounds of the game, since
        // runOneGame builds the seating once from game.players).
        std::shuffle(chosen.begin(), chosen.end(), rng);
        game.players = std::move(chosen);
        assignments.push_back(std::move(game));
    }

    return assignments;
}

// ─── Result JSON writing ──────────────────────────────────────────────────────
//
// The GameResult struct, RecordingObserver, toFullId, remapKeys,
// gameResultToDetailJson and compactHandArrays now live in the shared header
// server/game/game_recorder.h (imported via the using-declarations above). Only
// the tournament-specific summary JSON (placement points, stage, latency stats)
// remains here.

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
    // Per-player latency stats (only populated when clients send timestamps)
    {
        json latency = json::object();
        for (const auto& [tag, n] : gr.latencyCount)
        {
            if (n == 0) continue;
            std::string fullId_ = toFullId(tag, gr.playerTagToSlotId);
            long avgS2C   = gr.totalS2CMs.count(tag)   ? gr.totalS2CMs.at(tag)   / n : -1;
            long avgC2S   = gr.totalC2SMs.count(tag)    ? gr.totalC2SMs.at(tag)   / n : -1;
            long avgThink = gr.totalThinkMs.count(tag)  ? gr.totalThinkMs.at(tag) / n : -1;
            long maxThink = gr.maxThinkMs.count(tag)    ? gr.maxThinkMs.at(tag)       : -1;
            long avgBiDir = (avgS2C >= 0 && avgC2S >= 0) ? (avgS2C + avgC2S) / 2 : -1;
            latency[fullId_] = {
                {"avg_s2c_ms",     avgS2C},
                {"avg_c2s_ms",     avgC2S},
                {"avg_bidir_ms",   avgBiDir},
                {"avg_think_ms",   avgThink},
                {"max_think_ms",   maxThink},
                {"move_count",     n}
            };
        }
        j["latency"] = latency;
    }
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

// Forward declaration (defined after writeResults)
static GameResult runOneGame(const GameAssignment&, const std::string&,
    std::atomic<PlayerGameSessionID>&, const std::shared_ptr<Common::GameLogger>&,
    int, std::chrono::milliseconds);

// Runs all assignments concurrently, but limits how many games each team plays
// simultaneously (0 = no limit, original behaviour).
static std::vector<GameResult> runGames(
    const std::vector<GameAssignment>& assignments,
    const std::string& resultsDir,
    std::atomic<PlayerGameSessionID>& sessionCounter,
    const std::shared_ptr<Common::GameLogger>& nullLogger,
    int autoMoveAfterTimeouts,
    std::chrono::milliseconds moveTimeout,
    int maxConcurrentPerTeam,
    int gameParallelism,
    // Optional: invoked after each game completes with the partial results vector
    // (incomplete entries have an empty gameId). Used to write live progress.
    const std::function<void(const std::vector<GameResult>&)>& onProgress = {})
{
    std::vector<GameResult> results(assignments.size());

    auto teamOf = [](const PlayerSlot* slot) -> std::string {
        const auto& id = slot->slotId;
        auto pos = id.find('/');
        return pos == std::string::npos ? id : id.substr(0, pos);
    };

    const std::string stage = assignments.empty() ? "unknown" : assignments[0].stage;
    const int total = (int)assignments.size();
    std::atomic<int> completedCount{0};

    // Background thread: log progress every 10s while games are running.
    std::mutex progressMtx;
    std::condition_variable progressCv;
    bool progressStop = false;
    std::thread progressThread([&]() {
        std::unique_lock<std::mutex> lock(progressMtx);
        while (!progressStop) {
            if (progressCv.wait_for(lock, std::chrono::seconds(10)) == std::cv_status::timeout)
                LOG("[%s] %d/%d games complete", stage.c_str(), completedCount.load(), total);
        }
    });
    auto stopProgress = [&]() {
        { std::lock_guard<std::mutex> g(progressMtx); progressStop = true; }
        progressCv.notify_one();
        progressThread.join();
    };

    if (maxConcurrentPerTeam <= 0)
    {
        // No per-team limit: run games through a fixed-size worker pool instead of
        // spawning one thread per game. The old thread-per-game model launched one
        // std::async thread per assignment; with thousands of games that
        // oversubscribed the scheduler and (with ~8 MB stacks each) could exhaust
        // memory. It is also *slower*: a tournament's clients are a handful of
        // processes that each multiplex many game sessions over one connection, so
        // running far more games than there are client cores just starves some
        // sessions of CPU time and leaves a long tail of stragglers limping along
        // at the move timeout. Benchmarking 4 random-filler teams (see
        // benchmark_tournament.py) shows the runtime is minimised near the core
        // count and degrades sharply above it (8 workers: ~31s; 16: ~142s; 64:
        // ~124s; 170: ~252s for 170 games). Default to hardware_concurrency and let
        // GAME_PARALLELISM override it for setups with many independent clients.
        // Workers pull the next assignment index atomically; each results[i] is
        // written by exactly one worker, so no per-element locking is needed.
        unsigned hw = std::thread::hardware_concurrency();
        if (hw == 0) hw = 4;
        int workers = gameParallelism > 0 ? gameParallelism : (int)hw;
        workers = std::min<int>(workers, (int)assignments.size());
        if (workers < 1) workers = 1;
        LOG("[%s] running %d games across %d worker threads",
            stage.c_str(), total, workers);

        std::atomic<size_t> nextIdx{0};
        std::mutex progressWriteMtx; // serializes onProgress reads of results[]
        auto worker = [&]() {
            while (true)
            {
                size_t i = nextIdx.fetch_add(1);
                if (i >= assignments.size()) break;
                auto r = runOneGame(assignments[i], resultsDir, sessionCounter,
                                    nullLogger, autoMoveAfterTimeouts, moveTimeout);
                results[i] = r;             // unique index — no lock needed
                completedCount++;
                if (onProgress)
                {
                    std::lock_guard<std::mutex> g(progressWriteMtx);
                    onProgress(results);
                }
            }
        };
        std::vector<std::thread> pool;
        pool.reserve(workers);
        for (int w = 0; w < workers; w++) pool.emplace_back(worker);
        for (auto& t : pool) t.join();
        stopProgress();
        return results;
    }

    // Rate-limited launcher: scan pending games whenever a slot opens up.
    std::map<std::string, int> teamCount;
    std::mutex mtx;
    std::condition_variable cv;
    std::atomic<int> completed{0};
    std::vector<bool> started(assignments.size(), false);
    std::vector<std::thread> threads;

    auto canStart = [&](const GameAssignment& a) -> bool {
        for (auto* slot : a.players)
            if (teamCount[teamOf(slot)] >= maxConcurrentPerTeam) return false;
        return true;
    };

    while (completed < (int)assignments.size())
    {
        std::unique_lock<std::mutex> lock(mtx);

        bool anyStarted = false;
        for (size_t i = 0; i < assignments.size(); i++)
        {
            if (started[i] || !canStart(assignments[i])) continue;
            for (auto* slot : assignments[i].players) teamCount[teamOf(slot)]++;
            started[i] = true;
            lock.unlock();

            threads.emplace_back([&, i]() {
                auto r = runOneGame(assignments[i], resultsDir, sessionCounter,
                                    nullLogger, autoMoveAfterTimeouts, moveTimeout);
                {
                    std::lock_guard<std::mutex> g(mtx);
                    results[i] = r;
                    for (auto* slot : assignments[i].players) teamCount[teamOf(slot)]--;
                    completed++;
                    completedCount++;
                    if (onProgress) onProgress(results);
                }
                cv.notify_all();
            });

            lock.lock();
            anyStarted = true;
        }

        bool allDispatched = std::all_of(started.begin(), started.end(), [](bool b){ return b; });
        if (!anyStarted || allDispatched)
        {
            if (completed < (int)assignments.size())
                cv.wait(lock);
        }
    }
    for (auto& t : threads) t.join();
    stopProgress();
    return results;
}

// All the rules applying to a tournament, recorded alongside its results so a
// viewer can show exactly how a given tournament was configured. Team passwords
// are intentionally excluded — only team names are emitted.
static json buildRulesJson(const TournamentConfig& cfg,
                           const std::string& competitionId,
                           const std::string& tournamentIndex,
                           const std::string& beganAt)
{
    json rules;
    rules["competition_id"]               = competitionId;
    rules["tournament_index"]             = tournamentIndex;
    rules["began_at"]                     = beganAt;
    rules["qualifying_games"]             = cfg.qualifyingGames;
    rules["finals_games"]                 = cfg.finalsGames;
    rules["max_players_per_team"]         = cfg.maxPlayersPerTeam;
    rules["qualifying_points"]            = cfg.qualifyingPoints;
    rules["allow_multi_team_finals"]      = cfg.allowMultiTeamFinals;
    rules["auto_move_after_timeouts"]     = cfg.autoMoveAfterTimeouts;
    rules["move_timeout_ms"]              = cfg.moveTimeoutMs;
    rules["max_concurrent_games_per_team"]= cfg.maxConcurrentGamesPerTeam;
    rules["fallback_player_tag"]          = cfg.fallbackPlayerTag;
    json teamNames = json::array();
    for (const auto& [name, _pw] : cfg.teams) teamNames.push_back(name);
    rules["teams"] = teamNames;
    return rules;
}

// Writes a tournament's results.
//
// Layout (nested under a competition, when competitionId is non-empty):
//   <resultsDir>/<competitionId>/competition.json   (competition metadata + tournament list)
//   <resultsDir>/<competitionId>/<index>/summary.json
//   <resultsDir>/<competitionId>/<index>/rules.json
//   <resultsDir>/<competitionId>/<index>/games/<game_id>.json
//
// Legacy fallback (competitionId empty — e.g. running the server standalone):
//   <resultsDir>/<tournamentDirName>/summary.json (+ rules.json, games/)
//   <resultsDir>/competition.json   (flat array of {tournament_id, summary})
static void writeResults(
    const TournamentConfig& cfg,
    const std::string& competitionId,    // "" => legacy flat layout
    const std::string& tournamentDirName,// index ("1", "2", ...) nested, or timestamp legacy
    const std::string& beganAt,          // wall-clock when this tournament's games started
    const std::vector<GameResult>& qualifying,
    const std::vector<GameResult>& finals,
    const std::map<std::string, int>& qualTotals,
    const std::map<std::string, int>& finalTotals,
    // false for incremental mid-tournament progress writes, true for the final
    // authoritative write. Consumers (web UI, integration tests) use this to tell
    // an in-progress tournament from a finished one.
    bool complete = true)
{
    namespace fs = std::filesystem;
    const std::string& resultsDir = cfg.resultsDir;
    bool nested = !competitionId.empty();
    fs::path competitionDir = nested ? fs::path(resultsDir) / competitionId
                                     : fs::path(resultsDir);
    fs::path tDir = competitionDir / tournamentDirName;
    fs::path gDir = tDir / "games";
    fs::create_directories(gDir);

    std::string endedAt = complete
        ? Common::Dates::GetStrDate('-') + "_" + Common::Dates::GetStrTime('-')
        : std::string{};

    // Per-game detail files. A game's detail is immutable once the game
    // completes, so never rewrite an existing file. This is the difference
    // between O(N) and O(N^2) disk I/O: writeResults is also called on every
    // throttled live-progress tick, and re-emitting every completed game's JSON
    // on each tick dominated large-tournament runtime (a 1600-game run spent
    // hours rewriting the same files millions of times).
    auto writeGame = [&](const GameResult& gr) {
        fs::path p = gDir / (gr.gameId + ".json");
        if (fs::exists(p)) return;
        std::ofstream f(p);
        f << compactHandArrays(gameResultToDetailJson(gr).dump(2));
    };
    for (const auto& g : qualifying) writeGame(g);
    for (const auto& g : finals)     writeGame(g);

    // Summary
    json summary;
    // tournament_id keeps the human-readable identity; in nested layout it is the
    // competition-relative index, in legacy layout the timestamp dir name.
    summary["tournament_id"]    = tournamentDirName;
    summary["competition_id"]   = competitionId;
    summary["began_at"]         = beganAt;
    if (!endedAt.empty()) summary["ended_at"] = endedAt;
    json q = json::array(), fn = json::array();
    for (const auto& g : qualifying) q.push_back(gameResultToSummaryJson(g));
    for (const auto& g : finals)     fn.push_back(gameResultToSummaryJson(g));
    summary["qualifying"]       = q;
    summary["finals"]           = fn;
    summary["qualifying_totals"] = qualTotals;
    summary["finals_totals"]    = finalTotals;
    summary["complete"]         = complete;

    std::ofstream sf(tDir / "summary.json");
    sf << summary.dump(2);

    // Rules snapshot for this tournament.
    {
        std::ofstream rf(tDir / "rules.json");
        rf << buildRulesJson(cfg, competitionId, tournamentDirName, beganAt).dump(2);
    }

    if (nested) {
        // Per-competition index (object). Idempotent per tournament index: this is
        // also called incrementally while a tournament runs, so update-or-insert.
        fs::path idxPath = competitionDir / "competition.json";
        json comp = json::object();
        if (fs::exists(idxPath)) {
            std::ifstream f(idxPath);
            try { f >> comp; } catch(...) { comp = json::object(); }
        }
        comp["competition_id"]    = competitionId;
        comp["started_at"]        = competitionId; // competition dir name is its start timestamp
        comp["qualifying_games"]  = cfg.qualifyingGames;
        comp["finals_games"]      = cfg.finalsGames;
        json teamNames = json::array();
        for (const auto& [name, _pw] : cfg.teams) teamNames.push_back(name);
        comp["teams"] = teamNames;

        if (!comp.contains("tournaments") || !comp["tournaments"].is_array())
            comp["tournaments"] = json::array();
        json entry;
        entry["index"]    = tournamentDirName;
        entry["began_at"] = beganAt;
        entry["complete"] = complete;
        entry["summary"]  = tournamentDirName + "/summary.json";
        if (!endedAt.empty()) entry["ended_at"] = endedAt;
        bool replaced = false;
        for (auto& e : comp["tournaments"]) {
            if (e.value("index", std::string{}) == tournamentDirName) { e = entry; replaced = true; break; }
        }
        if (!replaced) comp["tournaments"].push_back(entry);
        std::ofstream idxOut(idxPath);
        idxOut << comp.dump(2);
    } else {
        // Legacy flat competition index (array), idempotent append.
        fs::path idxPath = fs::path(resultsDir) / "competition.json";
        json idx = json::array();
        if (fs::exists(idxPath)) {
            std::ifstream f(idxPath);
            try { f >> idx; } catch(...) {}
        }
        bool present = false;
        for (const auto& e : idx)
            if (e.value("tournament_id", std::string{}) == tournamentDirName) { present = true; break; }
        if (!present) {
            json entry;
            entry["tournament_id"] = tournamentDirName;
            entry["summary"]       = tournamentDirName + "/summary.json";
            idx.push_back(entry);
            std::ofstream idxOut(idxPath);
            idxOut << idx.dump(2);
        }
    }
}

// ─── Running one game ─────────────────────────────────────────────────────────

static std::atomic<PlayerGameSessionID> gameSessionCounter{100000};

static GameResult runOneGame(
    const GameAssignment& assignment,
    const std::string& resultsDir,
    std::atomic<PlayerGameSessionID>& sessionCounter,
    const std::shared_ptr<Common::GameLogger>& nullLogger,
    int autoMoveAfterTimeouts,
    std::chrono::milliseconds moveTimeout)
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
            sid, PlayerTag(slot->playerTag), *slot->source->connection, /*starting_seq=*/0,
            moveTimeout);
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
    std::string competitionId;     // empty => legacy flat layout
    std::string tournamentIndex;   // competition-relative index ("1", "2", ...)
    for (int i = 2; i < argc; i++)
    {
        std::string arg = argv[i];
        if (arg.substr(0, 11) == "--start-at=")
            startAt = std::stoll(arg.substr(11));
        else if (arg.substr(0, 17) == "--competition-id=")
            competitionId = arg.substr(17);
        else if (arg.substr(0, 19) == "--tournament-index=")
            tournamentIndex = arg.substr(19);
    }
    if (startAt == 0)
        startAt = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now()) + 30;

    TournamentConfig cfg = loadConfig(startAt);
    // In nested (competition) layout the tournament dir is its competition-relative
    // index; in legacy/standalone runs it is the timestamp.
    std::string timestampId = Common::Dates::GetStrDate('-') + "_" + Common::Dates::GetStrTime('-');
    std::string tournamentDirName = competitionId.empty()
        ? timestampId
        : (tournamentIndex.empty() ? std::string("1") : tournamentIndex);
    // Recorded inside summary.json / rules.json regardless of layout.
    std::string beganAt = timestampId;

    LOG("Tournament server starting on port %d, tournament starts at %lld", cfg.port, startAt);
    LOG("  move_timeout_ms=%d  auto_move_after=%d  max_concurrent_per_team=%s",
        cfg.moveTimeoutMs, cfg.autoMoveAfterTimeouts,
        cfg.maxConcurrentGamesPerTeam > 0
            ? std::to_string(cfg.maxConcurrentGamesPerTeam).c_str() : "unlimited");

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
                                return lobby.handleLobbyMessage(mc, msg);
                            },
                            [&lobby](const Message::Message& m) {
                                return lobby.isLobbyMessage(m);
                            });
                    });
                }
            }
            catch (...) { break; }
        }
    });

    // Reaper: while the registration window is open, periodically drop players whose
    // client has disconnected or missed its 15s heartbeat, and republish the live
    // status (countdown + currently-registered players) for the web UI to poll.
    constexpr int64_t kHeartbeatTimeoutSec = 15;
    std::atomic<bool> stopReaper{false};
    std::thread reaperThread([&]() {
        while (!stopReaper.load())
        {
            lobby.pruneDeadPlayers(kHeartbeatTimeoutSec);
            writeLiveStatus(cfg.resultsDir, competitionId, tournamentDirName,
                            "registering", startAt, lobby.snapshotRegistered());
            // Sleep ~1s in short slices so we exit promptly when registration closes.
            for (int i = 0; i < 10 && !stopReaper.load(); ++i)
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
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

    // Stop the reaper and do a final prune so the roster reflects only live clients,
    // then flip the published status to "running".
    stopReaper.store(true);
    reaperThread.join();
    lobby.pruneDeadPlayers(kHeartbeatTimeoutSec);
    writeLiveStatus(cfg.resultsDir, competitionId, tournamentDirName,
                    "running", startAt, lobby.snapshotRegistered());

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

    // Live progress: write a partial summary.json (+ completed game files, + the
    // competition index entry) as games finish, so the web UI's live page can show
    // standings and counts mid-tournament. Throttled so frequent completions don't
    // rewrite the files on every single game. The final writeResults() below always
    // produces the authoritative, complete output.
    auto completedOnly = [](const std::vector<GameResult>& v) {
        std::vector<GameResult> out;
        for (const auto& g : v) if (!g.gameId.empty()) out.push_back(g);
        return out;
    };
    auto lastProgressWrite = std::make_shared<std::chrono::steady_clock::time_point>();
    auto writeProgress = [&, completedOnly, lastProgressWrite](
                             const std::vector<GameResult>& qual,
                             const std::vector<GameResult>& fin) {
        auto now = std::chrono::steady_clock::now();
        if (now - *lastProgressWrite < std::chrono::seconds(2)) return;
        *lastProgressWrite = now;
        auto q = completedOnly(qual);
        auto f = completedOnly(fin);
        auto qt = tabulateQualifyingPoints(q, cfg.qualifyingPoints);
        auto ft = tabulateQualifyingPoints(f, cfg.qualifyingPoints);
        writeResults(cfg, competitionId, tournamentDirName, beganAt, q, f, qt, ft, /*complete=*/false);
    };

    // ── Stage 1: Qualifying ─────────────────────────────────────────────────

    auto qAssignments = scheduleGames(teamRosters, cfg.qualifyingGames, "qualifying");
    auto qualifyingResults = runGames(qAssignments, cfg.resultsDir, gameSessionCounter,
        nullLogger, cfg.autoMoveAfterTimeouts,
        std::chrono::milliseconds(cfg.moveTimeoutMs),
        cfg.maxConcurrentGamesPerTeam, cfg.gameParallelism,
        [&](const std::vector<GameResult>& partial) { writeProgress(partial, {}); });

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

    // Aggregate latency per slotId across a set of game results.
    struct LatencyAgg {
        long totalS2C=0, totalC2S=0, totalThink=0;
        long maxS2C=0, maxC2S=0, maxThink=0, maxTotal=0;
        int count=0;
    };
    auto aggregateLatency = [](const std::vector<GameResult>& games) {
        std::map<std::string, LatencyAgg> agg;
        for (const auto& gr : games) {
            for (const auto& [tagSession, n] : gr.latencyCount) {
                auto it = gr.playerTagToSlotId.find(tagSession);
                if (it == gr.playerTagToSlotId.end()) continue;
                const auto& slotId = it->second;
                auto& a = agg[slotId];
                a.count += n;
                if (gr.totalS2CMs.count(tagSession))      a.totalS2C  += gr.totalS2CMs.at(tagSession);
                if (gr.totalC2SMs.count(tagSession))      a.totalC2S  += gr.totalC2SMs.at(tagSession);
                if (gr.totalThinkMs.count(tagSession))    a.totalThink += gr.totalThinkMs.at(tagSession);
                if (gr.maxThinkMs.count(tagSession))      a.maxThink   = std::max(a.maxThink, gr.maxThinkMs.at(tagSession));
                if (gr.maxS2CMs.count(tagSession))        a.maxS2C     = std::max(a.maxS2C,   gr.maxS2CMs.at(tagSession));
                if (gr.maxC2SMs.count(tagSession))        a.maxC2S     = std::max(a.maxC2S,   gr.maxC2SMs.at(tagSession));
                if (gr.maxMoveLatencyMs.count(tagSession))a.maxTotal   = std::max(a.maxTotal,  gr.maxMoveLatencyMs.at(tagSession));
            }
        }
        return agg;
    };

    auto logLeaderboard = [](const char* header, const std::map<std::string, int>& totals,
                              const std::map<std::string, LatencyAgg>& latency) {
        std::vector<std::pair<std::string, int>> ranked(totals.begin(), totals.end());
        std::sort(ranked.begin(), ranked.end(), [](const auto& a, const auto& b){
            return a.second > b.second;
        });
        LOG("%s", header);
        bool hasLatency = std::any_of(ranked.begin(), ranked.end(), [&latency](const auto& p) {
            auto it = latency.find(p.first);
            return it != latency.end() && it->second.count > 0;
        });
        if (hasLatency)
            LOG("     %-40s   pts  |  avg s2c  avg c2s  avg think  |  max s2c  max c2s  max think  max total",
                "slot");
        for (int i = 0; i < (int)ranked.size(); i++) {
            const auto& slotId = ranked[i].first;
            auto it = latency.find(slotId);
            if (it != latency.end() && it->second.count > 0) {
                const auto& a = it->second;
                long avgS2C   = a.totalS2C   / a.count;
                long avgC2S   = a.totalC2S   / a.count;
                long avgThink = a.totalThink / a.count;
                LOG("  %d. %-40s  %3d pts  |  %4ldms   %4ldms   %4ldms     |  %4ldms   %4ldms   %4ldms     %4ldms",
                    i + 1, slotId.c_str(), ranked[i].second,
                    avgS2C, avgC2S, avgThink,
                    a.maxS2C, a.maxC2S, a.maxThink, a.maxTotal);
            } else {
                LOG("  %d. %-40s  %3d pts", i + 1, slotId.c_str(), ranked[i].second);
            }
        }
    };

    // Log full qualifying leaderboard
    {
        auto qualLatency = aggregateLatency(qualifyingResults);
        char header[64];
        snprintf(header, sizeof(header), "Qualifying results (%d slots):", (int)qualTotals.size());
        logLeaderboard(header, qualTotals, qualLatency);
    }

    auto finalistTags = selectFinalists(qualTotals, cfg.allowMultiTeamFinals);

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
    auto finalsResults = runGames(fAssignments, cfg.resultsDir, gameSessionCounter,
        nullLogger, cfg.autoMoveAfterTimeouts,
        std::chrono::milliseconds(cfg.moveTimeoutMs),
        cfg.maxConcurrentGamesPerTeam, cfg.gameParallelism,
        [&](const std::vector<GameResult>& partial) { writeProgress(qualifyingResults, partial); });

    // ── Notify clients and write results ────────────────────────────────────

    // Finals use the same point table as qualifying; winner = most finals points.
    auto finalTotals = tabulateQualifyingPoints(finalsResults, cfg.qualifyingPoints);

    // Log finals-only rankings
    {
        auto finalsLatency = aggregateLatency(finalsResults);
        logLeaderboard("Finals results (finals points only):", finalTotals, finalsLatency);
    }

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

    writeResults(cfg, competitionId, tournamentDirName, beganAt,
                 qualifyingResults, finalsResults, qualTotals, finalTotals);
    if (competitionId.empty())
        LOG("Results written to %s/%s", cfg.resultsDir.c_str(), tournamentDirName.c_str());
    else
        LOG("Results written to %s/%s/%s", cfg.resultsDir.c_str(),
            competitionId.c_str(), tournamentDirName.c_str());

    LOG("Tournament %s complete.", tournamentDirName.c_str());

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
