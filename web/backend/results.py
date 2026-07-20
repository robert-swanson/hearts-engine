"""Read-only access to the tournament results directory.

The C++ tournament server writes results nested under a competition directory
(one competition = one competition_runner invocation):

  <RESULTS_DIR>/<competition_id>/competition.json
        -> {competition_id, started_at, teams[], qualifying_games, finals_games,
            tournaments:[{index, began_at, ended_at, complete, summary}]}
  <RESULTS_DIR>/<competition_id>/<index>/summary.json
        -> {tournament_id, competition_id, began_at, ended_at, qualifying[],
            finals[], *_totals, complete}
  <RESULTS_DIR>/<competition_id>/<index>/rules.json
  <RESULTS_DIR>/<competition_id>/<index>/games/<game_id>.json

competition_id and timestamps are dir-name style "2026-5-15_13-36-12.409".

Legacy (pre-competition) tournaments live flat at <RESULTS_DIR>/<id>/ and are
indexed by a top-level array <RESULTS_DIR>/competition.json. They are surfaced
under a synthetic competition whose id is LEGACY_COMPETITION_ID.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

LEGACY_COMPETITION_ID = "legacy"


def repo_root() -> Path:
    # web/backend/results.py -> repo root is two levels up.
    return Path(__file__).resolve().parents[2]


def results_dir() -> Path:
    # Default to the repo's results/ dir (where the C++ server writes), so the
    # backend finds tournaments/lobby games regardless of its launch cwd. The
    # RESULTS_DIR env var still overrides for non-standard layouts.
    env = os.environ.get("RESULTS_DIR")
    if env:
        return Path(env).resolve()
    return repo_root() / "results"


def _read_json(path: Path) -> Optional[Any]:
    try:
        with path.open() as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Files may be missing or mid-write while a tournament runs.
        return None


_TS_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})_(\d{1,2})-(\d{1,2})-(\d{1,2})(?:\.(\d+))?$")


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Parse a dir-name style timestamp into a datetime, or None."""
    if not value:
        return None
    m = _TS_RE.match(value)
    if not m:
        return None
    y, mo, d, h, mi, s, ms = m.groups()
    try:
        return datetime(int(y), int(mo), int(d), int(h), int(mi), int(s),
                        int((ms or "0").ljust(3, "0")[:3]) * 1000)
    except ValueError:
        return None


def parse_tournament_time(value: Optional[str]) -> Optional[str]:
    """Parse a dir-name style timestamp into an ISO string, or None."""
    dt = parse_timestamp(value)
    return dt.isoformat() if dt else None


def _duration_seconds(began: Optional[str], ended: Optional[str]) -> Optional[float]:
    b, e = parse_timestamp(began), parse_timestamp(ended)
    if b and e:
        return max((e - b).total_seconds(), 0.0)
    return None


# ─── Path resolution (with traversal guards) ──────────────────────────────────

def _safe_child(base: Path, name: str) -> Optional[Path]:
    """Resolve base/name, ensuring the result stays within base."""
    target = (base / name).resolve()
    base = base.resolve()
    if target != base and base not in target.parents:
        return None
    return target


def _tournament_dir(competition_id: str, index: str) -> Optional[Path]:
    """Directory for a tournament. Legacy tournaments live flat at <results>/<index>."""
    if competition_id == LEGACY_COMPETITION_ID:
        return _safe_child(results_dir(), index)
    comp = _safe_child(results_dir(), competition_id)
    if comp is None:
        return None
    return _safe_child(comp, index)


# ─── Competitions ─────────────────────────────────────────────────────────────

def _winner_id_points(summary: Optional[dict]) -> list[dict]:
    """Top players (id + points) by finals totals, falling back to qualifying."""
    if not summary:
        return []
    for key in ("finals_totals", "qualifying_totals"):
        totals = summary.get(key)
        if totals:
            ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
            return [{"id": pid, "points": pts} for pid, pts in ranked]
    return []


def _competition_top_players(competition_id: str, tournaments: list[dict],
                             limit: int = 4) -> list[dict]:
    """The competition's leading players, by average tournament points per game.

    Aggregated per (team, player_tag) over every qualifying + finals game of every
    tournament in the competition — the same avg-points-per-game metric the
    competition detail chart drills into, rolled up to the whole competition so the
    list page can show at a glance how the leaders scored and whether a player
    improved between competitions (issue #111). Returns up to `limit` entries,
    highest average first (ties broken by team/tag)."""
    # (team/tag) -> list of that player's per-game tournament points. Within a game
    # we sum any slots a team ran under the same tag, matching the frontend's
    # playerAvgsForGames so the numbers agree with the detail-page drill-down.
    pts_by_tp: dict[str, list[float]] = {}
    for t in tournaments:
        idx = t.get("index")
        if idx is None:
            continue
        summary = get_summary(competition_id, str(idx))
        if not summary:
            continue
        for stage in ("qualifying", "finals"):
            for game in summary.get(stage, []):
                per_tp: dict[str, float] = {}
                for entry in game.get("players", []):
                    for full_id, score in entry.items():
                        parts = full_id.split("/")
                        key = f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else full_id
                        pts = (score or {}).get("tournament_points", 0)
                        per_tp[key] = per_tp.get(key, 0) + pts
                for key, pts in per_tp.items():
                    pts_by_tp.setdefault(key, []).append(pts)

    ranked = []
    for key, games in pts_by_tp.items():
        if not games:
            continue
        team, _, tag = key.partition("/")
        ranked.append({
            "team": team,
            "tag": tag or key,
            "avg_points": sum(games) / len(games),
            "games": len(games),
        })
    ranked.sort(key=lambda r: (-r["avg_points"], r["team"], r["tag"]))
    return ranked[:limit]


def _tournament_row(competition_id: str, index: str,
                    began_at: Optional[str], ended_at: Optional[str],
                    complete: Optional[bool]) -> dict:
    """A tournament's row for the competition detail page (placements + length)."""
    summary = get_summary(competition_id, index)
    if began_at is None and summary:
        began_at = summary.get("began_at")
    if ended_at is None and summary:
        ended_at = summary.get("ended_at")
    # Legacy tournaments predate began_at; their dir name (index) is itself a timestamp.
    if began_at is None and parse_timestamp(index):
        began_at = index
    if complete is None and summary:
        complete = summary.get("complete", True)
    ranked = _winner_id_points(summary)
    return {
        "competition_id": competition_id,
        "index": index,
        "began_at": parse_tournament_time(began_at) or began_at,
        "ended_at": parse_tournament_time(ended_at) or ended_at,
        "length_seconds": _duration_seconds(began_at, ended_at),
        "placements": ranked[:4],
        "num_qualifying": len((summary or {}).get("qualifying", [])),
        "num_finals": len((summary or {}).get("finals", [])),
        "complete": True if complete is None else complete,
    }


def _legacy_competition() -> Optional[dict]:
    """Wrap legacy flat tournaments (top-level competition.json array) as a competition."""
    index = _read_json(results_dir() / "competition.json")
    if not isinstance(index, list) or not index:
        return None
    tournaments = []
    for entry in index:
        tid = entry.get("tournament_id")
        if not tid:
            continue
        tournaments.append({"index": tid, "began_at": None, "ended_at": None, "complete": None})
    # Sort newest-first by parsed begin time (the id is a timestamp).
    tournaments.sort(key=lambda t: parse_tournament_time(t["index"]) or "", reverse=True)
    teams = _legacy_team_names(tournaments)
    return {
        "competition_id": LEGACY_COMPETITION_ID,
        "started_at": None,
        "teams": teams,
        "qualifying_games": None,
        "finals_games": None,
        "tournaments": tournaments,
        "is_legacy": True,
    }


def _legacy_team_names(tournaments: list[dict]) -> list[str]:
    """Best-effort team names for the legacy bundle, from the most recent summary."""
    for t in tournaments[:1]:
        summary = get_summary(LEGACY_COMPETITION_ID, t["index"])
        if summary:
            names = sorted({k.split("/")[0] for k in summary.get("qualifying_totals", {})})
            if names:
                return names
    return []


def _load_competition_meta(comp_dir: Path) -> Optional[dict]:
    """Load a real competition's competition.json (object) from its dir."""
    data = _read_json(comp_dir / "competition.json")
    if not isinstance(data, dict):
        return None
    data.setdefault("competition_id", comp_dir.name)
    data.setdefault("started_at", comp_dir.name)
    data.setdefault("teams", [])
    data.setdefault("tournaments", [])
    data["is_legacy"] = False
    return data


def list_competitions() -> list[dict]:
    """All competitions, newest first. Each carries summarizing info for the list page."""
    out: list[dict] = []
    root = results_dir()
    if root.is_dir():
        for child in root.iterdir():
            if not child.is_dir():
                continue
            meta = _load_competition_meta(child)
            if meta is None:
                continue
            out.append({
                "competition_id": meta["competition_id"],
                "started_at": parse_tournament_time(meta.get("started_at")) or meta.get("started_at"),
                "teams": meta.get("teams", []),
                "num_teams": len(meta.get("teams", [])),
                "num_tournaments": len(meta.get("tournaments", [])),
                "qualifying_games": meta.get("qualifying_games"),
                "finals_games": meta.get("finals_games"),
                "top_players": _competition_top_players(
                    meta["competition_id"], meta.get("tournaments", [])),
                "is_legacy": False,
            })
    legacy = _legacy_competition()
    if legacy:
        out.append({
            "competition_id": legacy["competition_id"],
            "started_at": legacy.get("started_at"),
            "teams": legacy.get("teams", []),
            "num_teams": len(legacy.get("teams", [])),
            "num_tournaments": len(legacy.get("tournaments", [])),
            "qualifying_games": legacy.get("qualifying_games"),
            "finals_games": legacy.get("finals_games"),
            "top_players": _competition_top_players(
                legacy["competition_id"], legacy.get("tournaments", [])),
            "is_legacy": True,
        })
    out.sort(key=lambda c: c["started_at"] or "", reverse=True)
    return out


def get_competition(competition_id: str) -> Optional[dict]:
    """Full competition detail: metadata + enriched tournament rows."""
    if competition_id == LEGACY_COMPETITION_ID:
        meta = _legacy_competition()
        if meta is None:
            return None
    else:
        comp_dir = _safe_child(results_dir(), competition_id)
        if comp_dir is None:
            return None
        meta = _load_competition_meta(comp_dir)
        if meta is None:
            return None

    rows = []
    for t in meta.get("tournaments", []):
        idx = t.get("index")
        if idx is None:
            continue
        rows.append(_tournament_row(
            competition_id, str(idx),
            t.get("began_at"), t.get("ended_at"), t.get("complete")))
    # Newest first by begin time (falls back to numeric index).
    def _sort_key(r):
        return (r["began_at"] or "", r["index"])
    rows.sort(key=_sort_key, reverse=True)

    return {
        "competition_id": meta["competition_id"],
        "started_at": parse_tournament_time(meta.get("started_at")) or meta.get("started_at"),
        "teams": meta.get("teams", []),
        "qualifying_games": meta.get("qualifying_games"),
        "finals_games": meta.get("finals_games"),
        "is_legacy": meta.get("is_legacy", False),
        "tournaments": rows,
    }


# ─── Live tournament status ────────────────────────────────────────────────────

def get_live_status(competition_id: str) -> Optional[dict]:
    """Live registration/countdown status for a competition. The tournament server
    writes <results>/<competition_id>/live.json while a registration window is open
    (state, tournament_index, start_at, registered players). None if absent."""
    comp_dir = _safe_child(results_dir(), competition_id)
    if comp_dir is None:
        return None
    data = _read_json(comp_dir / "live.json")
    return data if isinstance(data, dict) else None


def get_latest_live_status() -> Optional[dict]:
    """The most recently-updated live.json across all competitions, so the UI can
    surface "the next tournament" without first knowing which competition is live."""
    base = results_dir()
    best: Optional[dict] = None
    best_updated = -1
    try:
        children = list(base.iterdir())
    except FileNotFoundError:
        return None
    for child in children:
        if not child.is_dir():
            continue
        data = _read_json(child / "live.json")
        if isinstance(data, dict):
            updated = data.get("updated_at", 0) or 0
            if updated > best_updated:
                best_updated = updated
                best = data
    return best


# ─── Tournament / game / rules ─────────────────────────────────────────────────

def get_summary(competition_id: str, index: str) -> Optional[dict]:
    tdir = _tournament_dir(competition_id, index)
    if tdir is None:
        return None
    return _read_json(tdir / "summary.json")


# Per-game fields the web UI never reads. The tournament page shows aggregated
# move-time stats from the small top-level "player_stats" object, so the verbose
# per-game latency breakdown is pure dead weight on the wire — together these two
# are ~half the summary.json bytes for a large tournament. Stripping them before
# serving (alongside gzip) roughly halves the payload and the client-side JSON
# parse, which was the dominant tournament-page load cost.
_HEAVY_GAME_FIELDS = ("latency", "total_move_latency_ms")


def get_summary_web(competition_id: str, index: str) -> Optional[dict]:
    """get_summary() projected down to what the web tournament page needs:
    the same document with the unused heavy per-game latency fields removed."""
    summary = get_summary(competition_id, index)
    if summary is None:
        return None
    for stage in ("qualifying", "finals"):
        for game in summary.get(stage, []):
            for field in _HEAVY_GAME_FIELDS:
                game.pop(field, None)
    return summary


def get_rules(competition_id: str, index: str) -> Optional[dict]:
    tdir = _tournament_dir(competition_id, index)
    if tdir is None:
        return None
    return _read_json(tdir / "rules.json")


def get_game(competition_id: str, index: str, game_id: str) -> Optional[dict]:
    tdir = _tournament_dir(competition_id, index)
    if tdir is None:
        return None
    summary = _read_json(tdir / "summary.json")
    detail_file = f"games/{game_id}.json"
    if summary:
        for stage in ("qualifying", "finals"):
            for g in summary.get(stage, []):
                if g.get("game_id") == game_id and g.get("detail_file"):
                    detail_file = g["detail_file"]
    base = tdir.resolve()
    target = (base / detail_file).resolve()
    if base not in target.parents and target != base:
        return None
    return _read_json(target)


# ─── Lobby (practice) games ────────────────────────────────────────────────────
#
# The regular (non-tournament) server records every completed lobby game the same
# way tournaments do, under <RESULTS_DIR>/lobby/:
#   lobby/index.json          append-only array of game metadata (newest appended)
#   lobby/games/<id>.json     full detail (player_order + rounds), same shape as
#                             tournament game detail, so the existing game/round
#                             views render it unchanged.
# Lobby games are public practice games with no team secrecy, so passed cards are
# returned to everyone (no redaction).

def _lobby_dir() -> Path:
    return results_dir() / "lobby"


def list_lobby_games() -> list[dict]:
    """All recorded lobby games, newest first."""
    index = _read_json(_lobby_dir() / "index.json")
    if not isinstance(index, list):
        return []
    out: list[dict] = []
    for entry in index:
        if not isinstance(entry, dict):
            continue
        played_at = entry.get("played_at")
        out.append({
            "game_id": entry.get("game_id"),
            "played_at": parse_tournament_time(played_at) or played_at,
            "player_order": entry.get("player_order", []),
            "winner": entry.get("winner"),
            "final_scores": entry.get("final_scores", {}),
            "rounds_played": entry.get("rounds_played"),
        })
    out.sort(key=lambda g: (g["played_at"] or "", g["game_id"] or ""), reverse=True)
    return out


def get_lobby_game(game_id: str) -> Optional[dict]:
    """Full detail for one lobby game (player_order + rounds), or None."""
    base = _lobby_dir().resolve()
    target = (base / "games" / f"{game_id}.json").resolve()
    if base not in target.parents:
        return None
    return _read_json(target)


# ─── Env / live stats ──────────────────────────────────────────────────────────

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


def _latest_tournament() -> Optional[tuple[str, str]]:
    """(competition_id, index) of the most recent tournament across all competitions."""
    best: Optional[tuple[str, str, str]] = None  # (began_at, cid, index)
    for comp in list_competitions():
        cid = comp["competition_id"]
        detail = get_competition(cid)
        if not detail:
            continue
        for t in detail["tournaments"]:
            key = t["began_at"] or ""
            if best is None or key > best[0]:
                best = (key, cid, t["index"])
    if best is None:
        return None
    return best[1], best[2]


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

    latest = _latest_tournament()
    qualifying_executed = 0
    finals_executed = 0
    standings: dict[str, int] = {}
    games_won: dict[str, int] = {}
    began_at = None
    competition_id = None
    tournament_index = None
    if latest:
        competition_id, tournament_index = latest
        summary = get_summary(competition_id, tournament_index) or {}
        began_at = parse_tournament_time(summary.get("began_at"))
        qualifying_executed = len(summary.get("qualifying", []))
        finals_executed = len(summary.get("finals", []))
        standings = summary.get("finals_totals") or summary.get("qualifying_totals") or {}
        # Count game wins over the same stage the standings reflect (finals once
        # they begin, otherwise qualifying), so wins line up with the points shown.
        # The winner id carries a per-game session suffix; the standings totals are
        # keyed by slot id (team/tag/index), so collapse to that to match.
        stage_games = summary.get("finals") if summary.get("finals_totals") else summary.get("qualifying")
        for entry in stage_games or []:
            winner = entry.get("winner") if isinstance(entry, dict) else None
            if winner:
                slot = "/".join(winner.split("/")[:3])
                games_won[slot] = games_won.get(slot, 0) + 1

    executed = qualifying_executed + finals_executed
    planned_total = planned_qualifying + planned_finals
    waiting = max(planned_total - executed, 0)

    return {
        "competition_id": competition_id,
        "tournament_index": tournament_index,
        "began_at": began_at,
        "teams": teams,
        "num_teams": len(teams),
        "planned_qualifying_games": planned_qualifying,
        "planned_finals_games": planned_finals,
        "qualifying_executed": qualifying_executed,
        "finals_executed": finals_executed,
        "games_executed": executed,
        "games_waiting": waiting,
        "standings": standings,
        "games_won": games_won,
        "note": "in-progress/waiting counts are approximated from completed result files vs configured totals; the game server does not expose live per-game state.",
    }
