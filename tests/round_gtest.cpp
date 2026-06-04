#include <gtest/gtest.h>

#include <map>
#include <set>
#include <string>
#include <vector>

#include "server/game/round.h"
#include "server/game/game.h"
#include "server/game/game_observer.h"
#include "server/game/objects/player.h"
#include "server/game/objects/card_collection.h"
#include "server/game/objects/constants.h"

using namespace Common::Game;

namespace {

// Minimal concrete player: passes its first 3 cards, always plays the first
// legal move. Each instance has a unique tag so observer maps don't collide.
class TestPlayer final : public Player {
public:
    explicit TestPlayer(const std::string& tag) : Player(tag) {}

    void notifyStartGame(std::vector<PlayerID>) override {}
    void notifyStartRound(int, PassDirection, CardCollection) override {}
    CardCollection getCardsToPass(PassDirection) override {
        auto h = getHand();
        std::vector<Card> v{h[0], h[1], h[2]};
        return CardCollection(v);
    }
    void notifyReceivedCards(const CardCollection&, const CardCollection&) override {}
    void notifyStartTrick(int, std::vector<PlayerID>) override {}
    Card getMove(const CardCollection& legalPlays) override { return legalPlays[0]; }
    void notifyMove(PlayerID, Card, bool) override {}
    void notifyEndTrick(PlayerID) override {}
    void notifyEndRound(std::map<PlayerID, int>&) override {}
    void notifyEndGame(std::map<PlayerID, int>&, PlayerID) override {}
};

// Captures hands_after_passing and the cards each player actually plays.
class CapturingObserver final : public GameObserver {
public:
    std::vector<std::map<std::string, std::vector<std::string>>> handsCaptures;
    std::map<std::string, std::set<std::string>> played;

    void onHandsAfterPass(const std::map<std::string, std::vector<std::string>>& hands) override {
        handsCaptures.push_back(hands);
    }
    void onTrickComplete(const std::vector<std::string>& playerOrder,
                         const std::vector<std::string>& cards,
                         const std::vector<std::string>& /*moveSources*/,
                         const std::string&, int) override {
        for (size_t k = 0; k < playerOrder.size() && k < cards.size(); ++k)
            played[playerOrder[k]].insert(cards[k]);
    }
};

PlayerArray makePlayers() {
    return PlayerArray{
        std::make_shared<TestPlayer>("p0"),
        std::make_shared<TestPlayer>("p1"),
        std::make_shared<TestPlayer>("p2"),
        std::make_shared<TestPlayer>("p3"),
    };
}

} // namespace

// Mirrors RecordingObserver in tournament_server.cpp: a round record is created
// on onStartRound, hands are written into the current record, and tricks
// accumulate the cards each player plays in that round.
class StoringObserver final : public GameObserver {
public:
    struct RoundRec {
        std::map<std::string, std::vector<std::string>> hands;
        std::map<std::string, std::set<std::string>> played;
    };
    std::vector<RoundRec> rounds;

    void onStartRound(int, const std::string&) override { rounds.emplace_back(); }
    void onHandsAfterPass(const std::map<std::string, std::vector<std::string>>& hands) override {
        if (!rounds.empty()) rounds.back().hands = hands;
    }
    void onTrickComplete(const std::vector<std::string>& playerOrder,
                         const std::vector<std::string>& cards,
                         const std::vector<std::string>& /*moveSources*/,
                         const std::string&, int) override {
        if (rounds.empty()) return;
        for (size_t k = 0; k < playerOrder.size() && k < cards.size(); ++k)
            rounds.back().played[playerOrder[k]].insert(cards[k]);
    }
};

// Every round's stored hands (including the last) must match that round's play.
// Regression test for the onHandsAfterPass/onStartRound ordering bug.
TEST(RoundHandsCapture, EveryRoundStoredHandsMatchPlay_FullGame) {
    auto players = makePlayers();
    StoringObserver obs;
    Game game(players, std::make_shared<Common::GameLogger>(stdout), &obs);
    game.runGame();

    ASSERT_GT(obs.rounds.size(), 1u);
    for (size_t i = 0; i < obs.rounds.size(); ++i) {
        const auto& r = obs.rounds[i];
        ASSERT_EQ(r.hands.size(), Common::Constants::NUM_PLAYERS)
            << "round " << i << " has no stored hands";
        for (const auto& [tag, cards] : r.hands) {
            std::set<std::string> handSet(cards.begin(), cards.end());
            EXPECT_EQ(handSet, r.played.at(tag))
                << "round " << i << " stored hands for " << tag
                << " do not match that player's play";
        }
    }
}

// The post-pass hand reported via onHandsAfterPass must equal exactly the set
// of cards that player goes on to play during the round.
TEST(RoundHandsCapture, HandsAfterPassEqualsCardsPlayed_Left) {
    auto players = makePlayers();
    CapturingObserver obs;
    Round round(0, players, Left, std::make_shared<Common::GameLogger>(stdout), &obs);
    round.runDeal();

    ASSERT_EQ(obs.handsCaptures.size(), 1u);
    const auto& hands = obs.handsCaptures[0];
    ASSERT_EQ(hands.size(), Common::Constants::NUM_PLAYERS);

    for (const auto& [tag, cards] : hands) {
        std::set<std::string> handSet(cards.begin(), cards.end());
        EXPECT_EQ(handSet, obs.played[tag])
            << "hands_after_passing for " << tag
            << " does not match the cards that player actually played";
    }
}
