# Tournament System Handoff

## Goal
Implement and test a two-stage Hearts tournament system. User asked to run a single tournament locally with 3 registered teams and report back when it completes.

## Current Branch
`feature/tournament` — all code written but **not yet compiled or tested**.

---

## What's Done (code written, not verified)

### New files (untracked)
| File | Purpose |
|------|---------|
| `server/tournament_server.cpp` | Two-stage tournament binary (~833 lines) |
| `server/game/game_observer.h` | Observer interface for recording game events |
| `clients/python/api/networking/TournamentSession.py` | Python client-side tournament flow |
| `clients/python/tournament_client.py` | Standalone script to connect a player |
| `competition_runner.py` | Orchestrates server + clients, has `--non-interactive` mode |

### Modified files
- `server/BUILD` — added `tournament_server` cc_binary target
- `server/game/BUILD` — added `game_observer.h` to sources
- `server/game/game.h` — added optional `GameObserver*` param + `getRoundsPlayed()`
- `server/game/round.h` — wired observer through
- `server/game/trick.h` — wired observer through
- `server/game/remote_player.h` — removed `final` to allow subclassing
- `server/api/game_session.h` — added `starting_seq` param (default=1)
- `server/api/managed_connection.h` — added `addSession()`, generalized `ConnectionListener` predicate
- `server/util/constants.h` — added `ServerMsgTypes::Tournament::*`, `Tags::Tournament::*`, `ClientMsgTypes::TOURNAMENT_REGISTER`
- `server/util/logging.h` — simplified log format, JSON-Lines output
- `clients/python/util/Constants.py` — added `TournamentMsgTypes`, `TournamentTags`, `MoveSource`

---

## First Step: Build

```bash
bazel build --cxxopt=-std=c++17 --features=external_include_paths //server:tournament_server
```

### Known macOS build blocker
`boost.container` fails with Apple Clang (`BOOST_CONTAINER_STATIC_ASSERT` errors). This is the same issue that affected other targets — it works in CI (Linux) but not locally on Mac. The same pattern was used for the main `server` binary which does pass CI.

**Options:**
1. Push the branch and check CI — Linux build may just work.
2. Before pushing, check the potential compile issues below.

---

## Running the Test

Once built:
```bash
python3 competition_runner.py --non-interactive
```

This uses 3 pre-configured teams (alpha/beta/gamma) + 1 auto-detected filler team, runs qualifying + finals, writes results to `./results/`.

`--non-interactive` mode: port 40406, 20 qualifying games, 7 finals games, 4 players/team, teams alpha/alpha123, beta/beta456, gamma/gamma789.

---

## Potential Compile Issues to Verify First

Before pushing, read these files and check:

### 1. `server/util/env.h` — does `EnvironmentLoader` have a `has()` method?
`tournament_server.cpp` line 78 calls `EnvLoader.has("TOURNAMENT_PORT")`. If this method doesn't exist, either add it or change the code to use a try/catch or a default.

### 2. `server/api/game_session.h` — `send()` and `Setup()` signatures
`tournament_server.cpp` calls:
```cpp
session->Setup();
session->send({{ {Tags::TYPE, ...}, ... }});
```
Verify these method names and signatures match the actual class.

### 3. `server/game/game.h` — `Game` constructor signature
`tournament_server.cpp` does:
```cpp
Game::Game game(arr, nullLogger, observer.get());
game.runGame();
```
Verify the constructor takes `(PlayerArray, shared_ptr<GameLogger>, GameObserver*)`.

### 4. `server/game/remote_player.h` — `RemotePlayer` constructor
Called as:
```cpp
std::make_shared<RemotePlayer>(session->getPlayerTagSession(), session)
```
Verify this matches the actual constructor.

### 5. `clients/python/api/networking/ManagedConnection.py` — `message_store` structure
`TournamentSession.py` accesses `self.connection.message_store._id_to_received_messages[TOURNAMENT_CONTROL_SESSION].append(message)`. Verify `_id_to_received_messages` is a `defaultdict(list)`.

---

## Key Architecture Notes

### Sequence number trick
Server-initiated game sessions start at `seq=0` (server sends `start_game` first). Client-initiated sessions start at `seq=1` (client's setup was `seq=0`). Controlled by `starting_seq` param on `PlayerGameSession`.

### Tournament flow
1. Client connects → sends `tournament_register` (team, password, player_tag, priority_score)
2. Server responds with `tournament_queued` (contains `start_at` unix timestamp)
3. At `start_at`, server pushes `tournament_game_assignment` (game_session_id, game_id, stage) over control session
4. Client plays game normally on the new session_id
5. Server sends `tournament_stage_complete` after qualifying, `tournament_complete` after finals

### Control session routing (Python)
`TournamentSession._patch_handle_msg()` monkey-patches `ManagedConnection._handle_msg` to route tournament control messages to a special queue with `TOURNAMENT_CONTROL_SESSION = -2`.

### Filler teams
`competition_runner.py` creates filler teams with random passwords so there are always ≥4 teams. Each filler team spawns `max_players` client processes using randomly chosen player modules.
