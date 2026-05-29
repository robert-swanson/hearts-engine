from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import results

app = FastAPI(title="Hearts Web UI")

# Dev: Vite serves the frontend on :5173 and proxies /api here, but allow direct CORS too.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/tournaments")
def tournaments():
    return results.list_tournaments()


@app.get("/api/tournaments/{tournament_id}")
def tournament(tournament_id: str):
    summary = results.get_summary(tournament_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="tournament not found")
    return summary


@app.get("/api/tournaments/{tournament_id}/games/{game_id}")
def game(tournament_id: str, game_id: str):
    detail = results.get_game(tournament_id, game_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="game not found")
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
