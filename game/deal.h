#pragma once

#include "objects/player.h"
#include "objects/types.h"
#include "trick.h"

namespace Common::Game
{

class Deal
{
public:
    explicit Deal(PlayerArray &players, PassDirection passDirection):
            mPlayers(players), mPassDirection(passDirection)
    {
    }

    void runDeal()
    {
        LOG("Starting deal in direction %d", mPassDirection);
        dealCards();
        passCards();
        size_t startingPlayer = getStartingPlayer();
        bool brokenHearts = false;
        for (int trickIndex = 0; trickIndex < Constants::NUM_TRICKS; trickIndex++)
        {
            PlayerArray trickPlayerOrder = LeftShiftArray(mPlayers, startingPlayer);
            Trick trick(trickPlayerOrder, trickIndex, brokenHearts);
            trick.RunTrick();
            mTricks.push_back(trick);
            brokenHearts |= trick.heartsBroken();
            startingPlayer = (trick.getTrickWinner() + startingPlayer) % Constants::NUM_PLAYERS;
            mPlayers[startingPlayer].get().receiveTrick(trick.getPlayedCards());
        }
        scoreDeal();
    }

private:
    void dealCards()
    {
        auto fullDeck = CardCollection::ShuffledDeck();
        auto hands = fullDeck.divide(Constants::NUM_PLAYERS);

        for (int i = 0; i < Constants::NUM_PLAYERS; i++)
        {
            Player & player = mPlayers[i].get();
            player.resetReceivedTrickCards();
            player.assignHand(hands[i]);
        }

    }

    void passCards()
    {
        if (mPassDirection == Keeper)
            return;

        std::vector<CardCollection> passedCards;
        for (PlayerRef player: mPlayers)
        {
            auto cards = player.get().getCardsToPass(mPassDirection);
            ASRT_EQ(cards.size(), Constants::NUM_CARDS_TO_PASS);
            passedCards.push_back(cards);
        }

        for (int passFrom = 0; passFrom < Constants::NUM_PLAYERS; passFrom++)
        {
            auto passTo = playerToPassTo(passFrom);
            mPlayers[passTo].get().receiveCards(passedCards[passFrom]);
        }
    }

    int playerToPassTo(int fromPlayer)
    {
        int passTo = fromPlayer;
        switch (mPassDirection)
        {
            case Left:
                passTo = (fromPlayer + 1) % static_cast<int>(Constants::NUM_PLAYERS);
                break;
            case Right:
                passTo = (fromPlayer - 1) % static_cast<int>(Constants::NUM_PLAYERS);
                break;
            case Across:
                passTo = (fromPlayer + 2) % static_cast<int>(Constants::NUM_PLAYERS);
                break;
            default:
                passTo = fromPlayer;
                break;
        }
        if (passTo < 0)
            return passTo + Constants::NUM_PLAYERS;
        else
            return passTo;
    }

    int getStartingPlayer()
    {
        for(int playerI = 0; playerI < Constants::NUM_PLAYERS; playerI++)
        {
            LOG("%s: %s", mPlayers[playerI].get().getName().c_str(), mPlayers[playerI].get().getHand().getAbbreviation().c_str());
        }
        for(int playerI = 0; playerI < Constants::NUM_PLAYERS; playerI++)
        {
            if (mPlayers[playerI].get().getHand().contains(Constants::STARTING_CARD))
            {
                return playerI;
            }
        }
        DIE("Unable to find player with starting card");
    }

    void scoreDeal()
    {
        int scores[Constants::NUM_PLAYERS];
        int totalScore = 0;
        for (int playerI = 0; playerI < Constants::NUM_PLAYERS; playerI++)
        {
            auto receivedTrickCards = mPlayers[playerI].get().getReceivedTrickCards();
            size_t numHearts = receivedTrickCards.filter([](Card card){return card.getSuit() == Suit::HEARTS;}).size();
            bool queen = receivedTrickCards.contains(Card(QUEEN, SPADES));
            int score = static_cast<int>(numHearts) + queen * Constants::QUEEN_SCORE;
            scores[playerI] = score;
            totalScore += score;
            if (scores[playerI] == Constants::MAX_TRICK_SCORE)
            {
                for (int & playerScore : scores)
                    playerScore = Constants::MAX_TRICK_SCORE;
                scores[playerI] = 0;
                break;
            }
        }

        ASRT_EQ(totalScore, Constants::MAX_TRICK_SCORE);
        for (int playerI = 0; playerI < Constants::NUM_PLAYERS; playerI++)
        {
            mPlayers[playerI].get().addPoints(scores[playerI]);
        }
    }

    PlayerArray mPlayers;
    PassDirection mPassDirection;
    std::vector<Trick> mTricks;
};

}