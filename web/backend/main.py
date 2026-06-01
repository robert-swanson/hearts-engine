from pathlib import Path
from typing import Optional

import asyncio
import uuid

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import auth
import live
import results
import table

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
def live_stats():
    return results.get_live_stats()


# --- Live lobby play ---------------------------------------------------------


@app.get("/api/live/ai-types")
def live_ai_types():
    return {"ai_types": live.ai_type_options()}


@app.post("/api/live/tables")
def create_live_table():
    table = live.manager.create()
    return {"code": table.code}


@app.get("/api/live/tables/{code}")
def get_live_table(code: str):
    table = live.manager.get(code)
    if table is None:
        raise HTTPException(status_code=404, detail="table not found")
    return {"code": table.code, "status": table.status}


@app.websocket("/api/live/ws/{code}")
async def live_ws(websocket: WebSocket, code: str, client_id: str):
    table = live.manager.get(code)
    if table is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    table.loop = asyncio.get_running_loop()
    conn_key = uuid.uuid4().hex
    table.clients[conn_key] = (websocket, client_id)
    await websocket.send_json(table.snapshot_for(client_id))

    async def err(msg: str):
        await websocket.send_json({"type": "error", "message": msg})

    try:
        while True:
            msg = await websocket.receive_json()
            action = msg.get("action")
            if action == "add_human":
                e = table.add_human(msg["seat_id"], msg.get("name", ""), client_id)
            elif action == "add_ai":
                e = table.add_ai(msg["seat_id"], msg.get("ai_type") or live.default_ai_type(),
                                 msg.get("name", ""), client_id)
            elif action == "clear_seat":
                e = table.clear_seat(msg["seat_id"])
            elif action == "start":
                e = await asyncio.get_running_loop().run_in_executor(None, table.start)
            elif action == "decide":
                e = table.submit_decision(msg["seat_id"], client_id, msg.get("value"))
            else:
                e = f"Unknown action '{action}'"
            if e:
                await err(e)
            await table._broadcast()
    except WebSocketDisconnect:
        pass
    finally:
        table.clients.pop(conn_key, None)


# --- Physical-table play (AI vs. real humans at a real table) ----------------


@app.get("/api/table/ai-types")
def table_ai_types():
    return {"ai_types": table.ai_type_options()}


@app.post("/api/table/sessions")
def create_table_session():
    session = table.manager.create()
    return {"code": session.code}


@app.get("/api/table/sessions/{code}")
def get_table_session(code: str):
    session = table.manager.get(code)
    if session is None:
        raise HTTPException(status_code=404, detail="table session not found")
    return {"code": session.code, "status": session.status}


@app.websocket("/api/table/ws/{code}")
async def table_ws(websocket: WebSocket, code: str):
    session = table.manager.get(code)
    if session is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    session.loop = asyncio.get_running_loop()
    conn_key = uuid.uuid4().hex
    session.clients[conn_key] = websocket
    await websocket.send_json(session.snapshot())

    async def err(msg: str):
        await websocket.send_json({"type": "error", "message": msg})

    try:
        while True:
            msg = await websocket.receive_json()
            action = msg.get("action")
            if action == "configure":
                e = session.configure(msg.get("seats", []))
            elif action == "start":
                e = await asyncio.get_running_loop().run_in_executor(None, session.start)
            elif action == "respond":
                e = session.submit(msg.get("value"))
            else:
                e = f"Unknown action '{action}'"
            if e:
                await err(e)
            await session._broadcast()
    except WebSocketDisconnect:
        pass
    finally:
        session.clients.pop(conn_key, None)


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
