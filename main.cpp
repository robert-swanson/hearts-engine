#include "game/game.h"
#include "game/objects/constants.h"

using namespace Common::Game;

int main()
{
    Player player1 = Player{"A"};
    Player player2 = Player{"B"};
    Player player3 = Player{"C"};
    Player player4 = Player{"D"};
    std::array<Player, Common::Constants::NUM_PLAYERS> players = {player1, player2, player3, player4};
    Game game({player1, player2, player3, player4});
    game.runGame();
}