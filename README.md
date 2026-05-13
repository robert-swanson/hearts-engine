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
3. Add the project directory to your PYTHONPATH
   * `export PYTHONPATH=$PYTHONPATH:$(pwd)`
   * or if you don't want to do that each time `echo "export PYTHONPATH=\$PYTHONPATH:$(pwd)" >> ~/.bashrc`
4. `python3 clients/python/players/random_player.py`
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


## Running a competition

The repo ships a `competition_runner.py` orchestrator and a separate `tournament_server` binary for running recurring, two-stage (qualifying + finals) competitions.

### How it works

A competition has one registration phase followed by a recurring tournament loop:

1. **Registration** (once) — `competition_runner.py` opens a TCP listener. Competitors connect via `register_team.py` to claim a team name and password. When the organiser closes the window, the runner records all registered teams and enters the loop.
2. **Tournament loop** — for each cycle: pad registered teams to 4 with filler bots if needed, write `tournament.config.env`, start the tournament server, run qualifying + finals, write JSON results to `./results/`, sleep the configured interval, repeat. Competitor clients (`tournament_client.py`) reconnect automatically for each cycle without re-registering.

### Organiser (server host)

```bash
# Interactive — prompts for port, game counts, registration window duration, etc.
python3 competition_runner.py

# Non-interactive — built-in defaults, useful for smoke-testing or scripted runs
python3 competition_runner.py --non-interactive [--registration-window=30] [--interval=60]
```

> **Note for Claude / scripted use:** use `--non-interactive` with explicit `--registration-window=N` (seconds) and `--interval=N`. To register teams programmatically during the window, run `register_team.py --team=<name> --password=<pw>` once per team while the listener is open (poll port 40406 with `nc -z 127.0.0.1 40406` until it accepts). Then start `tournament_client.py` processes (they retry automatically until the tournament server opens after the window closes).

### Competitor

```bash
# Step 1 — during the registration window, claim your team name and password.
# The organiser's server address is needed only if they're not on localhost.
python3 register_team.py [--team=my_team --password=secret] [tournament.config.env]

# Step 2 — start one client per player slot you want to fill, then leave it running.
# It connects when the first tournament server opens and automatically reconnects
# for every subsequent tournament — no re-registration needed.
python3 clients/python/tournament_client.py --player=my_player [--score=N]
```

`register_team.py` saves credentials to `team.config.env` (gitignored); `tournament_client.py` reads them automatically — no `--team`/`--password` flags needed after that. A team with one client registered gets all four of its slots on the same connection. Multiple clients with different `--player` or `--score` values spread across slots.

See [`server/tournament_server.cpp`](server/tournament_server.cpp) for the full set of config keys and [`clients/python/api/networking/TournamentSession.py`](clients/python/api/networking/TournamentSession.py) for the client-side protocol.


## Use a Player AI in a physical game of hearts
Any client implemented using the python API can automatically be used in a physical game of hearts provided a person can act as the go-between between the physical cards and the textual interface.
1. Look at the [TableGame.py](clients/python/util/table_game/TableGame.py) and set `player_cls` to the client you want to use.
2. Run it: `python3 clients/python/util/table_game/TableGame.py`
3. Populate the player names (you are treated as player 1) starting with the person to your left
4. Follow the prompts to input cards dealt to the player and take actions when instructed

Cards are expressed as two case-insensitive characters, the rank and suit, e.g.:
- `2C` is the 2 of clubs
- `QH` is the queen of hearts
- `AS` is the ace of spades
- `TD` is the ten of diamonds

A list of cards can be expressed as a space (or comma) seperated list of cards, e.g.: `2C QS 8D`

Or it can be expressed as a suit followed by ranks of that suit:
```txt
...
Starting hand, card 1/13: C: 2 5 8 J A
Starting hand, card 6/13: D: 3 A
Starting hand, card 8/13: QS
Starting hand, card 9/13: H: 5 7 8 9
Starting hand, card 13/13: 9H
Duplicate card(s): {9H}
Starting hand, card 13/13: TH
Pass [AD, AC, QS] Left to Ted(2) (press enter to continue)
...
```

## Contributing
Please feel free to add player clients or contribute to the project in seperate branches. Please open PRs for those branches and contact me to review and merge them to `main`

