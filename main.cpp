#include "game/card.h"
#include "game/card_collection.h"

using namespace Common::Game;

int main()
{
    CardCollection deck;
    deck.shuffle();

    std::cout << deck.getAbbreviation() << std::endl;

    printf("Num mCards: %lu\n", deck.size());
}