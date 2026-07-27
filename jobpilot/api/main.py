"""FastAPI application entrypoint (REST + WebSocket).

Run with ``uvicorn jobpilot.api.main:app`` or ``python -m jobpilot.cli serve``.
Binds to localhost only (single-user, local control plane — PLAN.md §5.6).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from jobpilot import __version__
from jobpilot.api.routes import cv, jobs, stats
from jobpilot.api.ws import websocket_endpoint

# Vite dev server (Web Dashboard, Phase 4) origins.
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def create_app() -> FastAPI:
    app = FastAPI(title="JobPilot API", version=__version__)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    app.include_router(jobs.router)
    app.include_router(stats.router)
    app.include_router(cv.router)
    app.add_api_websocket_route("/ws", websocket_endpoint)
    return app


app = create_app()
