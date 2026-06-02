# Hearts C++ Client SDK

A small, performance-minded C++ SDK for writing Hearts AI clients that connect
to the engine's TCP server. It mirrors the Python client SDK
(`clients/python/`) but is header-only and does **no dynamic allocation on the
game hot path** — cards live in fixed-capacity stack arrays and player
identifiers are passed as `std::string_view` into the already-parsed message.
The only heap use is inside the JSON library at the transport boundary.

The SDK deliberately stays minimal: it does the work needed to talk to the
server correctly and leaves strategy, threading, and performance tuning to you.

## Layout

```
clients/cpp/
  sdk/                  header-only library (cc_library //clients/cpp/sdk)
    card.h              Card / Rank / Suit value types (2-byte Card)
    card_set.h          BasicCardSet<N> fixed-capacity card container
    protocol.h          wire constants, mirrored from server/util/constants.h
    transport.h         MessageChannel interface + "}{" frame splitter
    tcp_channel.h       POSIX-socket MessageChannel (TCP_NODELAY)
    session.h           per-session shared sequence-number bookkeeping
    player.h            Player interface + PlayerList / ScoreList value types
    game_runner.h       drives one Session through a full game via Player hooks
    client.h            connect + handshake + joinLobby entry point
    env.h               tiny KEY=VALUE config-file reader
  players/
    random_player.h     reference AI / template (passes & plays at random)
    random_player_main.cpp   CLI entry point: join a lobby and play N games
  tests/                gtest unit tests
```

## Build & test

Bazel 9+ (same toolchain as the server):

```bash
bazel build --cxxopt=-std=c++17 --features=external_include_paths //clients/cpp/...
bazel test  --cxxopt=-std=c++17 --features=external_include_paths //clients/cpp/...
```

## Running the reference player

Create a table in the web UI, mark a seat **Open (CLI)**, copy the lobby code,
then point the binary at your `config.env` (for `SERVER_ADDR` / `SERVER_PORT`):

```bash
bazel run //clients/cpp/players:random_player_bin -- \
    --lobby-code=ABCD --games=1 "$(pwd)/config.env"
```

Flags: `--lobby-code` (default `main`), `--player-tag` (default `cpp_random`),
`--games` (default 1), `--env-file` / bare positional path (default
`config.env`). Sessions sharing a lobby code are matched FIFO into one game, so
a CLI client and a UI seat can share a table, and CLI clients can fill a table
among themselves.

## Writing your own player

Copy `players/random_player.h`, rename the class, and implement the two required
decisions. Override the observation hooks to track state.

```cpp
#include "clients/cpp/sdk/player.h"

class MyPlayer : public hearts::Player {
 public:
  // REQUIRED: append exactly 3 cards from `hand` to `out`. Never called on
  // Keeper rounds. (out starts empty.)
  void getCardsToPass(hearts::PassDirection dir, const hearts::CardSet& hand,
                      hearts::CardSet& out) override {
    for (std::size_t i = 0; i < 3; ++i) out.push_back(hand[i]);
  }

  // REQUIRED: return one card from `legalMoves` (always non-empty).
  hearts::Card getMove(const hearts::CardSet& legalMoves) override {
    return legalMoves[0];
  }

  // OPTIONAL hooks (default no-ops): onStartGame, onStartRound,
  // onReceivedCards, onStartTrick, onMove, onEndTrick, onEndRound, onEndGame.
  void onMove(std::string_view player, hearts::Card card, bool autoMoved) override {
    // observe every player's move, including your own
  }
};
```

Wire it up with `Client` + `GameRunner`:

```cpp
hearts::Client client(host, port);                 // connects + handshakes
hearts::Session s = client.joinLobby("my_tag", "ABCD");
MyPlayer player;
hearts::GameRunner(s, player).run();               // plays one game to end_game
```

Add a `cc_library` / `cc_binary` for your player next to the random one in
`players/BUILD`.

## How it talks to the server

- **Framing.** Messages are compact JSON objects concatenated with no
  delimiter; the only place `}{` can appear is a message boundary, so receivers
  split there (`takeFirstFrame` in `transport.h`), matching the server's
  `getFirstMessage`.
- **Sequence numbers.** A session uses a *single* counter that advances on every
  message in *either* direction, because play is strictly request/response.
  `Session` stamps each outbound message with the session id and next seq, and
  resynchronizes to the server if it ever runs ahead (e.g. after a server
  auto-move on timeout). A client-initiated lobby session resumes at seq 2 after
  the handshake.
- **Game flow.** `GameRunner` receives a message, dispatches by `type`, and the
  only messages it originates are `donated_cards` (after a non-Keeper
  `start_round`) and `decided_move` (in reply to `move_request`). It validates
  the player's choices and throws `std::logic_error` on a player bug (wrong
  pass count, illegal move) rather than sending a malformed message.

The protocol constants live in `protocol.h` and must stay in sync with
`server/util/constants.h`. The full protocol spec is in `clients/README.md`.

## Concurrency

One `Client` plays one game at a time. That covers lobby play and is enough to
play tournament-assigned games sequentially. Running many games in parallel is
intentionally left to you — construct one `Client` per thread.
