"""Voice Studio — Web backend for Qwen3-TTS voice server.

FastAPI application with auth, character management, TTS proxy, and LLM refinement.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from web.app.core.config import settings
from web.app.core.database import init_db
from web.app.routes import auth, characters, tts
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
app.include_router(characters.router)
app.include_router(tts.router)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": settings.app_name}
