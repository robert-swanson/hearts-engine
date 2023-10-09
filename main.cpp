#include "game/game.h"
#include "game/objects/constants.h"

using namespace Common::Game;

int main()
{
    Player player1 = {"A"};
    Player player2 = {"B"};
    Player player3 = {"C"};
    Player player4 = {"D"};
    std::array<Player, Common::Constants::NUM_PLAYERS> players = {player1, player2, player3, player4};
    Game game({player1, player2, player3, player4});
    game.runGame();
}