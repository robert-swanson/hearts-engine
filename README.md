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

## Leaderboard
_Results for existing clients as of Aug 9, 2016 at http://hearts.radiswanson.org/c/2026-8-9_18-54-33.242/t/1_ 
### Rules:
| Rule                          | Values         |
|-------------------------------|----------------|
| Qualifying games per player   | 100            |
| Finals games                  | 400            |
| Qualifying points (1st–4th)   | 10 / 5 / 3 / 1 |
| Max players per team          | 4              |
| Allow multi-team finals       | No             |
| Move timeout                  | 5000 ms        |
| Auto-move after timeouts      | 4              |
| Max concurrent games per team | 4              |
| Fallback player tag           | none           |

### Qualifying
(Each player gets 100 games against random opponents in random table order)
| Rank | Player                            | Avg Tournament Points | Num Games | Games Won | Avg Game Score | Moon Shots | Timeout Games |
|------|-----------------------------------|-----------------------|-----------|-----------|----------------|------------|---------------|
| 1    | rob_prob_player                   | 7.16                  | 100       | 50        | 50.71          | 3          | 0             |
| 2    | tim_claude_player_moon_aggressive | 5.88                  | 100       | 38        | 63.26          | 48         | 0             |
| 3    | tim_claude_player_moon_reckless   | 5.62                  | 100       | 33        | 63.57          | 64         | 0             |
| 4    | rob_player                        | 5.30                  | 100       | 22        | 65.25          | 6          | 0             |
| 5    | rob_claude_player                 | 5.09                  | 100       | 27        | 73.46          | 6          | 0             |
| 6    | tim_claude_heuristic              | 3.97                  | 100       | 15        | 80.73          | 27         | 0             |
| 7    | madison_player                    | 1.82                  | 100       | 4         | 100.43         | 6          | 0             |
<img width="942" height="665" alt="image" src="https://github.com/user-attachments/assets/af414176-9ff0-4fc0-8bc3-e5b01caaf16a" />


### Finals
(Top 4 scorers from qualifying pitted against each other in 400 games of random table order. Ensures winner is actually better than second place)
| Rank |               Player              | Avg tournament points | Total games | Games won | Total tournament points | Avg game score | Moon shots | Timeout games |
|:----:|:---------------------------------:|:---------------------:|:-----------:|:---------:|:-----------------------:|:--------------:|:----------:|:-------------:|
| 1    | rob_prob_player                   | 6.02                  | 400         | 147       | 2409                    | 66.92          | 14         | 0             |
| 2    | tim_claude_player_moon_reckless   | 4.75                  | 400         | 103       | 1902                    | 78.14          | 254        | 0             |
| 3    | tim_claude_player_moon_aggressive | 4.34                  | 400         | 85        | 1736                    | 80.31          | 155        | 0             |
| 4    | rob_player.                       | 3.88                  | 400         | 65        | 1553                    | 84.42          | 38         | 0             |
<img width="948" height="615" alt="image" src="https://github.com/user-attachments/assets/8f26ed63-aad2-4b03-9f6f-df6a0f3c3f60" />


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
This saves credentials to `config.env` (gitignored).

To register **several teams from one machine**, give each its own env file with `--env-file`:
```bash
python3 register_team.py --team=alpha --password=a --env-file=alpha.env
python3 register_team.py --team=beta  --password=b --env-file=beta.env
```

**Step 2 — start your player client(s)** (leave running for the whole competition):
```bash
python3 clients/python/tournament_client.py --player=my_player
```
The client retries until the first tournament server opens, plays, then automatically reconnects for every subsequent tournament. Run multiple clients with different `--player` or `--score` values to fill more slots. To run a team whose credentials are in a non-default file, point the client at it:
```bash
python3 clients/python/tournament_client.py --env-file=alpha.env --player=my_player
```

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

## Latencies of Players When all Run on Tournament Server
| slot                              | pts     | avg s2c | avg c2s | avg think | max s2c | max c2s | max think | max total |
|-----------------------------------|---------|---------|---------|-----------|---------|---------|-----------|-----------|
| rob_prob_player                   | 716 pts | 48ms    | 1ms     | 22ms      | 317ms   | 117ms   | 766ms     | 789ms     |
| rob_prob_player                   | 685 pts | 47ms    | 1ms     | 22ms      | 375ms   | 100ms   | 513ms     | 620ms     |
| rob_prob_player                   | 676 pts | 48ms    | 1ms     | 22ms      | 379ms   | 62ms    | 759ms     | 761ms     |
| rob_prob_player                   | 638 pts | 48ms    | 1ms     | 23ms      | 332ms   | 82ms    | 491ms     | 560ms     |
| tim_claude_player_moon_aggressivr | 588 pts | 0ms     | 0ms     | 0ms       | 151ms   | 8ms     | 230ms     | 231ms     |
| tim_claude_player_moon_recklesr   | 562 pts | 0ms     | 0ms     | 0ms       | 93ms    | 41ms    | 2ms       | 93ms      |
| tim_claude_player_moon_aggressivr | 562 pts | 0ms     | 0ms     | 0ms       | 21ms    | 10ms    | 50ms      | 49ms      |
| tim_claude_player_moon_recklesr   | 549 pts | 0ms     | 0ms     | 0ms       | 166ms   | 5ms     | 2ms       | 165ms     |
| tim_claude_player_moon_aggressivr | 548 pts | 0ms     | 0ms     | 0ms       | 51ms    | 9ms     | 2ms       | 50ms      |
| tim_claude_player_moon_aggressivr | 539 pts | 0ms     | 0ms     | 0ms       | 83ms    | 10ms    | 2ms       | 83ms      |
| rob_player_der                    | 530 pts | 1ms     | 0ms     | 0ms       | 206ms   | 11ms    | 2ms       | 207ms     |
| rob_player_der                    | 512 pts | 1ms     | 0ms     | 0ms       | 78ms    | 13ms    | 4ms       | 78ms      |
| rob_claude_player                 | 509 pts | 0ms     | 0ms     | 0ms       | 39ms    | 11ms    | 2ms       | 39ms      |
| rob_player_der                    | 508 pts | 1ms     | 0ms     | 0ms       | 122ms   | 7ms     | 24ms      | 122ms     |
| tim_claude_player_moon_recklesr   | 500 pts | 0ms     | 0ms     | 0ms       | 98ms    | 7ms     | 2ms       | 98ms      |
| tim_claude_player_moon_recklesr   | 494 pts | 0ms     | 0ms     | 0ms       | 148ms   | 5ms     | 2ms       | 149ms     |
| rob_player_der                    | 479 pts | 1ms     | 0ms     | 0ms       | 158ms   | 18ms    | 2ms       | 161ms     |
| rob_claude_player                 | 474 pts | 0ms     | 0ms     | 0ms       | 40ms    | 6ms     | 1ms       | 40ms      |
| rob_claude_player                 | 455 pts | 0ms     | 0ms     | 0ms       | 155ms   | 15ms    | 4ms       | 155ms     |
| rob_claude_player                 | 451 pts | 0ms     | 0ms     | 0ms       | 131ms   | 4ms     | 101ms     | 132ms     |
| tim_claude_heuristir              | 397 pts | 0ms     | 0ms     | 0ms       | 28ms    | 9ms     | 48ms      | 47ms      |
| tim_claude_heuristir              | 384 pts | 0ms     | 0ms     | 0ms       | 163ms   | 5ms     | 2ms       | 163ms     |
| tim_claude_heuristir              | 366 pts | 0ms     | 0ms     | 0ms       | 161ms   | 5ms     | 102ms     | 160ms     |
| tim_claude_heuristir              | 366 pts | 0ms     | 0ms     | 0ms       | 11ms    | 3ms     | 2ms       | 10ms      |
| madison_player                    | 253 pts | 0ms     | 0ms     | 0ms       | 59ms    | 4ms     | 1ms       | 59ms      |
| madison_player                    | 191 pts | 0ms     | 0ms     | 0ms       | 120ms   | 5ms     | 73ms      | 120ms     |
| madison_player                    | 186 pts | 0ms     | 0ms     | 0ms       | 125ms   | 13ms    | 1ms       | 125ms     |
| madison_player                    | 182 pts | 0ms     | 0ms     | 0ms       | 127ms   | 9ms     | 2ms       | 127ms     |

