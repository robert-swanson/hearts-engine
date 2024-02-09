# Hearts Card Game Service

This project includes a game matching server (C++) which can mediate games between client players.

## Running a Client
Each of the four players are controlled by a client which communicates its moves to the server. The server will then relay the moves to the other clients.

1. After cloning the repository, `cd hearts-engine`
2. `vi config.env` and make sure SERVER_PORT and SERVER_ADDR are pointing to a known server
3. 


## Setting up the Server

If you wish to run a local instance of the game server do the following:

1. `cd hearts-engine`
2. `./setup.sh` (this may take several minutes the first time)
   - If you get `cmake: command not found` install cmake with your package manager (e.g. on linux: `sudo apt-get install cmake`) and rerun
3. `cmake .`
4. `cmake --build --target Server`
5. `
