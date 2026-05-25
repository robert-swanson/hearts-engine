#pragma once

#include <utility>

#include "objects/player.h"
#include "objects/types.h"
#include "trick.h"
#include "game_observer.h"

namespace Common::Game
{

class Round
{
public:
    explicit Round(int roundIndex, PlayerArray &players, PassDirection passDirection,
                   std::shared_ptr<GameLogger> gameLogger, GameObserver* observer = nullptr):
            mPlayers(players), mPassDirection(passDirection), mRoundIndex(roundIndex),
            mGameLogger(std::move(gameLogger)), mObserver(observer)
    {
    }

    void runDeal()
    {
        dealCards();
        notifyStartRound();
        passCards();

        if (mObserver)
        {
            std::map<std::string, std::vector<std::string>> hands;
            for (const auto& p : mPlayers)
            {
                auto& h = hands[p->getTagSession()];
                for (int i = 0; i < (int)p->getHand().size(); ++i)
                    h.push_back(p->getHand()[i].getAbbreviation());
            }
            mObserver->onHandsAfterPass(hands);
            mObserver->onStartRound(mRoundIndex, PassDirectionToString(mPassDirection));
        }

        size_t startingPlayer = getStartingPlayer();
        bool brokenHearts = false;
        for (int trickIndex = 0; trickIndex < Constants::NUM_TRICKS; trickIndex++)
        {
            PlayerArray trickPlayerOrder = LeftShiftArray(mPlayers, startingPlayer);
            Trick trick(trickPlayerOrder, trickIndex, brokenHearts, mGameLogger, mObserver);
            trick.RunTrick();
            mTricks.push_back(trick);
            brokenHearts |= trick.heartsBroken();
            startingPlayer = (trick.getTrickWinnerIdx() + startingPlayer) % Constants::NUM_PLAYERS;
            mPlayers[startingPlayer]->receiveTrick(trick.getPlayedCards());
        }
        scoreRound();
        notifyEndRound();
    }

private:
    void notifyStartRound()
    {
        for (PlayerRef & player : mPlayers)
            player->notifyStartRound(mRoundIndex, mPassDirection, player->getHand());
    }

    void notifyEndRound()
    {
        std::map<PlayerID, int> roundScores;
        for (PlayerRef & player : mPlayers)
            roundScores[player->getTagSession()] = mRoundScores[player->getTagSession()];
        for (PlayerRef & player : mPlayers)
            player->notifyEndRound(roundScores);
        if (mObserver)
            mObserver->onRoundComplete(mRoundIndex, roundScores);
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
            mPlayers[passTo]->notifyReceivedCards(passedCards[passFrom], passedCards[passTo]);
        }
    }

    int playerToPassTo(int fromPlayer)
    {
        int passTo;
        switch (mPassDirection)
        {
            case Left:   passTo = (fromPlayer + 1) % (int)Constants::NUM_PLAYERS; break;
            case Right:  passTo = (fromPlayer - 1); break;
            case Across: passTo = (fromPlayer + 2) % (int)Constants::NUM_PLAYERS; break;
            default:     passTo = fromPlayer; break;
        }
        if (passTo < 0) passTo += Constants::NUM_PLAYERS;
        return passTo;
    }

    int getStartingPlayer()
    {
        for (int playerI = 0; playerI < Constants::NUM_PLAYERS; playerI++)
        {
            if (mPlayers[playerI]->getHand().contains(Constants::STARTING_CARD))
                return playerI;
        }
        DIE("Unable to find player with starting card");
    }

    void scoreRound()
    {
        int totalScore = 0;
        std::string moonShooter;
        for (const auto& playerRef: mPlayers)
        {
            auto trickCards = playerRef->getReceivedTrickCards();
            size_t numHearts = trickCards.filter([](Card c){ return c.getSuit() == Suit::HEARTS; }).size();
            bool queen = trickCards.contains(Card(QUEEN, SPADES));
            int score = (int)numHearts + queen * Constants::QUEEN_SCORE;
            mRoundScores[playerRef->getTagSession()] = score;
            totalScore += score;

            if (score == Constants::MAX_TRICK_SCORE)
            {
                moonShooter = playerRef->getTagSession();
                for (const auto& p : mPlayers)
                    mRoundScores[p->getTagSession()] = Constants::MAX_TRICK_SCORE;
                mRoundScores[moonShooter] = 0;
                break;
            }
        }

        ASRT_EQ(totalScore, Constants::MAX_TRICK_SCORE);
        for (const auto& playerRef: mPlayers)
            playerRef->addPoints(mRoundScores[playerRef->getTagSession()]);

        if (mObserver && !moonShooter.empty())
            mObserver->onMoonShot(moonShooter);
    }

    PlayerArray mPlayers;
    PassDirection mPassDirection;
    int mRoundIndex;
    std::vector<Trick> mTricks;
    std::map<PlayerID, int> mRoundScores;
    std::shared_ptr<GameLogger> mGameLogger;
    GameObserver* mObserver;
};

}
