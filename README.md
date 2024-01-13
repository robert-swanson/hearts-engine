# Hearts Card Game Service

This project includes a game matching server (C++) which can mediate games between client players.

## Setting up the Server

If you wish to run a local instance of the game server do the following:

1. `cd hearts-engine`
2. `./setup.sh` (this may take several minutes the first time)
   - If you get `cmake: command not found` install cmake with your package manager (e.g. on linux: `sudo apt-get install cmake`) and rerun
3. `cmake .`
4. `cmake --build --target Server`
5. `
