"""Voice Studio — Web backend for Qwen3-TTS voice server.

FastAPI application with auth, character management, TTS proxy, and LLM refinement.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from web.app.core.config import settings
from web.app.core.database import init_db
from web.app.routes import account, auth, characters, config, drafts, presets, templates, tts
from web.app.services.tts_proxy import close_client

logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    logger.info("Voice Studio starting up...")
    await init_db()
    logger.info("Database initialized")
    yield
    await close_client()
    logger.info("Voice Studio shut down")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(auth.router)
app.include_router(account.router)
app.include_router(characters.router)
app.include_router(config.router)
app.include_router(presets.router)
app.include_router(tts.router)
app.include_router(drafts.router)
app.include_router(templates.router)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": settings.app_name}


# Serve frontend static files (built React SPA)
_frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    # SPA fallback: serve index.html for all non-API routes
    from starlette.responses import FileResponse

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        file = _frontend_dist / path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(_frontend_dist / "index.html")

    logger.info("Serving frontend from %s", _frontend_dist)
