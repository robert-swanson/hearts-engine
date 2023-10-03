#include "game/card.h"


int main()
{
    Common::Game::Card card(Common::Game::Rank::THREE, Common::Game::Suit::HEARTS);

    std::cout << card.getDescription() << std::endl;
    std::cout << card.getAbbreviation() << std::endl;
}