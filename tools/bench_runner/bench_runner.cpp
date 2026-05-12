// =============================================================================
// In-process bench runner for the Hearts engine.
//
// PURPOSE
//   Run Hearts games entirely inside one process — no TCP, no JSON, no
//   server. Goals:
//     (1) generate 30,000+ games of training data for a neural network in
//         minutes instead of hours,
//     (2) run benchmarks ~10x faster than the current TCP-mediated bench.
//
// CURRENT BOTTLENECK
//   A game over the live TCP server takes ~1.3s wall-clock. Per decision
//   (208 decisions/game) that's ~6.4ms — roughly 4ms TCP+JSON, 2ms Python
//   player logic. Eliminating TCP/JSON saves ~60%. Reimplementing hot
//   players in C++ is additive on top of that.
//
// ARCHITECTURE
//   This binary reuses the existing //server/game library unchanged.
//   The Common::Game::Player abstract class (server/game/objects/player.h)
//   is the seam: TCP players (server/game/remote_player.h) provide one
//   implementation; this binary provides in-process implementations that
//   talk directly to the C++ Game/Round/Trick loop.
//
//   The TCP server code path is untouched.
//
//                       Common::Game::Player (abstract)
//                       /            |              \
//                 RemotePlayer  LocalPlayer    (future) PyBridgePlayer
//                  (TCP/JSON)   (RandomLocal,    (pybind11 → claude_v1,
//                                LowestLocal)     expert_player, etc.)
//
// CHOSEN STRATEGY
//   Option 1 (pybind11-embedded Python runner) — recommended.
//   Reasoning:
//     - The existing Python claude_v1/expert_player are the immediate
//       targets for training-data generation. Rewriting them in C++
//       (Option 2) delays the goal; pybind11 lets us use them as-is.
//     - The TCP/JSON overhead (~4ms/decision) is the dominant cost.
//       Eliminating it yields the targeted speedup even with Python
//       still in the loop.
//     - The runner skeleton is the same for all three options; we can
//       drop in C++ ports for hot players later without rewriting it.
//       Option 1 is a strict subset of Option 2.
//
// THIS FIRST SLICE
//   - Built-in C++ RandomLocalPlayer and LowestLocalPlayer (see
//     local_player.h).
//   - CLI: --games N --p0 NAME --p1 NAME --p2 NAME --p3 NAME [--seed S]
//   - Per-matchup output that mirrors scripts/bench.py: target avg
//     points/game, win rate with Wilson 95% CI, and a brief "others"
//     summary.
//   - Logs go to stderr (a sink GameLogger writes to /dev/null) so stdout
//     stays clean and machine-readable.
//
// FOLLOW-UP — making this useful for training-data generation
//   1. [DONE] PyBridgePlayer (pybind11) — wraps a Python Player instance.
//      See py_bridge_player.h. Built with vendored pybind11 + Python 3.14
//      headers under //third_party (Homebrew install on Apple Silicon).
//      Measured ~22 games/sec for a 4-seat mixed-Python lineup
//      (claude_v1+claude_player+expert_player+random); ~38 g/s with a
//      single Python target vs 3 randoms. Compare to ~0.77 g/s over TCP —
//      roughly 29× speedup for the mixed lineup, 50× for the single-Python
//      lineup.
//   2. Add a --decision-log mode that emits per-decision NDJSON records
//      (state features + chosen card + final game score) — the actual
//      training-data format consumed downstream.
//   3. Optional: thread pool over games (game state is per-player and
//      independent; the runner is embarassingly parallel). Note: pybind11
//      requires GIL acquisition for Python calls, so parallelism here only
//      helps for C++-only AIs unless we run multiple sub-interpreters or
//      release the GIL around C++-only work.
//
// USAGE
//   bazel run //tools/bench_runner:bench_runner -- \
//       --games 100 --p0 random --p1 random --p2 random --p3 lowest
// =============================================================================

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <memory>
#include <random>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include <pybind11/embed.h>
#include <pybind11/pybind11.h>

#include "tools/bench_runner/local_player.h"
#include "tools/bench_runner/logging_player_proxy.h"
#include "tools/bench_runner/py_bridge_player.h"
#include "server/game/game.h"
#include "server/game/objects/player.h"
#include "server/util/logging.h"

namespace Tools::BenchRunner
{

namespace py = pybind11;

struct CliArgs
{
    int numGames = 100;
    std::string playerSpecs[4] = {"random", "random", "random", "random"};
    unsigned long seed = 0;
    bool seedExplicit = false;
    // When non-empty, the runner wraps every player in a LoggingPlayerProxy
    // and writes one NDJSON record per AI decision (move + pass) plus a
    // per-game `game_end` record to this path. This is the training-data
    // format for the supervised neural-network player.
    std::string decisionLogPath;
};

[[noreturn]] static void printUsageAndExit(int code)
{
    std::fprintf(stderr,
        "Usage: bench_runner [--games N] [--seed S]\n"
        "                    [--p0 SPEC] [--p1 SPEC] [--p2 SPEC] [--p3 SPEC]\n"
        "                    [--decision-log PATH]\n"
        "\n"
        "Built-in player SPECs:\n"
        "  random      — uniform-random over legal moves (matches RandomPlayer)\n"
        "  lowest      — always play the lowest legal card; pass the three highest\n"
        "  py:<spec>   — load a Python Player via embedded pybind11. Resolution\n"
        "                mirrors scripts/bench.py:\n"
        "                  py:claude_v1                  -> tim.players.claude_v1\n"
        "                                                   then clients.python.players.claude_v1\n"
        "                  py:claude_player              -> clients.python.players.claude_player\n"
        "                  py:tim.players.claude_v1      -> fully-qualified module\n"
        "                  py:tim.players.claude_v1:ClaudeV1   -> explicit class\n"
        "\n"
        "Output: one line per game on stdout (game_idx,p0,p1,p2,p3 scores),\n"
        "then a summary block per target seat.\n"
        "\n"
        "Example:\n"
        "  bench_runner --games 100 \\\n"
        "      --p0 py:claude_v1 --p1 py:claude_player --p2 py:expert_player --p3 random\n"
    );
    std::exit(code);
}

static CliArgs parseArgs(int argc, char** argv)
{
    CliArgs args;
    auto need = [&](int i){
        if (i + 1 >= argc) printUsageAndExit(1);
    };
    for (int i = 1; i < argc; ++i)
    {
        std::string a = argv[i];
        if (a == "-h" || a == "--help") printUsageAndExit(0);
        else if (a == "--games") { need(i); args.numGames = std::atoi(argv[++i]); }
        else if (a == "--seed")  { need(i); args.seed = std::strtoul(argv[++i], nullptr, 10); args.seedExplicit = true; }
        else if (a == "--p0")    { need(i); args.playerSpecs[0] = argv[++i]; }
        else if (a == "--p1")    { need(i); args.playerSpecs[1] = argv[++i]; }
        else if (a == "--p2")    { need(i); args.playerSpecs[2] = argv[++i]; }
        else if (a == "--p3")    { need(i); args.playerSpecs[3] = argv[++i]; }
        else if (a == "--decision-log") { need(i); args.decisionLogPath = argv[++i]; }
        else { std::fprintf(stderr, "unknown arg: %s\n", a.c_str()); printUsageAndExit(1); }
    }
    if (args.numGames <= 0) { std::fprintf(stderr, "--games must be > 0\n"); std::exit(1); }
    return args;
}

// Build a player from a spec string, allocating it with a stable tag that
// distinguishes seats so the server-side bookkeeping (which uses tags as
// map keys) doesn't collide when two seats use the same algorithm.
static Common::Game::PlayerRef makePlayer(const std::string& spec, int seatIdx, std::mt19937& seatRng)
{
    // py:<rest> specs: forward to the pybind11 bridge. The bridge derives
    // the canonical PlayerTagSession from the Python class's declared
    // `player_tag` (the C++ tag is updated to match — see
    // PyBridgePlayer::getTagSession after construction). We pass a
    // placeholder tag here; MakePyBridgePlayer rewrites it.
    if (spec.rfind("py:", 0) == 0)
    {
        std::string pySpec = spec.substr(3);
        std::string placeholder = "py(" + std::to_string(seatIdx) + ")";
        return MakePyBridgePlayer(placeholder, pySpec, seatIdx);
    }

    // Tag format: <spec>(<seat>) — readable in logs, unique per seat.
    Common::Server::PlayerTagSession tag = spec + "(" + std::to_string(seatIdx) + ")";
    if (spec == "random")
    {
        return std::make_shared<RandomLocalPlayer>(tag, seatRng());
    }
    if (spec == "lowest")
    {
        return std::make_shared<LowestLocalPlayer>(tag);
    }
    throw std::runtime_error("unknown player spec: " + spec
                             + " (try 'random', 'lowest', or 'py:<module>[:Class]')");
}

// Initialize the embedded CPython interpreter and add the project repos to
// sys.path. Mirrors scripts/bench.py's resolution rules. Called once per
// process; no-op if Python is already initialized.
//
// Paths added:
//   - /Users/tim/Documents/CS/Hearts Server/hearts-engine  (clients.python.*)
//   - /Users/tim/Documents/CS/Tim-hearts-ais                (tim.*)
//
// We resolve the first path from the workspace root that Bazel sets via
// $BUILD_WORKSPACE_DIRECTORY when running with `bazel run`. Fallback to the
// hard-coded absolute path for direct invocation of the binary.
static void initPython()
{
    static bool initialized = false;
    if (initialized) return;
    initialized = true;
    pybind11::initialize_interpreter();

    pybind11::module_ sys = pybind11::module_::import("sys");
    pybind11::list path = sys.attr("path");

    auto addPath = [&](const std::string& p) {
        if (p.empty()) return;
        path.attr("insert")(0, p);
    };

    // Hearts-engine workspace root (clients.python.* lives here).
    std::string workspaceRoot;
    const char* workspace = std::getenv("BUILD_WORKSPACE_DIRECTORY");
    if (workspace && *workspace) workspaceRoot = workspace;
    else workspaceRoot = "/Users/tim/Documents/CS/Hearts Server/hearts-engine";
    addPath(workspaceRoot);

    // Tim-hearts-ais sibling repo (tim.* lives here).
    const char* timRepo = std::getenv("TIM_HEARTS_AIS");
    if (timRepo && *timRepo)
    {
        addPath(timRepo);
    }
    else
    {
        addPath("/Users/tim/Documents/CS/Tim-hearts-ais");
    }

    // clients/python/util/Env.py reads sys.argv[1] as the config path at
    // import time. We never actually open a server connection from this
    // binary, but importing ManagedConnection (transitively via any AI's
    // module-level imports) still triggers Env. Point it at the workspace's
    // config.env to satisfy the read.
    pybind11::list argv = sys.attr("argv");
    if (py::len(argv) < 2)
    {
        argv.append(workspaceRoot + "/config.env");
    }
    else
    {
        argv[0] = pybind11::cast(std::string("bench_runner"));
        argv[1] = pybind11::cast(workspaceRoot + "/config.env");
    }
}

// Wilson 95% CI for k wins out of n trials. Mirrors scripts/bench.py.
struct WilsonInterval { double p; double lo; double hi; };
static WilsonInterval wilson(int k, int n)
{
    if (n == 0) return {0, 0, 0};
    double p = static_cast<double>(k) / n;
    constexpr double z = 1.96;
    double denom = 1.0 + z * z / n;
    double centre = (p + z * z / (2 * n)) / denom;
    double half = z * std::sqrt(p * (1 - p) / n + z * z / (4.0 * n * n)) / denom;
    return {p, std::max(0.0, centre - half), std::min(1.0, centre + half)};
}

// One game run: returns final scores keyed by player tag, plus winner tag
// (lowest-scoring player). Uses a fresh PlayerArray per game so per-player
// hand/score state resets cleanly.
struct GameResult
{
    std::vector<std::pair<std::string, int>> scoresInSeatOrder;
    std::string winnerTag;
};

static GameResult runOneGame(const CliArgs& args, std::mt19937& seedRng,
                             const std::shared_ptr<Common::GameLogger>& logger,
                             const std::shared_ptr<DecisionLogContext>& logCtx)
{
    Common::Game::PlayerArray players;
    for (int seat = 0; seat < 4; ++seat)
    {
        auto inner = makePlayer(args.playerSpecs[seat], seat, seedRng);
        if (logCtx)
        {
            // Wrap each inner player in a logging proxy. The engine sees
            // the proxy as the Player (so all hand/state mutations target
            // the proxy's inherited Player members). The proxy syncs the
            // inner's hand on demand inside getMove/getCardsToPass — see
            // LoggingPlayerProxy::syncInnerHand for the rationale.
            players[seat] = std::make_shared<LoggingPlayerProxy>(
                inner, seat, logCtx);
        }
        else
        {
            players[seat] = inner;
        }
    }
    Common::Game::Game game(players, logger);
    Common::Game::PlayerArray ranked = game.runGame();
    // ranked is sorted by decreasing score; winner is the last entry.
    GameResult result;
    for (auto& p : players)
    {
        result.scoresInSeatOrder.emplace_back(p->getTagSession(), p->getScore());
    }
    result.winnerTag = ranked[ranked.size() - 1]->getTagSession();
    return result;
}

static int runMain(int argc, char** argv)
{
    CliArgs args = parseArgs(argc, argv);

    // Initialize the embedded Python interpreter iff any spec uses py:. We
    // intentionally don't initialize it for pure-C++ runs so the binary
    // startup stays sub-millisecond for the random/lowest panels.
    bool needPython = false;
    for (auto& s : args.playerSpecs)
    {
        if (s.rfind("py:", 0) == 0) { needPython = true; break; }
    }
    if (needPython) initPython();

    // Use /dev/null for game logging by default — we want the bench fast,
    // not flooded with logs. To re-enable, change "/dev/null" below to
    // e.g. "log/bench_runner.log".
    FILE* nullSink = std::fopen("/dev/null", "w");
    if (!nullSink) nullSink = stderr;  // fallback
    auto logger = std::make_shared<Common::GameLogger>(nullSink);

    // If --decision-log was provided, open the NDJSON sink. One global
    // file handle is shared by all four LoggingPlayerProxy instances per
    // game; the proxies don't lock (single-threaded runner).
    std::shared_ptr<DecisionLogContext> logCtx;
    FILE* decisionLogFile = nullptr;
    if (!args.decisionLogPath.empty())
    {
        decisionLogFile = std::fopen(args.decisionLogPath.c_str(), "w");
        if (!decisionLogFile)
        {
            std::fprintf(stderr, "bench_runner: failed to open --decision-log %s\n",
                         args.decisionLogPath.c_str());
            std::exit(1);
        }
        logCtx = std::make_shared<DecisionLogContext>();
        logCtx->fp = decisionLogFile;
        logCtx->gameIndex = 0;
        std::fprintf(stderr, "bench_runner: writing decision log to %s\n",
                     args.decisionLogPath.c_str());
    }

    unsigned long seed = args.seedExplicit
        ? args.seed
        : static_cast<unsigned long>(std::chrono::steady_clock::now().time_since_epoch().count());
    std::mt19937 seedRng(seed);

    std::fprintf(stderr,
        "bench_runner: %d games, seats=[%s, %s, %s, %s], seed=%lu\n",
        args.numGames,
        args.playerSpecs[0].c_str(), args.playerSpecs[1].c_str(),
        args.playerSpecs[2].c_str(), args.playerSpecs[3].c_str(),
        seed);

    // Per-game CSV header on stdout for machine consumption.
    std::printf("game,p0_tag,p0_score,p1_tag,p1_score,p2_tag,p2_score,p3_tag,p3_score,winner\n");

    // Aggregate stats per spec (NOT per tag — two seats with the same
    // spec aggregate together, like bench.py's "target_seats" logic).
    std::unordered_map<std::string, int> specSeats;
    for (auto& s : args.playerSpecs) specSeats[s]++;
    std::unordered_map<std::string, long long> specPointsTotal;
    std::unordered_map<std::string, int> specWins;
    for (auto& kv : specSeats) { specPointsTotal[kv.first] = 0; specWins[kv.first] = 0; }

    auto t0 = std::chrono::steady_clock::now();
    for (int gameIdx = 0; gameIdx < args.numGames; ++gameIdx)
    {
        if (logCtx) logCtx->gameIndex = gameIdx;
        GameResult r = runOneGame(args, seedRng, logger, logCtx);
        std::printf("%d", gameIdx);
        for (int seat = 0; seat < 4; ++seat)
        {
            auto& [tag, score] = r.scoresInSeatOrder[seat];
            std::printf(",%s,%d", tag.c_str(), score);
            specPointsTotal[args.playerSpecs[seat]] += score;
        }
        std::printf(",%s\n", r.winnerTag.c_str());
        // Attribute the win to the spec of the seat whose tag matches.
        for (int seat = 0; seat < 4; ++seat)
        {
            if (r.scoresInSeatOrder[seat].first == r.winnerTag)
            {
                specWins[args.playerSpecs[seat]]++;
                break;
            }
        }
    }
    auto t1 = std::chrono::steady_clock::now();
    double elapsed = std::chrono::duration<double>(t1 - t0).count();

    // Summary block per unique spec — matches bench.py's reporting shape.
    std::fprintf(stderr, "\nSummary (%d games, %.2fs, %.1f games/sec):\n",
                 args.numGames, elapsed, args.numGames / std::max(elapsed, 1e-9));
    for (auto& [spec, seats] : specSeats)
    {
        long long total = specPointsTotal[spec];
        int wins = specWins[spec];
        int gameSeats = args.numGames * seats;
        double avg = static_cast<double>(total) / gameSeats;
        WilsonInterval w = wilson(wins, gameSeats);
        std::fprintf(stderr,
            "  %-20s avg points/game: %5.2f  "
            "(win rate %4.1f%% [%4.1f-%4.1f%%], %d/%d seats)\n",
            spec.c_str(), avg, w.p * 100.0, w.lo * 100.0, w.hi * 100.0,
            wins, gameSeats);
    }

    if (nullSink && nullSink != stderr) std::fclose(nullSink);
    if (decisionLogFile)
    {
        std::fflush(decisionLogFile);
        std::fclose(decisionLogFile);
    }
    return 0;
}

}  // namespace Tools::BenchRunner

int main(int argc, char** argv)
{
    try
    {
        return Tools::BenchRunner::runMain(argc, argv);
    }
    catch (const std::exception& e)
    {
        std::fprintf(stderr, "bench_runner: fatal: %s\n", e.what());
        return 2;
    }
}
