#!/usr/bin/env python3
"""Unit tests for clients.python.player_debugger (no server, no network needed).

Covers the pieces that make the replay debugger trustworthy:

  * URL / API / file parsing into a GameRef (incl. the /r/<n> round default),
  * the legal-move reconstruction (a port of Trick::legalMovesForPlayer),
  * dealt-hand reconstruction (post_pass − received + passed), and
  * the end-to-end replay: the driver asks the simulated seat at every pass and
    move, forces history everywhere else, and reports exactly the decisions that
    diverge from the record.

Run directly: ``python3 tests/player_debugger_test.py``.
"""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from clients.python import player_debugger as pd
from clients.python.api.Player import Player
from clients.python.api.Round import Round
from clients.python.api.Trick import Trick
from clients.python.api.types.Card import Card, Suit, SortCardsByRank
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTag as _PlayerTag


def C(s):
    return Card(s)


# ─── URL parsing ──────────────────────────────────────────────────────────────

def test_parse_web_tournament_round_url():
    ref = pd.parse_game_ref("https://host/c/comp1/t/0/g/game9/r/3")
    assert ref.kind == "tournament"
    assert ref.competition_id == "comp1"
    assert ref.tournament_index == "0"
    assert ref.game_id == "game9"
    assert ref.round_idx == 3
    assert ref.api_path() == "/api/competitions/comp1/tournaments/0/games/game9"
    assert ref.origin == "https://host"


def test_parse_web_lobby_url_no_round():
    ref = pd.parse_game_ref("https://host/lobby/g/abc123")
    assert ref.kind == "lobby"
    assert ref.game_id == "abc123"
    assert ref.round_idx is None
    assert ref.api_path() == "/api/lobby/games/abc123"


def test_parse_api_urls():
    ref = pd.parse_game_ref("http://h:8000/api/lobby/games/xyz")
    assert ref.kind == "lobby" and ref.game_id == "xyz"
    ref = pd.parse_game_ref("http://h/api/competitions/c9/tournaments/2/games/g5")
    assert ref.kind == "tournament" and ref.game_id == "g5"
    assert ref.competition_id == "c9" and ref.tournament_index == "2"


def test_parse_file_path(tmp_path=None):
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write("{}")
        name = f.name
    ref = pd.parse_game_ref(name)
    assert ref.kind == "file"
    assert ref.file_path == Path(name).resolve()
    Path(name).unlink()


def test_parse_bad_url_raises():
    try:
        pd.parse_game_ref("not-a-url-or-file")
    except ValueError:
        return
    raise AssertionError("expected ValueError for a non-URL, non-file input")


# ─── Identity parsing ─────────────────────────────────────────────────────────

def test_parse_full_id_formats():
    assert pd.parse_full_id("RandomPlayer(3)") == ("RandomPlayer(3)", "RandomPlayer", 3)
    assert pd.parse_full_id("TeamA/rob_player/0/42") == ("TeamA/rob_player/0", "rob_player", 42)


# ─── Legal-move reconstruction (mirrors server/game/trick.h) ──────────────────

def test_legal_moves_first_trick_leader_forced_2c():
    hand = [C("2C"), C("5D"), C("KS")]
    assert pd.legal_moves_for_hand(hand, 0, None, False) == [C("2C")]


def test_legal_moves_follow_suit():
    hand = [C("4D"), C("9D"), C("KS")]
    # Following a diamond lead: only diamonds are legal.
    assert set(pd.legal_moves_for_hand(hand, 1, Suit.DIAMONDS, False)) == {C("4D"), C("9D")}


def test_legal_moves_void_can_slough():
    hand = [C("4D"), C("9D"), C("KS")]
    # Void in the led suit (clubs) → everything is legal.
    assert set(pd.legal_moves_for_hand(hand, 1, Suit.CLUBS, True)) == set(hand)


def test_legal_moves_no_lead_hearts_until_broken():
    hand = [C("3H"), C("5D")]
    assert pd.legal_moves_for_hand(hand, 4, None, False) == [C("5D")]
    assert set(pd.legal_moves_for_hand(hand, 4, None, True)) == {C("3H"), C("5D")}


def test_legal_moves_first_trick_no_points():
    hand = [C("QS"), C("3H"), C("5D")]
    # Void in the club lead on trick 0: may not sluff points if a non-point exists.
    assert pd.legal_moves_for_hand(hand, 0, Suit.CLUBS, False) == [C("5D")]


# ─── Test players ─────────────────────────────────────────────────────────────

class _LowestPlayer(Player):
    """Deterministic: play the lowest legal card, pass the three highest."""
    player_tag = _PlayerTag("lowest_test")

    def handle_new_round(self, round: Round) -> None:
        self.hand = round.cards_in_hand
        self.moves_seen = getattr(self, "moves_seen", 0)

    def get_cards_to_pass(self, pass_dir, receiving_player):
        return SortCardsByRank(self.hand, reverse=True)[:3]

    def get_move(self, trick, legal_moves, move_request_latency_ms=None):
        return SortCardsByRank(legal_moves)[0]

    def handle_move(self, trick, player, card, report_latency_ms=None,
                    decided_move_latency_ms=None):
        self.moves_seen = getattr(self, "moves_seen", 0) + 1


class _HighestPlayer(_LowestPlayer):
    """Play the highest legal card, pass the three lowest — to force divergence."""
    player_tag = _PlayerTag("highest_test")

    def get_cards_to_pass(self, pass_dir, receiving_player):
        return SortCardsByRank(self.hand)[:3]

    def get_move(self, trick, legal_moves, move_request_latency_ms=None):
        return SortCardsByRank(legal_moves, reverse=True)[0]


# A small but rule-valid Keeper round. Seat A (target) gets a real choice in
# trick 1 (void in the led suit, holding two diamonds), so lowest vs highest
# strategies diverge there and nowhere else.
KEEPER_GAME = {
    "game_id": "test-keeper",
    "player_order": ["A(1)", "B(2)", "C(3)", "D(4)"],
    "rounds": [
        {
            "round_idx": 0,
            "pass_direction": "Keeper",
            "hands_after_passing": {
                "A(1)": ["2C", "4D", "9D"],
                "B(2)": ["3C", "5D", "7S"],
                "C(3)": ["5C", "6D", "8S"],
                "D(4)": ["7C", "3S", "TD"],
            },
            "tricks": [
                {"first_player": "A(1)", "moves": ["2C", "3C", "5C", "7C"],
                 "winner": "D(4)", "points": 0},
                {"first_player": "D(4)", "moves": ["3S", "4D", "7S", "8S"],
                 "winner": "C(3)", "points": 0},
                {"first_player": "C(3)", "moves": ["6D", "TD", "9D", "5D"],
                 "winner": "D(4)", "points": 0},
            ],
            "round_scores": {"A(1)": 0, "B(2)": 0, "C(3)": 0, "D(4)": 0},
        }
    ],
}


def _run(game, target_index, player_cls, **kw):
    dbg = pd.ReplayDebugger(game, target_index, player_cls, out=io.StringIO())
    end_round = max(r["round_idx"] for r in game["rounds"])
    return dbg.run(kw.get("start_round", 0), kw.get("end_round", end_round),
                   kw.get("through_trick", 12))


def test_replay_matches_history_no_diffs():
    result = _run(KEEPER_GAME, 0, _LowestPlayer)
    # 3 moves for the target seat, no passing on a Keeper round.
    assert result.decisions == 3
    assert result.discrepancies == [], result.discrepancies


def test_replay_detects_move_divergence():
    result = _run(KEEPER_GAME, 0, _HighestPlayer)
    assert result.decisions == 3
    assert result.move_diffs == 1
    assert result.pass_diffs == 0
    d = result.discrepancies[0]
    assert d.kind == "move" and d.round_idx == 0 and d.trick_idx == 1
    assert d.agent_choice == "9D" and d.historical == "4D"


def test_replay_observes_all_four_seats():
    dbg = pd.ReplayDebugger(KEEPER_GAME, 0, _LowestPlayer, out=io.StringIO())
    dbg.run(0, 0, 12)
    # handle_move fires once per card played: 3 tricks * 4 players.
    assert dbg.player.moves_seen == 12


def test_through_trick_truncates_round():
    result = _run(KEEPER_GAME, 0, _HighestPlayer, through_trick=0)
    # Only trick 0 runs; the divergence in trick 1 is never reached.
    assert result.decisions == 1
    assert result.discrepancies == []


# ─── Passing reconstruction + divergence ──────────────────────────────────────
#
# A Left round: A passes to B, and (Left) receives from D. The dealt hand is the
# post-pass hand minus what D gave A, plus what A passed away.
LEFT_GAME = {
    "game_id": "test-left",
    "player_order": ["A(1)", "B(2)", "C(3)", "D(4)"],
    "rounds": [
        {
            "round_idx": 0,
            "pass_direction": "Left",
            "cards_passed": {
                "A(1)": ["AS", "KH", "QD"],  # A passed these to B
                "D(4)": ["2C", "3C", "4C"],  # D passed these to A (A received them)
            },
            "hands_after_passing": {
                "A(1)": ["2C", "3C", "4C", "5D"],  # post-pass hand
                "B(2)": ["6C", "7C", "8C", "9C"],
                "C(3)": ["TC", "JC", "QC", "KC"],
                "D(4)": ["AC", "2D", "3D", "4D"],
            },
            "tricks": [],
            "round_scores": {"A(1)": 0, "B(2)": 0, "C(3)": 0, "D(4)": 0},
        }
    ],
}


def test_dealt_hand_reconstruction():
    order = LEFT_GAME["player_order"]
    dealt = pd.dealt_hand(LEFT_GAME["rounds"][0], order, "A(1)", PassDirection.LEFT)
    # post_pass {2C,3C,4C,5D} − received {2C,3C,4C} + passed {AS,KH,QD}
    assert set(dealt) == {C("5D"), C("AS"), C("KH"), C("QD")}


def test_pass_divergence_detected():
    # _LowestPlayer passes the 3 highest of its dealt hand: {AS, KH, QD} (spade/
    # heart/diamond high cards) — which happens to match history exactly here.
    result = _run(LEFT_GAME, 0, _LowestPlayer)
    assert result.pass_diffs == 0

    # _HighestPlayer passes the 3 lowest → diverges from the recorded pass.
    result = _run(LEFT_GAME, 0, _HighestPlayer)
    assert result.pass_diffs == 1
    d = result.discrepancies[0]
    assert d.kind == "pass" and d.round_idx == 0


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("ALL PASS: player_debugger")


if __name__ == "__main__":
    run()
