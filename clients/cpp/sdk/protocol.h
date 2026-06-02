#pragma once

// Wire protocol constants for the Hearts server, mirrored from
// server/util/constants.h. Keep these in sync with the server: the JSON tag
// names and message-type strings are the contract between them.

namespace hearts::proto {

// JSON field names ("tags").
namespace tag {
inline constexpr const char* kType            = "type";
inline constexpr const char* kStatus          = "status";
inline constexpr const char* kSessionId       = "session_id";
inline constexpr const char* kSeqNum          = "seq_num";
inline constexpr const char* kPlayerTag       = "player_tag";
inline constexpr const char* kLobbyCode       = "lobby_code";
inline constexpr const char* kGameType        = "game_type";
inline constexpr const char* kPlayerOrder     = "player_order";
inline constexpr const char* kPassDirection   = "pass_direction";
inline constexpr const char* kCards           = "cards";
inline constexpr const char* kCard            = "card";
inline constexpr const char* kDonatedCards    = "donated_cards";
inline constexpr const char* kMoveSource      = "move_source";
inline constexpr const char* kRoundIndex      = "round_index";
inline constexpr const char* kTrickIndex      = "trick_index";
inline constexpr const char* kLegalMoves      = "legal_moves";
inline constexpr const char* kWinningPlayer   = "winning_player";
inline constexpr const char* kRoundPoints     = "player_to_round_points";
inline constexpr const char* kGamePoints      = "player_to_game_points";
inline constexpr const char* kSentAtMs        = "sent_at_ms";
inline constexpr const char* kPrevLatencyMs   = "prev_latency_ms";
}  // namespace tag

// Messages the server sends to the client.
namespace server_msg {
inline constexpr const char* kConnectionResponse  = "connection_response";
inline constexpr const char* kGameSessionResponse = "game_session_response";
inline constexpr const char* kStartGame           = "start_game";
inline constexpr const char* kStartRound          = "start_round";
inline constexpr const char* kReceivedCards       = "received_cards";
inline constexpr const char* kStartTrick          = "start_trick";
inline constexpr const char* kMoveReport          = "move_report";
inline constexpr const char* kMoveRequest         = "move_request";
inline constexpr const char* kEndTrick            = "end_trick";
inline constexpr const char* kEndRound            = "end_round";
inline constexpr const char* kEndGame             = "end_game";
}  // namespace server_msg

// Messages the client sends to the server.
namespace client_msg {
inline constexpr const char* kConnectionRequest  = "connection_request";
inline constexpr const char* kGameSessionRequest = "game_session_request";
inline constexpr const char* kDonatedCards       = "donated_cards";
inline constexpr const char* kDecidedMove        = "decided_move";
}  // namespace client_msg

namespace move_source {
inline constexpr const char* kPlayer = "player";
inline constexpr const char* kServer = "server";
}  // namespace move_source

namespace status {
inline constexpr const char* kSuccess = "success";
}

inline constexpr const char* kDefaultLobbyCode = "main";

}  // namespace hearts::proto
