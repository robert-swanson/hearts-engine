#include <gtest/gtest.h>
#include <string>

#include "server/util/validation.h"
#include "server/game/objects/card.h"

using namespace Common::Server::Validation;

// ─── Player tags ───────────────────────────────────────────────────────────────

TEST(Validation, AcceptsOrdinaryPlayerTags)
{
    EXPECT_TRUE(IsValidPlayerTag("random_player"));
    EXPECT_TRUE(IsValidPlayerTag("tim_claude_player_moon_reckless"));
    EXPECT_TRUE(IsValidPlayerTag("alice-1"));
    EXPECT_TRUE(IsValidPlayerTag("A"));
}

TEST(Validation, RejectsEmptyOrOversizedPlayerTags)
{
    EXPECT_FALSE(IsValidPlayerTag(""));
    EXPECT_FALSE(IsValidPlayerTag(std::string(MAX_PLAYER_TAG_LENGTH + 1, 'x')));
    EXPECT_TRUE(IsValidPlayerTag(std::string(MAX_PLAYER_TAG_LENGTH, 'x')));
}

TEST(Validation, RejectsStructuralDelimitersInPlayerTags)
{
    // These characters are how the server frames identity: PlayerTagSession is
    // "tag(sessionId)" and tournament slot IDs are "team/tag/slot". Allowing them
    // in a tag would let a client forge or corrupt those identifiers.
    EXPECT_FALSE(IsValidPlayerTag("foo(1)"));
    EXPECT_FALSE(IsValidPlayerTag("a/b"));
    EXPECT_FALSE(IsValidPlayerTag("a\\b"));
    EXPECT_FALSE(IsValidPlayerTag("bad)tag"));
}

TEST(Validation, RejectsControlCharactersInPlayerTags)
{
    EXPECT_FALSE(IsValidPlayerTag(std::string("line\ninjection")));
    EXPECT_FALSE(IsValidPlayerTag(std::string("tab\there")));
    EXPECT_FALSE(IsValidPlayerTag(std::string("nul\0byte", 8)));
}

TEST(Validation, AllowsUtf8InPlayerTags)
{
    // Bytes >= 0x80 are permitted so UTF-8 display names still work.
    EXPECT_TRUE(IsValidPlayerTag("café"));
}

// ─── Lobby codes ───────────────────────────────────────────────────────────────

TEST(Validation, AcceptsOrdinaryLobbyCodes)
{
    EXPECT_TRUE(IsValidLobbyCode("main"));
    EXPECT_TRUE(IsValidLobbyCode("weblive_AB12_deadbeef"));
    EXPECT_TRUE(IsValidLobbyCode("practice_lobby_random_player_123456"));
}

TEST(Validation, RejectsPathTraversalInLobbyCodes)
{
    // Lobby codes are embedded in log and result file paths — anything a
    // filesystem could reinterpret must be rejected.
    EXPECT_FALSE(IsValidLobbyCode("../../etc/passwd"));
    EXPECT_FALSE(IsValidLobbyCode("a/b"));
    EXPECT_FALSE(IsValidLobbyCode("a.b"));
    EXPECT_FALSE(IsValidLobbyCode("with space"));
    EXPECT_FALSE(IsValidLobbyCode("dollar$"));
}

TEST(Validation, RejectsEmptyOrOversizedLobbyCodes)
{
    EXPECT_FALSE(IsValidLobbyCode(""));
    EXPECT_FALSE(IsValidLobbyCode(std::string(MAX_LOBBY_CODE_LENGTH + 1, 'a')));
    EXPECT_TRUE(IsValidLobbyCode(std::string(MAX_LOBBY_CODE_LENGTH, 'a')));
}

// ─── Card parsing (client-supplied strings must throw, not abort) ──────────────

TEST(Validation, MalformedCardStringThrows)
{
    using Common::Game::Card;
    // A client can send any string as a card. The constructor must throw
    // std::invalid_argument (caught by RemotePlayer to auto-substitute a move),
    // never assert/abort the whole server.
    EXPECT_THROW(Card(std::string("")), std::invalid_argument);
    EXPECT_THROW(Card(std::string("Q")), std::invalid_argument);
    EXPECT_THROW(Card(std::string("123")), std::invalid_argument);
    EXPECT_THROW(Card(std::string("ZZ")), std::invalid_argument);
    EXPECT_THROW(Card(std::string("2Z")), std::invalid_argument);
    EXPECT_THROW(Card(std::string("NOTACARD")), std::invalid_argument);
}

TEST(Validation, ValidCardStringParses)
{
    using Common::Game::Card;
    EXPECT_NO_THROW(Card(std::string("2C")));
    EXPECT_NO_THROW(Card(std::string("QS")));
    EXPECT_NO_THROW(Card(std::string("TH")));
    EXPECT_NO_THROW(Card(std::string("AD")));
}
