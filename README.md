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
2. `vi config.env` and make sure SERVER_PORT and SERVER_ADDR are pointing to a known server
3. `python clients/python/players/random_player.py`
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

If you wish to run a local instance of the game server do the following (untested):

1. `cd hearts-engine`
2. `./setup.sh` (this may take several minutes the first time)
   - If you get `cmake: command not found` install cmake with your package manager (e.g. on linux: `sudo apt-get install cmake`) and rerun
3. `cmake .`
4. `cmake --build --target Server`
5. `./Server config.env`


## Use a Player AI in a physical game of hearts
Any client implemented using the python API can automatically be used in a physical game of hearts provided a person can act as the go-between between the physical cards and the textual interface.
1. Look at the [TableGame.py](python/util/table_game/TableGame.py) and set `player_cls` to the client you want to use.
2. Run it: `python python/util/table_game/TableGame.py`
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


