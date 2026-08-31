"""
Project Google Drive Multi Mail
Main entry point - starts the FastAPI application.

Usage:
    python main.py
    or
    uvicorn main:app --reload --host 0.0.0.0 --port 8090
"""
import os
import sys
import logging
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()  # Load .env file

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import manager as db
from app.api.routes import app as api_app
from app.sync.background import start_background_sync, stop_background_sync

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("gdrive_multi")

# Sync interval (default 1 hour, configurable via env)
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL_SECONDS", 3600))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown hooks."""
    # ── Startup ──
    logger.info("Initializing database...")
    db.init_db()
    logger.info("Database initialized.")

    logger.info(f"Starting background sync (interval={SYNC_INTERVAL}s)...")
    await start_background_sync(interval=SYNC_INTERVAL)
    logger.info("Background sync started.")

    yield  # App is running

    # ── Shutdown ──
    logger.info("Stopping background sync...")
    await stop_background_sync()
    logger.info("Shutdown complete.")


def create_app() -> FastAPI:
    """Create and configure the application."""
    app = FastAPI(
        title="Google Drive Multi Mail",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app


# Build the app by importing routes (which registers them on api_app)
# and then merging into our lifespan-enabled app
_app = create_app()

# Re-attach everything from api_app onto our new app
for route in api_app.routes:
    _app.routes.append(route)
for middleware in api_app.user_middleware:
    _app.user_middleware.insert(0, middleware)
_app.middleware_stack = None  # force re-build

app = _app


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8090)) or 8090
    host = os.environ.get("HOST", "0.0.0.0")
    reload = os.environ.get("RELOAD", "true").lower() == "true"

    logger.info(f"Starting server on {host}:{port}")
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=reload,
    )
