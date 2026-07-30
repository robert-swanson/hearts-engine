#!/usr/bin/env python3
"""Tests for the web backend merging per-move log sidecars into game detail, and
redacting them per team (no server needed).

Run directly: ``python3 tests/move_logs_backend_test.py``.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web" / "backend"))

import importlib


def _write(path: Path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))


def test_lobby_game_merges_move_logs():
    with tempfile.TemporaryDirectory() as d:
        os.environ["RESULTS_DIR"] = d
        try:
            import results
            importlib.reload(results)
            root = Path(d)
            _write(root / "lobby" / "games" / "g1.json",
                   {"game_id": "g1", "player_order": ["A(1)", "B(2)"], "rounds": []})
            _write(root / "lobby" / "logs" / "g1" / "A_1_.json",
                   {"game_id": "g1", "author": "A(1)",
                    "entries": [{"round_idx": 0, "trick_idx": 2, "seat": "A(1)",
                                 "phase": "move", "text": "why I played this"}]})
            _write(root / "lobby" / "logs" / "g1" / "B_2_.json",
                   {"game_id": "g1", "author": "B(2)",
                    "entries": [{"round_idx": 0, "trick_idx": 2, "seat": "B(2)",
                                 "phase": "move", "text": "B reasoning"}]})

            detail = results.get_lobby_game("g1")
            assert detail is not None
            logs = detail["move_logs"]
            assert len(logs) == 2
            authors = {e["author"] for e in logs}
            assert authors == {"A(1)", "B(2)"}
            a = next(e for e in logs if e["author"] == "A(1)")
            assert a["text"] == "why I played this" and a["trick_idx"] == 2
        finally:
            os.environ.pop("RESULTS_DIR", None)


def test_lobby_game_no_logs_is_empty_list():
    with tempfile.TemporaryDirectory() as d:
        os.environ["RESULTS_DIR"] = d
        try:
            import results
            importlib.reload(results)
            _write(Path(d) / "lobby" / "games" / "g2.json",
                   {"game_id": "g2", "player_order": ["A(1)"], "rounds": []})
            detail = results.get_lobby_game("g2")
            assert detail["move_logs"] == []
        finally:
            os.environ.pop("RESULTS_DIR", None)


def test_tournament_game_merges_move_logs():
    """The tournament sidecar path the server tells clients to use
    (<competition>/<index>/logs/<game_id>/<seat>.json) is the one get_game reads."""
    with tempfile.TemporaryDirectory() as d:
        os.environ["RESULTS_DIR"] = d
        try:
            import results
            importlib.reload(results)
            tdir = Path(d) / "comp_a" / "1"
            _write(tdir / "games" / "g3.json",
                   {"game_id": "g3", "player_order": ["red/p/0/1"], "rounds": []})
            _write(tdir / "logs" / "g3" / "red_p_0_1.json",
                   {"game_id": "g3", "author": "red/p/0/1",
                    "entries": [{"round_idx": 5, "trick_idx": 0, "seat": "red/p/0/1",
                                 "phase": "move", "text": "tournament reasoning"}]})

            detail = results.get_game("comp_a", "1", "g3")
            assert detail is not None
            assert [e["text"] for e in detail["move_logs"]] == ["tournament reasoning"]
            # Authored under the recorded id, so per-team redaction can match it.
            assert detail["move_logs"][0]["author"] == detail["player_order"][0]
        finally:
            os.environ.pop("RESULTS_DIR", None)


def test_redact_move_logs_by_team():
    import auth
    detail = {
        "player_order": ["red/p/0/1", "blue/q/0/2"],
        "rounds": [],
        "move_logs": [
            {"author": "red/p/0/1", "round_idx": 0, "trick_idx": 0, "seat": "red/p/0/1",
             "phase": "move", "text": "red secret"},
            {"author": "blue/q/0/2", "round_idx": 0, "trick_idx": 0, "seat": "blue/q/0/2",
             "phase": "move", "text": "blue secret"},
        ],
    }
    # Admin sees all.
    admin = auth.redact_game(json.loads(json.dumps(detail)), {"is_admin": True})
    assert len(admin["move_logs"]) == 2
    # A team sees only its own authors.
    red = auth.redact_game(json.loads(json.dumps(detail)), {"team": "red"})
    assert [e["text"] for e in red["move_logs"]] == ["red secret"]
    # Anonymous sees none.
    anon = auth.redact_game(json.loads(json.dumps(detail)), None)
    assert anon["move_logs"] == []


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("ALL PASS: move_logs_backend")


if __name__ == "__main__":
    run()
