"""Read-only access to the tournament results directory.

The C++ tournament server writes:
  <RESULTS_DIR>/competition.json          -> [{tournament_id, summary}]
  <RESULTS_DIR>/<id>/summary.json         -> {tournament_id, qualifying[], finals[], *_totals}
  <RESULTS_DIR>/<id>/games/<game_id>.json -> {game_id, player_order, rounds[]}

Tournament ids are timestamped dir names like "2026-5-15_13-36-12.409".
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def results_dir() -> Path:
    return Path(os.environ.get("RESULTS_DIR", "./results")).resolve()


def repo_root() -> Path:
    # web/backend/results.py -> repo root is two levels up.
    return Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> Optional[Any]:
    try:
        with path.open() as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Files may be missing or mid-write while a tournament runs.
        return None


_TS_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})_(\d{1,2})-(\d{1,2})-(\d{1,2})(?:\.(\d+))?$")


def parse_tournament_time(tournament_id: str) -> Optional[str]:
    """Parse a tournament dir name into an ISO timestamp, or None if it doesn't match."""
    m = _TS_RE.match(tournament_id)
    if not m:
        return None
    y, mo, d, h, mi, s, ms = m.groups()
    try:
        dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), int((ms or "0").ljust(3, "0")[:3]) * 1000)
    except ValueError:
        return None
    return dt.isoformat()


def list_tournaments() -> list[dict]:
    """Tournaments from competition.json, enriched with begin time and winner."""
    index = _read_json(results_dir() / "competition.json") or []
    out: list[dict] = []
    for entry in index:
        tid = entry.get("tournament_id")
        if not tid:
            continue
        summary = _read_json(results_dir() / tid / "summary.json")
        out.append(
            {
                "tournament_id": tid,
                "began_at": parse_tournament_time(tid),
                "winner": _tournament_winner(summary),
                "num_qualifying": len((summary or {}).get("qualifying", [])),
                "num_finals": len((summary or {}).get("finals", [])),
                "complete": summary is not None,
            }
        )
    out.sort(key=lambda t: t["began_at"] or "", reverse=True)
    return out


def _tournament_winner(summary: Optional[dict]) -> Optional[str]:
    """Winning slot id = top scorer in finals_totals (falls back to qualifying_totals)."""
    if not summary:
        return None
    for key in ("finals_totals", "qualifying_totals"):
        totals = summary.get(key)
        if totals:
            return max(totals.items(), key=lambda kv: kv[1])[0]
    return None


def get_summary(tournament_id: str) -> Optional[dict]:
    return _read_json(results_dir() / tournament_id / "summary.json")


def get_game(tournament_id: str, game_id: str) -> Optional[dict]:
    summary = get_summary(tournament_id)
    detail_file = f"games/{game_id}.json"
    if summary:
        for stage in ("qualifying", "finals"):
            for g in summary.get(stage, []):
                if g.get("game_id") == game_id and g.get("detail_file"):
                    detail_file = g["detail_file"]
    # Guard against path traversal; detail_file is server-authored but be safe.
    base = (results_dir() / tournament_id).resolve()
    target = (base / detail_file).resolve()
    if base not in target.parents and target != base:
        return None
    return _read_json(target)


def _parse_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    try:
        text = path.read_text()
    except FileNotFoundError:
        return env
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env


def _parse_teams(teams_str: str) -> list[dict]:
    teams: list[dict] = []
    for part in teams_str.split(","):
        part = part.strip()
        if not part:
            continue
        name = part.split(":", 1)[0]
        teams.append({"name": name})
    return teams


def get_live_stats() -> dict:
    """Live stats for the most-recent tournament, approximated from files + config."""
    env = _parse_env_file(repo_root() / "tournament_server.env")
    try:
        planned_qualifying = int(env.get("QUALIFYING_GAMES", "0"))
    except ValueError:
        planned_qualifying = 0
    try:
        planned_finals = int(env.get("FINALS_GAMES", "0"))
    except ValueError:
        planned_finals = 0
    teams = _parse_teams(env.get("TEAMS", ""))

    tournaments = list_tournaments()
    current = tournaments[0] if tournaments else None

    executed = 0
    standings: dict[str, int] = {}
    began_at = None
    tournament_id = None
    if current:
        tournament_id = current["tournament_id"]
        began_at = current["began_at"]
        summary = get_summary(tournament_id) or {}
        executed = len(summary.get("qualifying", [])) + len(summary.get("finals", []))
        # Standings: prefer finals totals once finals start, else qualifying.
        standings = summary.get("finals_totals") or summary.get("qualifying_totals") or {}

    planned_total = planned_qualifying + planned_finals
    waiting = max(planned_total - executed, 0)

    return {
        "tournament_id": tournament_id,
        "began_at": began_at,
        "teams": teams,
        "num_teams": len(teams),
        "planned_qualifying_games": planned_qualifying,
        "planned_finals_games": planned_finals,
        "games_executed": executed,
        "games_waiting": waiting,
        "standings": standings,
        "note": "in-progress/waiting counts are approximated from completed result files vs configured totals; the game server does not expose live per-game state.",
    }
