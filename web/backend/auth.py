"""Lightweight team / admin authentication for the web UI.

Public data (tournament results, scores, post-pass hands) stays open. The only
private field is each round's ``cards_passed`` (what each player passed, which
encodes their pre-pass hand and received cards). Visibility:
  * admin  -> sees every player's passed cards;
  * a team -> sees only its own players' passed cards, in any game;
  * anyone -> sees none.

Credentials live in ``tournament_server.env`` (never committed):
  * ``WEB_ADMIN_PASSWORD`` -> the admin password (admin login uses no team name);
  * ``TEAMS=name:password,...`` -> per-team passwords (same file the server uses).

Tokens are stdlib-only HMAC-signed blobs (no extra dependency).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Optional

import results

TOKEN_TTL_SECONDS = 12 * 60 * 60

# Per-process fallback so tokens are unforgeable even when no secret is configured
# (they simply won't survive a restart, which is fine for this app).
_PROCESS_SECRET = secrets.token_hex(32)


def _server_env() -> dict[str, str]:
    return results._parse_env_file(results.repo_root() / "tournament_server.env")


def _signing_secret() -> bytes:
    env = _server_env()
    secret = (
        os.environ.get("WEB_TOKEN_SECRET")
        or env.get("WEB_TOKEN_SECRET")
        or os.environ.get("WEB_ADMIN_PASSWORD")
        or env.get("WEB_ADMIN_PASSWORD")
        or _PROCESS_SECRET
    )
    return secret.encode()


def _admin_password() -> Optional[str]:
    pw = os.environ.get("WEB_ADMIN_PASSWORD") or _server_env().get("WEB_ADMIN_PASSWORD")
    return pw or None


def _team_passwords() -> dict[str, str]:
    """name -> password parsed from TEAMS (entries without a password are skipped)."""
    teams: dict[str, str] = {}
    for part in _server_env().get("TEAMS", "").split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        name, _, pw = part.partition(":")
        name, pw = name.strip(), pw.strip()
        if name and pw:
            teams[name] = pw
    return teams


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(team: Optional[str], is_admin: bool) -> str:
    payload = {"team": team, "is_admin": is_admin, "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    body = _b64u(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64u(hmac.new(_signing_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(token: Optional[str]) -> Optional[dict]:
    """Return the validated payload, or None if missing/tampered/expired."""
    if not token or "." not in token:
        return None
    body, _, sig = token.partition(".")
    expected = _b64u(hmac.new(_signing_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64u_decode(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("exp", 0) < int(time.time()):
        return None
    return payload


def authenticate(team: Optional[str], password: str) -> Optional[str]:
    """Validate credentials; return a signed token, or None on failure."""
    admin_pw = _admin_password()
    if admin_pw and not team and hmac.compare_digest(password, admin_pw):
        return make_token(team=None, is_admin=True)
    if team:
        expected = _team_passwords().get(team)
        if expected and hmac.compare_digest(password, expected):
            return make_token(team=team, is_admin=False)
    return None


def principal_from_header(authorization: Optional[str]) -> Optional[dict]:
    """Parse a ``Bearer <token>`` header into a validated principal payload."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return verify_token(token.strip())


def _recipient_index(idx: int, n: int, pass_dir: str) -> Optional[int]:
    """Seat that the player at ``idx`` passes to, or None for Keeper/unknown."""
    if pass_dir == "Left":
        return (idx + 1) % n
    if pass_dir == "Right":
        return (idx - 1) % n
    if pass_dir == "Across":
        return (idx + 2) % n
    return None


def redact_game(detail: dict, principal: Optional[dict]) -> dict:
    """Strip ``cards_passed`` entries the principal may not see (in place).

    A passing transaction (the passer's 3 cards) is private to both the passer
    and the recipient — the recipient legitimately knows what they received. So
    a team sees entries where it owns the passer OR the recipient; an admin sees
    all; everyone else sees none.
    """
    if principal and principal.get("is_admin"):
        return detail

    team = principal.get("team") if principal else None
    player_order = detail.get("player_order", []) or []
    n = len(player_order)

    for rnd in detail.get("rounds", []):
        passed = rnd.get("cards_passed")
        if not isinstance(passed, dict):
            continue
        if not team:
            rnd["cards_passed"] = None
            continue

        prefix = f"{team}/"
        pass_dir = rnd.get("pass_direction", "")
        visible: dict[str, list] = {}
        for pid, cards in passed.items():
            # Viewer owns the passer.
            if pid.startswith(prefix):
                visible[pid] = cards
                continue
            # Viewer owns the recipient -> these are cards the viewer received.
            if pid in player_order:
                ri = _recipient_index(player_order.index(pid), n, pass_dir)
                if ri is not None and player_order[ri].startswith(prefix):
                    visible[pid] = cards
        rnd["cards_passed"] = visible or None
    return detail
