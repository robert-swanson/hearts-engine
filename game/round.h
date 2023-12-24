#pragma once

#include "objects/player.h"
#include "objects/types.h"
#include "trick.h"

namespace Common::Game
{

class Round
{
public:
    explicit Round(int roundIndex, PlayerArray &players, PassDirection passDirection):
            mPlayers(players), mPassDirection(passDirection), mRoundIndex(roundIndex)
    {
    }

    void runDeal()
    {
        LOG("\n## Starting round in direction %d", mPassDirection);
        dealCards();
        notifyStartRound();
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
            mPlayers[startingPlayer]->receiveTrick(trick.getPlayedCards());
        }
        notifyEndRound();
        scoreRound();
    }

private:
    void notifyStartRound()
    {
        for (PlayerRef & player : mPlayers)
        {
            player->notifyStartRound(mRoundIndex, mPassDirection, player->getHand());
        }
    }

    void notifyEndRound()
    {
        std::map<PlayerID, int> roundScores;
        for (PlayerRef & player : mPlayers)
        {
            roundScores[player->getTagSession()] = player->getScore();
        }
        for (PlayerRef & player : mPlayers)
        {
            player->notifyEndRound(roundScores);
        }
    }

    void dealCards()
    {
        auto fullDeck = CardCollection::ShuffledDeck();
        auto hands = fullDeck.divide(Constants::NUM_PLAYERS);

        for (int i = 0; i < Constants::NUM_PLAYERS; i++)
        {
            mPlayers[i]->resetReceivedTrickCards();
            mPlayers[i]->assignHand(hands[i]);
        }

    }

    void passCards()
    {
        if (mPassDirection == Keeper)
            return;

        std::vector<CardCollection> passedCards;
        for (const auto& player: mPlayers)
        {
            auto cards = player->getCardsToPass(mPassDirection);
            ASRT_EQ(cards.size(), Constants::NUM_CARDS_TO_PASS);
            player->removeCardsFromHand(cards);
            passedCards.push_back(cards);
        }

        for (int passFrom = 0; passFrom < Constants::NUM_PLAYERS; passFrom++)
        {
            auto passTo = playerToPassTo(passFrom);
            mPlayers[passTo]->receiveCards(passedCards[passFrom]);
            mPlayers[passTo]->notifyReceivedCards(passedCards[passFrom]);
        }
    }

    int playerToPassTo(int fromPlayer)
    {
        int passTo;
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
            LOG("%s: %s", mPlayers[playerI]->getTagSession().c_str(), mPlayers[playerI]->getHand().getAbbreviation().c_str());
        }
        for(int playerI = 0; playerI < Constants::NUM_PLAYERS; playerI++)
        {
            if (mPlayers[playerI]->getHand().contains(Constants::STARTING_CARD))
            {
                return playerI;
            }
        }
        DIE("Unable to find player with starting card");
    }

    void scoreRound()
    {
        int totalScore = 0;
        for (const auto& playerRef: mPlayers)
        {
            auto receivedTrickCards = playerRef->getReceivedTrickCards();
            size_t numHearts = receivedTrickCards.filter([](Card card){return card.getSuit() == Suit::HEARTS;}).size();
            bool queen = receivedTrickCards.contains(Card(QUEEN, SPADES));
            int score = static_cast<int>(numHearts) + queen * Constants::QUEEN_SCORE;
            mRoundScores[playerRef->getTagSession()] = score;
            totalScore += score;

            if (score == Constants::MAX_TRICK_SCORE)
            {
                for (const auto& player: mPlayers)
                    mRoundScores[player->getTagSession()] = Constants::MAX_TRICK_SCORE;
                mRoundScores[playerRef->getTagSession()] = 0;
                break;
            }
        }

        ASRT_EQ(totalScore, Constants::MAX_TRICK_SCORE);
        for (const auto& playerRef: mPlayers)
        {
            playerRef->addPoints(mRoundScores[playerRef->getTagSession()]);
        }
    }

    PlayerArray mPlayers;
    PassDirection mPassDirection;
    int mRoundIndex;
    std::vector<Trick> mTricks;
    std::map<PlayerID, int> mRoundScores;
};

}