# Tournament Protocol

This document describes the full message flow for the two-stage Hearts tournament system. It covers four sequential phases: team registration, player registration, game play, and end notifications.

For the base game protocol (game sessions, rounds, tricks) see [`clients/README.md`](clients/README.md).

---

## Overview

Two separate servers run sequentially on the **same port** (default 40406):

```
competition_runner.py                     tournament_server (C++ binary)
  └── Registration listener (Python)        └── Tournament server
        Phase 1 only                              Phases 2–4
```

There are also two distinct registration steps:

| Phase | Who talks | Protocol | Purpose |
|-------|-----------|----------|---------|
| 1. Team registration | `register_team.py` → `competition_runner.py` | Simple JSON (custom) | Claim a team name/password before the competition starts |
| 2. Player registration | `tournament_client.py` → `tournament_server` | Hearts protocol | Connect a player client for an upcoming tournament |
| 3. Game sessions | `tournament_server` → `tournament_client.py` | Hearts protocol | Server assigns games; client plays them |
| 4. End notifications | `tournament_server` → `tournament_client.py` | Hearts protocol | Stage and tournament results |

---

## Phase 1 — Team Registration

Happens **before** the tournament server starts. `competition_runner.py` opens a TCP listener. Teams connect and claim a name/password. This listener uses a **custom, non-Hearts protocol** (plain JSON lines, no `session_id` or `seq_num`).

```
register_team.py                         competition_runner.py
     |                                   (registration listener)
     |   TCP connect to <addr>:40406          |
     |--------------------------------------> |
     |                                        |
     |   {"type": "register",                 |
     |    "team": "my_team",                  |
     |    "password": "secret"}               |
     |--------------------------------------> |
     |                                        |
     |   {"status": "ok"}                     |
     | <------------------------------------- |
     |   TCP close                            |
```

If the tournament client connects to this listener by mistake (e.g. started too early), it receives:

```json
{"type": "connection_response", "status": "registration_window_open"}
```

The client detects this and retries until the tournament server opens.

**Error responses:**
```json
{"status": "error", "message": "Team 'my_team' already registered with a different password"}
```

After the registration window closes, `competition_runner.py` writes the team list to `tournament_server.env` and starts the C++ `tournament_server` binary on the same port.

---

## Phase 2 — Player Registration

Once the tournament server is up, player clients connect and register. This uses the standard Hearts connection handshake followed by a `tournament_register` message.

```
tournament_client.py                      tournament_server (C++)
     |                                          |
     |   TCP connect to <addr>:40406            |
     |----------------------------------------> |
     |                                          |
     |   {"type": "connection_request"}         |
     |----------------------------------------> |
     |                                          |
     |   {"type": "connection_response",        |
     |    "status": "success"}                  |
     | <----------------------------------------|
     |                                          |
     |   {"type":           "tournament_register",
     |    "team_name":      "my_team",          |
     |    "password":       "secret",           |
     |    "player_tag":     "rob_player",       |
     |    "priority_score": 0,                  |
     |    "seq_num":        0}                  |
     |----------------------------------------> |
     |                                          |
     |   // Server internally creates a         |
     |   // PlayerGameSession and calls Setup() |
     |   {"type":       "game_session_response",|
     |    "session_id": 1042,                   |
     |    "status":     "success",              |
     |    "seq_num":    0}                      |
     | <----------------------------------------|
     |                                          |
     |   {"type":     "tournament_queued",      |
     |    "start_at": 1778955984,               |  ← unix timestamp
     |    "session_id": 1042,                   |
     |    "seq_num":  1}                        |
     | <----------------------------------------|
     |   (client waits for start_at)            |
```

> **Note on `game_session_response`:** This is sent by the server's internal `PlayerGameSession::Setup()` as reused infrastructure. The Python client routes it to an internal buffer and ignores it; only `tournament_queued` matters here.

**Bad credentials** — server closes the socket immediately (client retries):
```
     |   {"type": "tournament_register", ...bad creds...}
     |----------------------------------------> |
     |                                          |
     |   [TCP connection closed]                |
     | <----------------------------------------|
```

A team can connect **multiple player clients** (up to `MAX_PLAYERS_PER_TEAM`). Higher `priority_score` clients fill slots first.

---

## Phase 3 — Game Assignment and Play

At `start_at` the server builds rosters and schedules games. For each game a player is assigned to, the server sends a `tournament_game_assignment` over the player's **control session** (the one from Phase 2). The client then plays the game on a new session using the assigned `game_session_id`.

```
tournament_server (C++)                   tournament_client.py
     |                                          |
     |   {"type":            "tournament_game_assignment",
     |    "game_session_id": 1099,              |
     |    "game_id":         "qualifying_3",    |
     |    "stage":           "qualifying",      |
     |    "session_id":      1042,              |  ← control session ID
     |    "seq_num":         2}                 |
     |----------------------------------------> |
     |                                          |
     |   // Client spins up a thread for        |
     |   // session 1099 and plays the game     |
     |   // using the standard Hearts protocol  |
     |   // (start_game → rounds → end_game)    |
     |                                          |
     |   [game plays on session_id 1099]        |
     |   <-------- standard Hearts protocol --->|
     |                                          |
     |   // More game_assignment messages may   |
     |   // arrive concurrently for other games |
```

Multiple `tournament_game_assignment` messages can arrive concurrently. The client runs each game in its own thread, all multiplexed over the single TCP connection.

The game protocol on the new session is identical to the lobby server — see [`clients/README.md`](clients/README.md) for the full `start_game` → rounds → tricks → `end_game` flow.

---

## Phase 4 — Stage and Tournament Complete

After all qualifying games finish, the server sends stage results to every registered player. After finals, the tournament-complete message is sent.

```
tournament_server (C++)                   tournament_client.py
     |                                          |
     |   {"type":       "tournament_stage_complete",
     |    "stage":      "qualifying",           |
     |    "results":    {                       |
     |      "my_team/rob_player/0": 25,         |  ← tournament points
     |      "filler_1/random_player/1": 10,     |
     |      ...                                 |
     |    },                                    |
     |    "session_id": 1042,                   |
     |    "seq_num":    N}                      |
     |----------------------------------------> |
     |                                          |
     |   [finals games play — same as Phase 3]  |
     |                                          |
     |   {"type": "tournament_complete",        |
     |    "results": {                          |
     |      "qualifying_totals": {              |
     |        "my_team/rob_player/0": 25, ...   |
     |      },                                  |
     |      "finals_totals": {                  |
     |        "my_team/rob_player/0": 10, ...   |
     |      }                                   |
     |    },                                    |
     |    "session_id": 1042,                   |
     |    "seq_num":    M}                      |
     |----------------------------------------> |
     |                                          |
     |   [TCP connection closed by server]      |
     |                                          |
     |   // Client loops back and reconnects    |
     |   // for the next tournament cycle       |
```

Result keys use the full player ID format: `team/player_tag/slot_index/session_id`. Totals keys use the stable slot ID (without session): `team/player_tag/slot_index`.

---

## Message Reference

### Phase 1 (Registration Listener — custom protocol)

| Direction | Type | Key Fields |
|-----------|------|-----------|
| Client → Server | — | `type:"register"`, `team`, `password` |
| Server → Client | — | `status:"ok"` or `status:"error"`, `message` |
| Server → Client (early) | — | `type:"connection_response"`, `status:"registration_window_open"` |

### Phase 2–4 (Tournament Server — Hearts protocol)

| Direction | Type | Key Fields |
|-----------|------|-----------|
| Client → Server | `connection_request` | — |
| Server → Client | `connection_response` | `status:"success"` |
| Client → Server | `tournament_register` | `team_name`, `password`, `player_tag`, `priority_score`, `seq_num:0` |
| Server → Client | `game_session_response` | `session_id`, `status:"success"` *(ignore — internal infra)* |
| Server → Client | `tournament_queued` | `start_at` (unix timestamp) |
| Server → Client | `tournament_game_assignment` | `game_session_id`, `game_id`, `stage` |
| Server → Client | `tournament_stage_complete` | `stage`, `results` (slotId → pts) |
| Server → Client | `tournament_complete` | `results.qualifying_totals`, `results.finals_totals` |

All Phase 2–4 messages include `session_id` (the control session from Phase 2) and `seq_num`.

---

## File Architecture

### C++ (Server Side)

```
server/
├── tournament_server.cpp        Main binary — orchestrates the full tournament
│   ├── loadConfig()             Reads tournament_server.env (teams, rules, port)
│   ├── TournamentLobby          Accepts player registrations during Phase 2
│   │   └── handleRegister()     Validates team/password, creates PlayerGameSession,
│   │                            sends game_session_response + tournament_queued
│   ├── buildRoster()            Assigns registered players to slots (handles
│   │                            duplicates, fallback, priority scoring)
│   ├── scheduleGames()          Round-robin scheduling with 3-array fairness
│   ├── runOneGame()             Runs one 4-player game asynchronously, sends
│   │                            tournament_game_assignment to each player
│   ├── tabulateQualifyingPoints() Scores each game using the QUALIFYING_POINTS table
│   ├── selectFinalists()        Picks top-4 slots (one per team if multi-team=off)
│   ├── gameResultToSummaryJson() Builds per-game entry in summary.json
│   ├── gameResultToDetailJson() Builds games/<id>.json with round/trick detail
│   └── writeResults()          Writes results/ directory and competition.json index
│
├── api/
│   ├── managed_connection.h    ManagedConnection — multiplexes many sessions over
│   │                           one TCP socket; ConnectionListener dispatches
│   │                           incoming messages by session_id
│   ├── game_session.h          PlayerGameSession — wraps one player's slot in a game;
│   │                           owns seq_num counter, send/receive with timeout
│   └── connection.h            Base TCP socket; handleConnectionRequest() does the
│                               connection_request / connection_response handshake
│
└── game/
    ├── game.h                  Runs one 4-player game (13 rounds)
    ├── round.h                 Deals cards, handles passing, runs 13 tricks
    ├── trick.h                 Collects 4 moves, determines winner; fires observer
    │                           callbacks (onMove, onTrickComplete, onMoonShot, …)
    ├── remote_player.h         Sends start_game/start_trick/move_request to a
    │                           PlayerGameSession; receives donated_cards/decided_move
    └── game_observer.h         Observer interface used by RecordingObserver in
                                tournament_server.cpp to capture game data for JSON
```

**Key data flow (C++ side):**
```
acceptor.accept()
  → ManagedConnection constructed → handleConnectionRequest() → handshake
  → ConnectionListener thread started
    → message arrives with type="tournament_register"
      → handleRegister() → PlayerGameSession created → tournament_queued sent
    → [at start_at] runOneGame() called (async)
      → tournament_game_assignment sent on control session
      → Game::Game run with RemotePlayer instances
        → trick.h fires observer callbacks → RecordingObserver records data
      → game completes → GameResult returned
  → tabulateQualifyingPoints() → selectFinalists()
  → finals run the same way
  → tournament_stage_complete + tournament_complete sent
  → writeResults() → results/ directory written
```

---

### Python (Client Side)

```
competition_runner.py            Orchestrator — runs on the server host
  └── run_registration_listener()  Opens TCP listener for Phase 1 (custom protocol)
  └── write_config()               Writes tournament_server.env with TEAMS + rules
  └── start_filler_clients()       Launches tournament_client.py subprocesses for
                                   filler teams (with --host=127.0.0.1)
  └── run_competition()            Loop: start server → wait → sleep → repeat

register_team.py                 Run once by each competitor to claim a team slot
  └── Connects via TCP, sends {"type":"register",...}, saves creds to config.env

clients/python/
├── tournament_client.py         Entry point for competitor player clients
│   └── main()                   Retry loop: connect → register → run → reconnect
│
└── api/networking/
    ├── TournamentSession.py     High-level tournament protocol handler
    │   ├── TournamentSession    Manages the full lifecycle of one tournament cycle:
    │   │   ├── _patch_handle_msg()  Monkey-patches ManagedConnection._handle_msg
    │   │   │                        to route tournament control messages
    │   │   │                        (queued/assignment/complete) to a special
    │   │   │                        internal queue (session_id = -2) instead of
    │   │   │                        the normal session routing
    │   │   ├── register()       Sends tournament_register; waits for tournament_queued
    │   │   └── run()            Loops on control queue: spawns a thread per
    │   │                        game_assignment, waits for tournament_complete
    │   └── TournamentGameSession  Thin wrapper over ManagedConnection for one
    │                              server-initiated game session (seq_num tracking)
    │
    ├── ManagedConnection.py     Multiplexes sessions over one TCP connection;
    │                            receiver thread dispatches messages by session_id;
    │                            patched by TournamentSession to intercept control msgs
    └── Connection.py            Raw TCP socket + JSON framing;
                                 setup() does the connection_request handshake
```

**Key data flow (Python side):**
```
tournament_client.py
  → ManagedConnection created → Connection.setup() → handshake complete
  → TournamentSession created
      → _patch_handle_msg() installed on ManagedConnection
  → register() called
      → sends tournament_register
      → receiver thread started
      → game_session_response arrives → routed to normal session queue (ignored)
      → tournament_queued arrives → intercepted → routed to control queue (-2)
      → register() reads from control queue → returns
  → run() called
      → loops reading control queue (-2)
      → tournament_game_assignment → _run_game() thread spawned
          → TournamentGameSession wraps the assigned session_id
          → ActiveGame.run_game() executes the standard Hearts game loop
      → tournament_stage_complete → prints scores
      → tournament_complete → loop exits
  → game threads joined → results returned
  → outer retry loop reconnects for next tournament
```

---

## Player ID Format

Player IDs grow as the tournament progresses:

| Stage | Format | Example |
|-------|--------|---------|
| Team registered | `team` | `my_team` |
| Player registered (slot assigned) | `team/player_tag/slot_index` | `my_team/rob_player/0` |
| In-game (session assigned) | `team/player_tag/slot_index/session_id` | `my_team/rob_player/0/1042` |

- **`slot_index`** — which of the team's MAX_PLAYERS_PER_TEAM slots this player fills (stable within a tournament)
- **`session_id`** — unique per TCP registration (changes each tournament cycle)
- **Result totals** use the stable `team/player_tag/slot_index` form (without session)
- **In-game JSON** uses the full four-part form

---

## Lifecycle Summary

```
[competition_runner.py starts]
  │
  ├─ Phase 0: build tournament_server binary
  │
  ├─ Phase 1: registration listener (port 40406, Python, custom protocol)
  │     register_team.py ──→ {"type":"register","team":…,"password":…}
  │                    ←── {"status":"ok"}
  │     (window closes on timeout or Enter press)
  │
  ├─ tournament_server binary started (port 40406, C++)
  │
  ├─ Phase 2: player registration (Hearts protocol)
  │     tournament_client.py ──→ connection_request
  │                         ←── connection_response
  │                         ──→ tournament_register
  │                         ←── game_session_response  [ignore]
  │                         ←── tournament_queued
  │
  ├─ [start_at reached — rosters built, games scheduled]
  │
  ├─ Phase 3: qualifying games (parallel, repeated per assigned game)
  │                         ←── tournament_game_assignment
  │     [game plays on new session — standard Hearts protocol]
  │                         ←── tournament_stage_complete
  │
  ├─ Phase 3: finals games (same as qualifying)
  │
  ├─ Phase 4: results
  │                         ←── tournament_complete
  │     [TCP closed by server]
  │
  └─ [competition_runner.py sleeps INTERVAL seconds → next cycle]
       tournament_client.py reconnects and repeats from Phase 2
```
