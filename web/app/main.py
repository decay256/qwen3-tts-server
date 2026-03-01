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
# NOTE: Must use middleware, NOT a catch-all @app.get("/{path:path}") route.
# A catch-all GET route registers a GET handler for every path, which makes
# FastAPI return 405 on POST/PATCH/DELETE to API routes that share a prefix.
_frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    from starlette.responses import FileResponse
    from starlette.types import ASGIApp, Receive, Scope, Send

    class SPAFallbackMiddleware:
        """Serve SPA index.html for non-API, non-file GET requests."""

        def __init__(self, app: ASGIApp, dist_dir: Path):
            self.app = app
            self.dist_dir = dist_dir

        async def __call__(self, scope: Scope, receive: Receive, send: Send):
            if scope["type"] == "http":
                path = scope.get("path", "/")
                # Let API routes, health, and auth through
                if path.startswith(("/api/", "/auth/", "/health", "/docs", "/openapi")):
                    await self.app(scope, receive, send)
                    return
                # Serve static files if they exist
                if scope["method"] == "GET":
                    file = self.dist_dir / path.lstrip("/")
                    if file.is_file() and self.dist_dir in file.resolve().parents:
                        response = FileResponse(str(file))
                        await response(scope, receive, send)
                        return
                    # SPA fallback — serve index.html
                    if not path.startswith("/api/"):
                        response = FileResponse(str(self.dist_dir / "index.html"))
                        await response(scope, receive, send)
                        return
            await self.app(scope, receive, send)

    app = SPAFallbackMiddleware(app, _frontend_dist)  # type: ignore[assignment]
    logger.info("Serving frontend from %s (SPA middleware)", _frontend_dist)
