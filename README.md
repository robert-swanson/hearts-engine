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

