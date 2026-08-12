"""FastAPI dashboard: serves the single-page UI and a small JSON API.

Endpoints
  GET  /                 -> dashboard HTML
  GET  /api/status       -> full engine snapshot (equity, positions, signals)
  GET  /api/trades       -> recent closed trades
  GET  /api/equity       -> equity curve points
  POST /api/start        -> start the engine
  POST /api/stop         -> stop the engine

Optional token auth: if DASHBOARD_TOKEN is set, every request must present it
via `?token=` or the `Authorization: Bearer <token>` header.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import load_bot_config, load_settings
from ..database import Database
from ..engine import TradingEngine

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    settings = load_settings()
    config = load_bot_config()
    db = Database()
    engine = TradingEngine(settings, config, db)

    app = FastAPI(title="Crypto Trading Bot", version="0.1.0")

    def require_token(
        request: Request,
        token: str | None = Query(default=None),
    ) -> None:
        expected = settings.dashboard_token
        if not expected:
            return  # auth disabled
        header = request.headers.get("authorization", "")
        bearer = header[7:] if header.lower().startswith("bearer ") else ""
        if token != expected and bearer != expected:
            raise HTTPException(status_code=401, detail="Invalid or missing token")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/status")
    def status(_: None = Depends(require_token)) -> JSONResponse:
        return JSONResponse(engine.snapshot())

    @app.get("/api/trades")
    def trades(_: None = Depends(require_token), limit: int = 100) -> JSONResponse:
        return JSONResponse(db.recent_trades(limit))

    @app.get("/api/equity")
    def equity(_: None = Depends(require_token), limit: int = 1000) -> JSONResponse:
        return JSONResponse(db.equity_history(limit))

    @app.post("/api/start")
    def start(_: None = Depends(require_token)) -> JSONResponse:
        engine.start()
        return JSONResponse({"running": engine.state.running})

    @app.post("/api/stop")
    def stop(_: None = Depends(require_token)) -> JSONResponse:
        engine.stop()
        return JSONResponse({"running": engine.state.running})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.state.engine = engine
    return app


app = create_app()
