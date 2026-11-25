"""Pinecone vector search service for fuzzy menu matching via semantic embeddings."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from pinecone import Pinecone, ServerlessSpec
from openai import AsyncOpenAI

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class VectorService:
    """
    Pinecone-backed semantic search for menu items.

    Uses OpenAI-compatible embeddings (can substitute any embedding provider).
    Enables fuzzy natural-language queries like "something spicy and vegetarian"
    to match semantically relevant menu items.
    """

    def __init__(self) -> None:
        self._pc: Optional[Pinecone] = None
        self._index = None
        self._embed_client: Optional[AsyncOpenAI] = None

    @property
    def is_connected(self) -> bool:
        """Return True if Pinecone index is initialized and ready."""
        return self._index is not None

    async def connect(self) -> None:
        """Initialize Pinecone client and embedding client."""
        api_key = (settings.pinecone_api_key or "").strip()
        if not api_key or api_key.startswith("your-"):
            logger.warning("Pinecone API key not configured; semantic search disabled.")
            return

        try:
            self._pc = Pinecone(api_key=api_key)

            # Create index if it doesn't exist
            existing_resp = await asyncio.to_thread(self._pc.list_indexes)
            existing = [idx.name for idx in existing_resp]
            if settings.pinecone_index_name not in existing:
                await asyncio.to_thread(
                    self._pc.create_index,
                    name=settings.pinecone_index_name,
                    dimension=settings.pinecone_dimension,
                    metric=settings.pinecone_metric,
                    spec=ServerlessSpec(cloud="aws", region="us-east-1"),
                )
                logger.info("Created Pinecone index: %s", settings.pinecone_index_name)
            else:
                logger.info("Using existing Pinecone index: %s", settings.pinecone_index_name)

            self._index = self._pc.Index(settings.pinecone_index_name)
        except Exception as exc:
            logger.warning("Failed to connect to Pinecone (%s); semantic search disabled.", exc)
            self._index = None
            self._pc = None
            return

        # Use Kimi K2 endpoint for embeddings (OpenAI-compatible)
        # In production, you'd use a dedicated embedding model
        self._embed_client = AsyncOpenAI(
            api_key=settings.kimi_api_key,
            base_url=settings.kimi_api_url,
        )

    async def disconnect(self) -> None:
        """Clean up connections."""
        self._index = None
        self._pc = None
        logger.info("VectorService disconnected.")

    async def get_embedding(self, text: str) -> List[float]:
        """
        Generate a semantic embedding for the given text.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector as list of floats.
        """
        if self._embed_client is None:
            return [0.0] * settings.pinecone_dimension

        try:
            response = await self._embed_client.embeddings.create(
                input=text,
                model="text-embedding-3-small",
            )
            return response.data[0].embedding
        except Exception as exc:
            logger.error("Embedding error: %s", exc)
            # Return zero vector as fallback
            return [0.0] * settings.pinecone_dimension

    async def upsert_menu_item(self, item_id: str, item_data: Dict[str, Any]) -> None:
        """
        Upsert a menu item into the Pinecone index.

        Args:
            item_id: Unique menu item ID.
            item_data: Menu item dict with name, description, category, tags, etc.
        """
        if self._index is None:
            return

        # Build rich text for embedding
        text_parts = [
            item_data.get("name") or "",
            item_data.get("description") or "",
            item_data.get("category") or "",
        ]
        tags = item_data.get("tags") or []
        if tags:
            text_parts.append(" ".join(tags))
        allergens = item_data.get("allergens") or []
        if allergens:
            text_parts.append(f"allergens: {', '.join(allergens)}")
        text = " | ".join(filter(None, text_parts))

        embedding = await self.get_embedding(text)

        metadata = {
            "name": item_data.get("name") or "",
            "category": item_data.get("category") or "",
            "price": float(item_data.get("price", 0)),
            "is_available": bool(item_data.get("is_available", True)),
            "tags": list(tags),
        }

        await asyncio.to_thread(
            self._index.upsert,
            vectors=[{"id": item_id, "values": embedding, "metadata": metadata}],
        )
        logger.debug("Upserted menu item %s into Pinecone.", item_id)

    async def delete_menu_item(self, item_id: str) -> None:
        """Remove a menu item from the index."""
        if self._index is None:
            return
        await asyncio.to_thread(self._index.delete, ids=[item_id])
        logger.debug("Deleted menu item %s from Pinecone.", item_id)

    async def search_menu(
        self,
        query: str,
        top_k: int = 5,
        filter_dict: Optional[Dict] = None,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search for menu items matching the query.

        Args:
            query: Natural language search query.
            top_k: Maximum number of results to return.
            filter_dict: Optional Pinecone metadata filters, e.g. {"is_available": {"$eq": True}}.

        Returns:
            List of dicts with keys: id, score, metadata.
        """
        if self._index is None:
            return []

        embedding = await self.get_embedding(query)

        query_kwargs: Dict[str, Any] = {
            "vector": embedding,
            "top_k": top_k,
            "include_metadata": True,
        }
        if filter_dict:
            query_kwargs["filter"] = filter_dict

        # Always filter to available items by default
        if not filter_dict:
            query_kwargs["filter"] = {"is_available": {"$eq": True}}

        try:
            results = await asyncio.to_thread(self._index.query, **query_kwargs)
            matches = results.get("matches", [])
            return [
                {
                    "id": m["id"],
                    "score": float(m["score"]),
                    "metadata": m.get("metadata", {}),
                }
                for m in matches
                if float(m["score"]) > 0.5  # minimum similarity threshold
            ]
        except Exception as exc:
            logger.error("Pinecone search error: %s", exc)
            return []

    async def bulk_upsert_menu(self, items: List[Dict[str, Any]]) -> int:
        """
        Bulk upsert all menu items into Pinecone.

        Args:
            items: List of menu item dicts with 'id' field.

        Returns:
            Number of items upserted.
        """
        count = 0
        for item in items:
            item_id = item.get("id")
            if item_id:
                await self.upsert_menu_item(str(item_id), item)
                count += 1
        logger.info("Bulk upserted %d menu items into Pinecone.", count)
        return count


# Global singleton
vector_service = VectorService()
