"""FastAPI application entrypoint (REST + WebSocket).

Run with ``uvicorn jobpilot.api.main:app`` or ``python -m jobpilot.cli serve``.
Binds to localhost only (single-user, local control plane — PLAN.md §5.6).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from jobpilot import __version__
from jobpilot.api.routes import analytics, apply, cv, inbox, jobs, ops, review, stats
from jobpilot.api.ws import manager, websocket_endpoint
from jobpilot.orchestrator import queue

# Vite dev server (Web Dashboard, Phase 4) origins.
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Worker threads publish task progress by hopping back onto this loop.
    queue.bind(asyncio.get_running_loop(), manager.broadcast)
    yield
    queue.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(title="JobPilot API", version=__version__, lifespan=lifespan)

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

    # review + apply first: jobs' GET /{job_id:path} is greedy and would shadow
    # /jobs/{id}/review and /jobs/{id}/cv.
    app.include_router(review.router)
    app.include_router(apply.router)
    app.include_router(apply.board)
    app.include_router(jobs.router)
    app.include_router(stats.router)
    app.include_router(analytics.router)
    app.include_router(cv.router)
    app.include_router(inbox.router)
    app.include_router(ops.router)
    app.add_api_websocket_route("/ws", websocket_endpoint)
    return app


app = create_app()
