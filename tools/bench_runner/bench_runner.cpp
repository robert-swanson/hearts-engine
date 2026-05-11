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
//   1. Add PyBridgePlayer (pybind11) that wraps a Python Player instance.
//      Build: add @pybind11 as a Bazel dep (or via rules_python), link
//      libpython at runtime. Map Card<->str, CardCollection<->List[str],
//      PassDirection<->enum string. Mirror the eight Player virtuals.
//   2. Add a --decision-log mode that emits per-decision NDJSON records
//      (state features + chosen card + final game score) — the actual
//      training-data format consumed downstream.
//   3. Optional: thread pool over games (game state is per-player and
//      independent; the runner is embarassingly parallel).
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

#include "tools/bench_runner/local_player.h"
#include "server/game/game.h"
#include "server/game/objects/player.h"
#include "server/util/logging.h"

namespace Tools::BenchRunner
{

struct CliArgs
{
    int numGames = 100;
    std::string playerSpecs[4] = {"random", "random", "random", "random"};
    unsigned long seed = 0;
    bool seedExplicit = false;
};

[[noreturn]] static void printUsageAndExit(int code)
{
    std::fprintf(stderr,
        "Usage: bench_runner [--games N] [--seed S]\n"
        "                    [--p0 SPEC] [--p1 SPEC] [--p2 SPEC] [--p3 SPEC]\n"
        "\n"
        "Built-in player SPECs:\n"
        "  random  — uniform-random over legal moves (matches RandomPlayer)\n"
        "  lowest  — always play the lowest legal card; pass the three highest\n"
        "\n"
        "Output: one line per game on stdout (game_idx,p0,p1,p2,p3 scores),\n"
        "then a summary block per target seat.\n"
        "\n"
        "Example:\n"
        "  bench_runner --games 100 --p0 random --p1 lowest --p2 lowest --p3 lowest\n"
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
    throw std::runtime_error("unknown player spec: " + spec + " (try 'random' or 'lowest')");
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
                             const std::shared_ptr<Common::GameLogger>& logger)
{
    Common::Game::PlayerArray players;
    for (int seat = 0; seat < 4; ++seat)
    {
        players[seat] = makePlayer(args.playerSpecs[seat], seat, seedRng);
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

    // Use /dev/null for game logging by default — we want the bench fast,
    // not flooded with logs. To re-enable, change "/dev/null" below to
    // e.g. "log/bench_runner.log".
    FILE* nullSink = std::fopen("/dev/null", "w");
    if (!nullSink) nullSink = stderr;  // fallback
    auto logger = std::make_shared<Common::GameLogger>(nullSink);

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
        GameResult r = runOneGame(args, seedRng, logger);
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
