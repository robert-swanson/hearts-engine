# Implementing a Python Client

This document describes how to use the provided python api to implement a client for the hearts game. See the [clients/README.md](../README.md) for more information on the protocol it implements.

See [`random_player.py`](players/random_player.py) for a simple example on how to implement a player.


## Summary

The python client API uses class inheritance to express the playing logic of a player through function calls and class instance state. 
The API assures that these methods are called in the correct order according to the game protocol, regardless of concurrent sessions.
After implementing the player protocol, a main method should be implemented that instantiates the connection and session.

## Implementing a Player
Players should extend the [`Player`](api/Player.py) class and implement at least the 2 abstract methods:
1. `get_cards_to_pass(self, pass_dir: PassDirection, receiving_player: PlayerTagSession) -> List[Card]`
2. `get_move(self, trick: Trick, legal_moves: List[Card]) -> Card`
 
The other methods serve to notify the player of game events, allow them changes to state, and also possibly spin off a new thread to start asynchronous logic.

See the docstrings in [`Player`](api/Player.py) for more details on each method, their params, and return values.

## Instantiating Connections and Sessions
A connection can be established as follows:
```python
from clients.python.api.networking.ManagedConnection import ManagedConnection

with ManagedConnection() as connection:
    pass
    # use connection
# will wait for any sessions to finish before closing the connection and exiting the block
```
    
Several utility functions are included in [`SessionHelpers.py`](api/networking/SessionHelpers.py) that allow for different ways to start sessions:
1. `MakeSession`: Request a new game session on the provided connection, and set up a thread ready to run the session
2. `MakeAndRunSession`: Request a new game session and run the session in a thread
3. `MakeAndRunMultipleSessions`: Request and run multiple game sessions in parallel
4. `WaitForAllSessionsToFinish`: Block until all sessions have finished (and log blocking sessions)
5. `RunGame`: Spin up 4 players to play a game together and wait until they finish
6. `RunMultipleGames`: Spins up multiple synchronous games based on the provided players (based on the value of MAX_CONCURRENT_SESSIONS)

You can read the [documentation](api/networking/SessionHelpers.py) for these methods for examples on each of these, but a common use case for testing a new player would be to run it against 3 random players:

```python
    players = [RobPlayer, RandomPlayer, RandomPlayer, RandomPlayer]
    total_games = 0
    games_won = 0
    start_time = time.time()

    with ManagedConnection("rob_player") as connection:
        games = RunMultipleGames(connection, GameType.ANY, players, 100)
        for game_result in games:
            if "rob_player" in str(game_result[0].winner):
                games_won += 1
            total_games += 1

    print(f"Games won: {games_won}/{total_games} ({games_won / total_games * 100}%)")
    print(f"Time: {time.time() - start_time}")
```


## Testing
There are a few ways you might want to go about testing your player:
1. Run it on the server against random players (as demonstrated above)
    - Good for running a large number of games to get an aggregate win rate or test more scenarios
    - Hard to get a sense for the actual strategy in individual games (would require checking logs or adding print statements)
2. Use the [`DebuggerPlayer`](players/debugger_player.py) class type to add an interactive CLI for each decision made by the player
    - Good for seeing the decisions made by the player in individual games
    - *Make sure you change the superclass of DebuggerPlayer to the player you want to test*
3. Play a physical game (aka [table game](util/table_game/TableGame.py)) of hearts and use your player to make decisions
    - Good for putting your player in a more realistic scenario, and to show off its performance to others
    - Be sure to set `player_cls` to your player class in the `TableGame` class
