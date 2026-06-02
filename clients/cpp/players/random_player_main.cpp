// random_player_main — join a lobby from the command line with the C++ SDK's
// RandomPlayer. Mirrors clients/python/lobby_client.py: create a table in the
// web UI, mark a seat "Open (CLI)", copy the lobby code, then run:
//
//   bazel run //clients/cpp/players:random_player -- \
//       --lobby-code=ABCD --games=1 "$(pwd)/config.env"
//
// The server address/port are read from an env file (config.env by default, or
// a positional path / --env-file=PATH), the same convention as the Python
// clients. Sessions sharing a lobby code are matched FIFO into one game.

#include <cstdlib>
#include <iostream>
#include <string>

#include "clients/cpp/players/random_player.h"
#include "clients/cpp/sdk/client.h"
#include "clients/cpp/sdk/env.h"
#include "clients/cpp/sdk/game_runner.h"

namespace {

struct Args {
  std::string envFile = "config.env";
  std::string lobbyCode = hearts::proto::kDefaultLobbyCode;
  std::string playerTag = "cpp_random";
  int games = 1;
};

// Parse a "--key=value" flag into `out`; returns true if it matched `key`.
bool matchFlag(const std::string& arg, const char* key, std::string& out) {
  std::string prefix = std::string("--") + key + "=";
  if (arg.rfind(prefix, 0) == 0) {
    out = arg.substr(prefix.size());
    return true;
  }
  return false;
}

Args parseArgs(int argc, char** argv) {
  Args args;
  std::string val;
  for (int i = 1; i < argc; ++i) {
    std::string a = argv[i];
    if (matchFlag(a, "lobby-code", args.lobbyCode)) continue;
    if (matchFlag(a, "player-tag", args.playerTag)) continue;
    if (matchFlag(a, "env-file", args.envFile)) continue;
    if (matchFlag(a, "games", val)) { args.games = std::stoi(val); continue; }
    if (a.rfind("--", 0) == 0) {
      std::cerr << "Unknown flag: " << a << "\n";
      std::exit(2);
    }
    args.envFile = a;  // bare positional = env file path
  }
  return args;
}

}  // namespace

int main(int argc, char** argv) {
  Args args = parseArgs(argc, argv);

  std::string host;
  int port = 0;
  try {
    hearts::EnvFile env(args.envFile);
    host = env.getOr("SERVER_ADDR", "127.0.0.1");
    port = env.getInt("SERVER_PORT");
  } catch (const std::exception& e) {
    std::cerr << "Config error: " << e.what() << "\n";
    return 1;
  }

  std::cout << "Joining lobby '" << args.lobbyCode << "' as " << args.playerTag
            << " on " << host << ":" << port << " for " << args.games
            << " game(s)...\n";

  for (int g = 0; g < args.games; ++g) {
    try {
      hearts::Client client(host, port);
      hearts::Session session = client.joinLobby(args.playerTag, args.lobbyCode);
      hearts::RandomPlayer player;
      hearts::GameRunner(session, player).run();
      std::cout << "Game " << (g + 1) << "/" << args.games << " finished.\n";
    } catch (const hearts::ConnectionClosed&) {
      std::cout << "Game " << (g + 1) << "/" << args.games
                << ": server closed the connection.\n";
    } catch (const std::exception& e) {
      std::cerr << "Game " << (g + 1) << "/" << args.games
                << " error: " << e.what() << "\n";
      return 1;
    }
  }
  return 0;
}
