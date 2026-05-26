# Hearts Card Game Service

This project aims to provide a platform for people to easily implement players for the game of hearts and compete them against each other.
It includes 
1. A game server (C++) which mediates games between client players 
   - Can be built and run locally, or you can use the server hosted at `hearts.radiswanson.org:40405` (default config)
   - The server also implements logic for matching players to games (currently only first come first match)
2. A [python API](#running-a-client) for easily implementing and running client players
   - Supports multiple concurrent running sessions and games
   - Supports playing physical games against any implemented player
3. (TODO) A database for storing game actions and results for aggregated analysis or model training
   

## Running a Client
Each of the four players are controlled by a client which communicates its moves to the server. The server will then relay the moves to the other clients.

1. After cloning the repository, `cd hearts-engine`
2. Edit `config.env` (or `local.config.env`) so `SERVER_ADDR` and `SERVER_PORT` point to the server you want to play against.
   The Python client reads `./config.env` by default; pass a different file as the first positional arg to use it instead, e.g.
   `python3 clients/python/players/random_player.py local.config.env`
3. `python3 clients/python/players/random_player.py`
   ```txt
   Connected to hearts.radiswanson.org:40405
   Scores:
      random_player(56): 106
      random_player(57): 78
      random_player(58): 97
      random_player(59): 57
   ```
See the [clients/README.md](clients/README.md) for more information on implementing a client.


## Setting a local server

If you wish to run a local instance of the game server do the following:

1. `cd hearts-engine`
2. Install Bazel 9+ (if not already installed): `scripts/install_bazel.sh`
3. Build and run the server: `bazel run //server:server -- "$(pwd)/config.env"`

**macOS firewall:** if the macOS Application Firewall is enabled, you need to allow inbound connections to the server binary once after each clean build (the path is stable across incremental rebuilds):
```bash
REAL_BIN=$(python3 -c "import os; print(os.path.realpath('bazel-bin/server/tournament_server'))")
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add "$REAL_BIN"
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp "$REAL_BIN"
```
This also applies to the `tournament_server` binary used by `competition_runner.py`. Without it, external clients (including other machines on your LAN) will see their connections refused.


## Running a competition

The repo ships a `competition_runner.py` orchestrator and a separate `tournament_server` binary for recurring, two-stage (qualifying + finals) competitions.  The competition has one registration phase up front, then runs tournaments in a loop indefinitely — competitor clients reconnect automatically for each cycle without re-registering.

### Organiser (run on the server host)

```bash
python3 competition_runner.py        # prompts for rules, then opens registration
```

The runner builds the `tournament_server` binary, then opens a registration listener. Once you press Enter to close the window, it loops forever: start server → run qualifying + finals → write JSON to `./results/` → sleep → repeat.

For non-interactive / scripted use:
```bash
python3 competition_runner.py --non-interactive [--registration-window=30] [--interval=300]
```

### Competitor (run on each team's machine)

**Step 1 — register your team** (do this once, while the organiser's registration window is open):
```bash
python3 register_team.py             # prompts for team name + password
```
If the server isn't on localhost, pass the organiser's config file:
```bash
python3 register_team.py path/to/organisers/tournament.config.env
```
This saves credentials to `team.config.env` (gitignored).

**Step 2 — start your player client(s)** (leave running for the whole competition):
```bash
python3 clients/python/tournament_client.py --player=my_player
```
The client retries until the first tournament server opens, plays, then automatically reconnects for every subsequent tournament. Run multiple clients with different `--player` or `--score` values to fill more slots.

> **Note for Claude / scripted use:** poll `nc -z 127.0.0.1 40406` until it succeeds before running `register_team.py --team=<name> --password=<pw>`. Start `tournament_client.py` processes immediately after — they retry automatically once the server opens.

See [`server/tournament_server.cpp`](server/tournament_server.cpp) for the full set of config keys.


## Use a Player AI in a physical game of hearts

Any AI player can advise one or more seats at a real table. A human acts as the go-between — entering cards as they are dealt and played.

```bash
python3 clients/python/util/table_game/TableGame.py
```

On startup it shows the available AI strategies and prompts you to configure all four seats:

```
Available AI strategies:
  rob                  (RobPlayer)
  rob_claude           (RobClaudePlayer)
  random               (RandomPlayer)
  madison              (MadisonPlayer)
  ...

Seat 1: Alice          → Human: Alice
Seat 2: rob            → AI: RobPlayer (tag: rob_player)
Seat 3: Bob            → Human: Bob
Seat 4: rob_claude     → AI: RobClaudePlayer (tag: rob_claude_player)
```

Enter a player name for human seats, or a strategy keyword for AI seats. Any number of seats (0–4) can be AI-controlled.

### During the game

Follow the prompts to enter each player's hand and the cards played each trick. When it is an AI seat's turn the AI picks a card and instructs you to play it; for all other seats you type the card that was played.

**Typing `undo`** when prompted for a card reverses the last human-entered card:
- If the mistake happened after the AI's last decision it is undone instantly (no rebuild needed).
- If it happened before an AI decision the AI is torn down and replayed from the corrected history.

### Card notation

Cards are two case-insensitive characters — rank then suit:

| Example | Meaning |
|---------|---------|
| `2C` | 2 of clubs |
| `QS` | queen of spades |
| `TD` | ten of diamonds |
| `AH` | ace of hearts |

Multiple cards can be entered space- or comma-separated (`2C QS 8D`), or grouped by suit (`C: 2 5 8 J A`).

## Contributing
Please feel free to add player clients or contribute to the project in seperate branches. Please open PRs for those branches and contact me to review and merge them to `main`

