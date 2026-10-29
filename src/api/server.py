"""
Dashboard API Server — FastAPI backend for the Autopilot Dashboard.

Routes:
  GET  /              → Dashboard HTML
  GET  /api/status    → System status JSON
  GET  /api/runs      → Agent run history
  POST /api/trigger   → Manually trigger an agent
  WS   /ws            → Live event stream
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal, Optional

import structlog
import uvicorn
from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, StrictBool

from src.config.settings import settings
from src.orchestrator import Orchestrator
from src.security import valid_admin_token

logger = structlog.get_logger("api")

app = FastAPI(
    title="AI Business Autopilot",
    description="Monitor and control your AI automation agents",
    version="1.0.0",
)

# Singleton orchestrator (initialized on startup)
_orchestrator: Orchestrator | None = None
_ws_clients: list[WebSocket] = []


@app.middleware("http")
async def authenticate_api(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not valid_admin_token(token):
            return JSONResponse(
                {"detail": "Valid admin bearer token required"}, status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
    return await call_next(request)


@app.get("/health")
async def health():
    return {"status": "ok" if _orchestrator else "starting"}


@app.on_event("startup")
async def startup():
    global _orchestrator
    _orchestrator = Orchestrator(dry_run=True)
    _orchestrator.add_event_listener(_broadcast_to_ws)
    await _orchestrator.start()
    logger.info("server_started", port=settings.DASHBOARD_PORT)


@app.on_event("shutdown")
async def shutdown():
    if _orchestrator:
        await _orchestrator.stop()


# ------------------------------------------------------------------
# REST routes
# ------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard HTML."""
    html_path = Path(__file__).parent / "static" / "dashboard.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text())
    return HTMLResponse("<h1>AI Autopilot — Dashboard loading...</h1>")


@app.get("/api/status")
async def get_status():
    if not _orchestrator:
        return JSONResponse({"error": "Orchestrator not initialized"}, status_code=503)
    return _orchestrator.get_status()


@app.get("/api/runs")
async def get_runs(limit: int = Query(50, ge=1, le=500)):
    if not _orchestrator:
        return []
    runs = _orchestrator.run_history[-limit:]
    return [r.to_dict() for r in reversed(runs)]


class TriggerRequest(BaseModel):
    mode: Literal["dry_run", "live"] = "dry_run"
    approve_live: StrictBool = False


@app.post("/api/trigger/{agent_name}")
async def trigger_agent(agent_name: str, request: Optional[TriggerRequest] = None):
    if not _orchestrator:
        return JSONResponse({"error": "Orchestrator not initialized"}, status_code=503)

    request = request or TriggerRequest()
    live = request.mode == "live"
    if live and (not settings.ENABLE_LIVE_ACTIONS or not request.approve_live):
        raise HTTPException(403, "Live mode requires server opt-in and approve_live: true")
    logger.info("manual_trigger", agent=agent_name, live=live)
    run = await _orchestrator.trigger(agent_name, live=live)

    if run is None:
        return JSONResponse({"error": f"Agent '{agent_name}' not found"}, status_code=404)

    return run.to_dict()


@app.get("/api/agents")
async def get_agents():
    if not _orchestrator:
        return []
    return [
        {
            "name": name,
            "status": agent.last_run.status.value if agent.last_run else "idle",
            "last_run": agent.last_run.started_at.isoformat() if agent.last_run and agent.last_run.started_at else None,
        }
        for name, agent in _orchestrator.active_agents.items()
    ]


# ------------------------------------------------------------------
# WebSocket
# ------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    # Browser WebSockets cannot set Authorization headers. Authenticate the first
    # frame before sending any status/history or registering for broadcasts.
    try:
        credentials = await asyncio.wait_for(ws.receive_json(), timeout=5)
        token = credentials.get("token") if isinstance(credentials, dict) else None
        if not isinstance(token, str) or not valid_admin_token(token):
            await ws.close(code=1008)
            return
    except (TimeoutError, ValueError, WebSocketDisconnect):
        await ws.close(code=1008)
        return
    _ws_clients.append(ws)
    logger.info("ws_client_connected", total=len(_ws_clients))

    try:
        # Send current status on connect
        if _orchestrator:
            await ws.send_json({"event": "status", "data": _orchestrator.get_status()})

        while True:
            # Keep connection alive with ping
            await asyncio.sleep(30)
            await ws.send_json({"event": "ping"})

    except WebSocketDisconnect:
        logger.info("ws_client_disconnected", total=len(_ws_clients))
    finally:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


async def _broadcast_to_ws(message: dict):
    """Send an event to all connected WebSocket clients."""
    disconnected = []
    for client in _ws_clients:
        try:
            await client.send_json(message)
        except Exception:
            disconnected.append(client)

    for client in disconnected:
        if client in _ws_clients:
            _ws_clients.remove(client)


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def run_server():
    uvicorn.run(
        "src.api.server:app",
        host="0.0.0.0",
        port=settings.DASHBOARD_PORT,
        reload=settings.APP_ENV == "development",
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    run_server()
