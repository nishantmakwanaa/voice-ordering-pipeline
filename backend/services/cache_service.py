"""Redis cache service for VoiceServe AI."""

import json
import logging
from typing import Any, Optional

import redis.asyncio as aioredis

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class CacheService:
    """Async Redis cache service with intelligent preloading and TTL management."""

    def __init__(self) -> None:
        self._client: Optional[aioredis.Redis] = None

    async def connect(self) -> None:
        """Initialize the Redis connection pool."""
        self._client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50,
        )
        await self._client.ping()
        logger.info("Redis connection established: %s", settings.redis_url)

    async def disconnect(self) -> None:
        """Close the Redis connection pool."""
        if self._client:
            await self._client.aclose()
            logger.info("Redis connection closed.")

    @property
    def is_connected(self) -> bool:
        """Return True if the Redis client is initialized."""
        return self._client is not None

    @property
    def client(self) -> aioredis.Redis:
        if self._client is None:
            raise RuntimeError("CacheService not connected. Call connect() first.")
        return self._client

    # ── Generic helpers ───────────────────────────────────────────────────────

    async def get(self, key: str) -> Optional[Any]:
        """Get a value from cache; returns None on miss."""
        raw = await self.client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set a value in cache with optional TTL (seconds)."""
        serialized = json.dumps(value, default=str)
        if ttl:
            await self.client.setex(key, ttl, serialized)
        else:
            await self.client.set(key, serialized)

    async def delete(self, key: str) -> None:
        """Delete a key from cache."""
        await self.client.delete(key)

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a pattern. Returns count deleted."""
        keys = await self.client.keys(pattern)
        if keys:
            return await self.client.delete(*keys)
        return 0

    async def exists(self, key: str) -> bool:
        """Check if a key exists in cache."""
        return bool(await self.client.exists(key))

    # ── Menu cache helpers ────────────────────────────────────────────────────

    async def get_menu(self) -> Optional[list]:
        """Get full menu from cache."""
        return await self.get("menu:all")

    async def set_menu(self, menu_data: list) -> None:
        """Cache full menu with configured TTL."""
        await self.set("menu:all", menu_data, ttl=settings.redis_ttl_menu)
        logger.debug("Menu cached with TTL=%ds", settings.redis_ttl_menu)

    async def get_menu_item(self, item_id: str) -> Optional[dict]:
        """Get a single menu item from cache."""
        return await self.get(f"menu:item:{item_id}")

    async def set_menu_item(self, item_id: str, item_data: dict) -> None:
        """Cache a single menu item."""
        await self.set(f"menu:item:{item_id}", item_data, ttl=settings.redis_ttl_menu)

    async def invalidate_menu(self) -> None:
        """Invalidate all menu caches."""
        count = await self.delete_pattern("menu:*")
        logger.info("Invalidated %d menu cache keys.", count)

    # ── Session cache helpers ─────────────────────────────────────────────────

    async def get_session(self, session_id: str) -> Optional[dict]:
        """Get session state from cache."""
        return await self.get(f"session:{session_id}")

    async def set_session(self, session_id: str, session_data: dict) -> None:
        """Cache session state with configured TTL."""
        await self.set(f"session:{session_id}", session_data, ttl=settings.redis_ttl_session)

    async def refresh_session_ttl(self, session_id: str) -> None:
        """Reset TTL on session key (keep alive on activity)."""
        await self.client.expire(f"session:{session_id}", settings.redis_ttl_session)

    async def invalidate_session(self, session_id: str) -> None:
        """Remove session from cache."""
        await self.delete(f"session:{session_id}")

    # ── Cart cache helpers ────────────────────────────────────────────────────

    async def get_cart(self, session_id: str) -> Optional[dict]:
        """Get cart from cache."""
        return await self.get(f"cart:{session_id}")

    async def set_cart(self, session_id: str, cart_data: dict) -> None:
        """Cache cart data."""
        await self.set(f"cart:{session_id}", cart_data, ttl=settings.redis_ttl_session)

    async def invalidate_cart(self, session_id: str) -> None:
        """Remove cart from cache."""
        await self.delete(f"cart:{session_id}")

    # ── Recommendation cache helpers ──────────────────────────────────────────

    async def get_recommendations(self, session_id: str) -> Optional[list]:
        """Get recommendations from cache."""
        return await self.get(f"recs:{session_id}")

    async def set_recommendations(self, session_id: str, recs: list) -> None:
        """Cache recommendations."""
        await self.set(f"recs:{session_id}", recs, ttl=settings.redis_ttl_recommendations)

    # ── Stats / counters ──────────────────────────────────────────────────────

    async def increment_counter(self, key: str, amount: int = 1) -> int:
        """Increment a counter and return new value."""
        return await self.client.incrby(key, amount)

    async def get_counter(self, key: str) -> int:
        """Get counter value."""
        val = await self.client.get(key)
        return int(val) if val else 0


# Global singleton
cache_service = CacheService()
