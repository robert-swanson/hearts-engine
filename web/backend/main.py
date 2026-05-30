from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import auth
import results

app = FastAPI(title="Hearts Web UI")

# Dev: Vite serves the frontend on :5173 and proxies /api here, but allow direct CORS too.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    team: Optional[str] = None
    password: str


@app.post("/api/login")
def login(req: LoginRequest):
    token = auth.authenticate(req.team, req.password)
    if token is None:
        raise HTTPException(status_code=401, detail="invalid credentials")
    principal = auth.verify_token(token) or {}
    return {"token": token, "team": principal.get("team"), "is_admin": principal.get("is_admin", False)}


@app.get("/api/competitions")
def competitions():
    return results.list_competitions()


@app.get("/api/competitions/{competition_id}")
def competition(competition_id: str):
    detail = results.get_competition(competition_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="competition not found")
    return detail


@app.get("/api/competitions/{competition_id}/tournaments/{index}")
def tournament(competition_id: str, index: str):
    summary = results.get_summary(competition_id, index)
    if summary is None:
        raise HTTPException(status_code=404, detail="tournament not found")
    return summary


@app.get("/api/competitions/{competition_id}/tournaments/{index}/rules")
def rules(competition_id: str, index: str):
    data = results.get_rules(competition_id, index)
    if data is None:
        raise HTTPException(status_code=404, detail="rules not found")
    return data


@app.get("/api/competitions/{competition_id}/tournaments/{index}/games/{game_id}")
def game(competition_id: str, index: str, game_id: str,
         authorization: Optional[str] = Header(default=None)):
    detail = results.get_game(competition_id, index, game_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="game not found")
    return auth.redact_game(detail, auth.principal_from_header(authorization))


@app.get("/api/lobby/games")
def lobby_games():
    return results.list_lobby_games()


@app.get("/api/lobby/games/{game_id}")
def lobby_game(game_id: str):
    detail = results.get_lobby_game(game_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="lobby game not found")
    return detail


@app.get("/api/live")
def live():
    return results.get_live_stats()


# Serve the built frontend (web/frontend/dist) when present, so prod is a single process.
_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _dist.is_dir():
    # Real build assets (hashed JS/CSS) are served from /assets directly.
    app.mount("/assets", StaticFiles(directory=str(_dist / "assets")), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        # /api/* is handled above; anything else still under /api is a genuine 404.
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        # Serve a real file when it exists (favicon, etc.), else the SPA shell so
        # client-side routes like /t/<id>/g/<game>/r/0 work on refresh/deep-link.
        candidate = (_dist / full_path).resolve()
        if full_path and candidate.is_file() and _dist in candidate.parents:
            return FileResponse(str(candidate))
        return FileResponse(str(_dist / "index.html"))
