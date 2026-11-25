"""FastAPI application entry point for VoiceServe AI."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.agents.tools import get_all_menu_items_cached
from backend.config import get_settings
from backend.database import close_db, get_db_session, init_db
from backend.routers import menu, orders, reports, voice
from backend.services.cache_service import cache_service
from backend.services.llm_service import llm_service
from backend.services.recommendation_service import recommendation_service
from backend.services.stt_service import stt_service
from backend.services.tts_service import tts_service
from backend.services.vector_service import vector_service

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown lifecycle for DB, Redis, AI services, and FP-Growth."""
    logger.info("Starting VoiceServe AI backend...")

    # 1. PostgreSQL tables
    try:
        await init_db()
        logger.info("Database initialized.")
    except Exception as exc:
        logger.warning("Database initialization warning: %s", exc)

    # 2. Redis cache + menu preloading
    try:
        await cache_service.connect()
        async with get_db_session() as db:
            preloaded = await get_all_menu_items_cached(db)
            logger.info("Preloaded %d menu items into Redis cache.", len(preloaded))
    except Exception as exc:
        logger.warning("Redis cache unavailable at startup: %s", exc)

    # 3. Voice & AI services
    await stt_service.connect()
    await llm_service.connect()
    await tts_service.connect()

    # 4. Pinecone vector service
    try:
        await vector_service.connect()
    except Exception as exc:
        logger.warning("VectorService startup warning: %s", exc)

    # 5. Train FP-Growth recommendations from historical orders
    try:
        async with get_db_session() as db:
            await recommendation_service.train(db)
    except Exception as exc:
        logger.warning("FP-Growth training skipped at startup: %s", exc)

    yield

    logger.info("Shutting down VoiceServe AI backend...")
    await tts_service.disconnect()
    await llm_service.disconnect()
    await stt_service.disconnect()
    await vector_service.disconnect()
    await cache_service.disconnect()
    await close_db()
    logger.info("VoiceServe AI shutdown complete.")


app = FastAPI(
    title="VoiceServe AI",
    description="Real-time STT -> LLM -> TTS voice ordering pipeline",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(voice.router)
app.include_router(menu.router)
app.include_router(orders.router)
app.include_router(reports.router)


@app.get("/health", tags=["Health"])
async def health_check() -> Dict[str, Any]:
    """Return service health and dependency status."""
    return {
        "status": "ok",
        "services": {
            "redis": cache_service.is_connected,
            "vector_db": vector_service.is_connected,
            "llm": llm_service.is_connected,
        },
    }
