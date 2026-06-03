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


@app.get("/api/live/tournament")
def live_tournament():
    """Live status of the next/registering tournament across all competitions
    (countdown target + currently-registered players). {} when none is open."""
    return results.get_latest_live_status() or {}


@app.get("/api/competitions/{competition_id}/live")
def competition_live(competition_id: str):
    """Live registration/countdown status for one competition. {} when none."""
    return results.get_live_status(competition_id) or {}


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


@app.get("/api/live/tables")
def list_live_tables():
    """Open/active tables, so the UI can list lobbies to join or observe."""
    return {"tables": live.manager.list_tables()}


@app.post("/api/live/tables")
def create_live_table():
    table = live.manager.create()
    if table is None:
        raise HTTPException(status_code=503, detail="server is at capacity; try again later")
    return {"code": table.code}


class UploadClientRequest(BaseModel):
    filename: Optional[str] = None
    source: str


@app.post("/api/live/tables/{code}/upload-client")
def upload_live_client(code: str, req: UploadClientRequest):
    """Register an uploaded Python Player for one table's seat picker.

    SECURITY: the uploaded file is arbitrary code executed in this process. The
    web UI is a trusted local/dev tool; do not expose this to untrusted users.
    """
    table = live.manager.get(code)
    if table is None:
        raise HTTPException(status_code=404, detail="table not found")
    if len(req.source.encode("utf-8")) > live.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="uploaded client is too large")
    try:
        option = table.register_upload(req.source, req.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Push the updated roster to every connected client so the new option shows
    # up in the seat picker immediately (otherwise it only appears on the next
    # WS action, e.g. clicking Clear).
    table.schedule_broadcast()
    return option


@app.get("/api/live/tables/{code}")
def get_live_table(code: str):
    table = live.manager.get(code)
    if table is None:
        raise HTTPException(status_code=404, detail="table not found")
    return {"code": table.code, "status": table.status}


@app.websocket("/api/live/ws/{code}")
async def live_ws(websocket: WebSocket, code: str, client_id: Optional[str] = None):
    # `client_id` is Optional (not a required str) on purpose: a *missing*
    # required query param makes FastAPI reject the handshake before we can
    # accept it, which the ASGI layer logs as a bare "403 Forbidden" and the
    # client only sees as a generic abnormal close it then reconnects to
    # forever. Accept first and close with an application code instead, so the
    # logs stay quiet and the client gets a reason it can stop on.
    table = live.manager.get(code)
    if table is None or not client_id:
        # Accept first, *then* close with an application code. Closing before
        # accept makes the ASGI layer reject the handshake with HTTP 403, which
        # (a) spams the logs and (b) hides the reason from the client, whose
        # onclose only sees a generic abnormal close and reconnects forever.
        await websocket.accept()
        reason = "table not found" if table is None else "missing client_id"
        await websocket.close(code=4404, reason=reason)
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
            # A malformed frame (non-JSON, or JSON that isn't an object) must not
            # tear down the socket or log a traceback — answer with an error and
            # keep going, so one buggy/hostile client can't spam or self-DoS.
            try:
                msg = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except Exception:
                await err("malformed message (expected a JSON object)")
                continue
            if not isinstance(msg, dict):
                await err("malformed message (expected a JSON object)")
                continue
            try:
                action = msg.get("action")
                if action == "add_human":
                    e = table.add_human(str(msg.get("seat_id", "")), str(msg.get("name", "")), client_id)
                elif action == "add_ai":
                    e = table.add_ai(str(msg.get("seat_id", "")),
                                     msg.get("ai_type") or live.default_ai_type(),
                                     str(msg.get("name", "")), client_id)
                elif action == "add_open":
                    e = table.add_open(str(msg.get("seat_id", "")), str(msg.get("name", "")))
                elif action == "clear_seat":
                    e = table.clear_seat(str(msg.get("seat_id", "")))
                elif action == "set_options":
                    e = table.set_options(slow_mode=msg.get("slow_mode"),
                                          hide_prev_tricks=msg.get("hide_prev_tricks"),
                                          timeout_s=msg.get("timeout_s"))
                elif action == "collect":
                    e = table.collect(str(msg.get("seat_id", "")), client_id)
                elif action == "start":
                    e = await asyncio.get_running_loop().run_in_executor(None, table.start)
                elif action == "decide":
                    e = table.submit_decision(str(msg.get("seat_id", "")), client_id, msg.get("value"))
                else:
                    e = f"Unknown action '{action}'"
            except WebSocketDisconnect:
                break
            except Exception:
                e = "could not process request"
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
    if session is None:
        raise HTTPException(status_code=503, detail="server is at capacity; try again later")
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
        # See live_ws: accept before closing so the client receives a real
        # 4404 close code instead of a handshake-level 403 it can't interpret.
        await websocket.accept()
        await websocket.close(code=4404, reason="table session not found")
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
            # See live_ws: tolerate malformed frames without crashing the socket.
            try:
                msg = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except Exception:
                await err("malformed message (expected a JSON object)")
                continue
            if not isinstance(msg, dict):
                await err("malformed message (expected a JSON object)")
                continue
            try:
                action = msg.get("action")
                if action == "configure":
                    e = session.configure(msg.get("seats", []))
                elif action == "start":
                    e = await asyncio.get_running_loop().run_in_executor(None, session.start)
                elif action == "respond":
                    e = session.submit(msg.get("value"))
                else:
                    e = f"Unknown action '{action}'"
            except WebSocketDisconnect:
                break
            except Exception:
                e = "could not process request"
            if e:
                await err(e)
            await session._broadcast()
    except WebSocketDisconnect:
        pass
    finally:
        session.clients.pop(conn_key, None)


# Catch-all WebSocket route. MUST be declared after every specific @app.websocket
# route above so those still win (FastAPI matches in registration order). Any WS
# path that matches nothing else — an empty table code (/api/live/ws/), a stale
# path from an old cached frontend, a typo — would otherwise be rejected by
# Starlette *before* the handshake. uvicorn logs that as a bare "403 Forbidden"
# and the browser only sees an uninterpretable 1006 close, so the client can't
# tell it should stop and reconnects forever, spamming the logs (issue #50).
# Accept the handshake first, then close with the application code 4404 that the
# live/table socket clients already treat as "gone — stop reconnecting".
@app.websocket("/{_ws_path:path}")
async def websocket_catch_all(websocket: WebSocket, _ws_path: str):
    await websocket.accept()
    await websocket.close(code=4404, reason="unknown websocket endpoint")


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
