#pragma once

#include <string>

// Validation for the two client-supplied identifiers the server embeds in
// filesystem paths, log lines, and result JSON. Everything a client sends must
// be treated as hostile until it passes these checks.

namespace Common::Server::Validation
{

// Player tags appear in logs, PlayerTagSession strings ("tag(sessionId)"),
// tournament slot IDs ("team/tag/slot"), and result JSON keys.
constexpr size_t MAX_PLAYER_TAG_LENGTH = 48;

// Lobby codes are embedded in log/result *file names* (see LiveGame), so they
// get the strictest charset. The SDK's practice-lobby helper builds codes by
// concatenating the four player tags plus a hash, so this allows for four
// reasonably long tags while keeping composed filenames (code + "_" + session
// id + "_messages.log", ~25 extra bytes) under the 255-byte filesystem limit.
constexpr size_t MAX_LOBBY_CODE_LENGTH = 200;

// Lobby codes: [A-Za-z0-9_-] only — no separators, no dots, nothing a
// filesystem or path join could reinterpret.
inline bool IsValidLobbyCode(const std::string& code)
{
    if (code.empty() || code.size() > MAX_LOBBY_CODE_LENGTH)
        return false;
    for (char c : code)
    {
        bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
               || (c >= '0' && c <= '9') || c == '_' || c == '-';
        if (!ok)
            return false;
    }
    return true;
}

// Player tags: printable, no control characters (log-line injection), and none
// of the characters the server itself uses as structural delimiters:
//   '(' ')'  — PlayerTagSession is "tag(sessionId)" and is parsed back by rfind
//   '/' '\\' — tournament slot IDs are "team/tag/slot" and are split on '/'
// Bytes >= 0x80 are allowed so UTF-8 names (e.g. from the web UI) still work.
inline bool IsValidPlayerTag(const std::string& tag)
{
    if (tag.empty() || tag.size() > MAX_PLAYER_TAG_LENGTH)
        return false;
    for (char c : tag)
    {
        auto uc = static_cast<unsigned char>(c);
        if (uc < 0x20 || uc == 0x7F)
            return false;
        if (c == '(' || c == ')' || c == '/' || c == '\\')
            return false;
    }
    return true;
}

}
