"""Menu CRUD and semantic search endpoints."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.tools import get_all_menu_items_cached, menu_item_to_dict
from backend.database import get_db
from backend.models.database import Menu
from backend.models.schemas import (
    MenuItemCreate,
    MenuItemResponse,
    MenuItemUpdate,
    MenuListResponse,
)
from backend.services.cache_service import cache_service
from backend.services.vector_service import vector_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/menu", tags=["Menu"])


@router.get("", response_model=MenuListResponse)
async def list_menu_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    category: Optional[str] = Query(None),
    available_only: bool = Query(False),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> MenuListResponse:
    """List menu items with optional filtering and pagination (Redis-cached)."""
    items = await get_all_menu_items_cached(db, available_only=available_only)

    if category:
        cat_lower = category.strip().lower()
        items = [it for it in items if it["category"].lower() == cat_lower]

    if search:
        q = search.strip().lower()
        items = [
            it
            for it in items
            if q in (it["name"] or "").lower()
            or q in (it["description"] or "").lower()
            or q in (it["category"] or "").lower()
            or any(q in tag.lower() for tag in (it.get("tags") or []))
        ]

    total = len(items)
    start = (page - 1) * page_size
    paginated = items[start : start + page_size]

    return MenuListResponse(
        items=[MenuItemResponse(**it) for it in paginated],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/search", response_model=List[MenuItemResponse])
async def semantic_search_menu(
    q: str = Query(..., min_length=1, description="Natural language search query"),
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
) -> List[MenuItemResponse]:
    """Search menu items using Pinecone semantic search with keyword fallback."""
    all_items = await get_all_menu_items_cached(db, available_only=True)
    by_id = {it["id"]: it for it in all_items}

    results: List[MenuItemResponse] = []
    if vector_service.is_connected:
        hits = await vector_service.search_menu(query=q, top_k=limit)
        for hit in hits:
            if hit["id"] in by_id:
                results.append(MenuItemResponse(**by_id[hit["id"]]))

    if not results:
        tokens = [t for t in q.lower().split() if t]
        scored = []
        for it in all_items:
            haystack = " ".join([
                it.get("name") or "",
                it.get("description") or "",
                it.get("category") or "",
                " ".join(it.get("tags") or []),
            ]).lower()
            score = sum(1 for tok in tokens if tok in haystack)
            if score > 0:
                scored.append((score, it))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        results = [MenuItemResponse(**pair[1]) for pair in scored[:limit]]

    return results


@router.get("/{item_id}", response_model=MenuItemResponse)
async def get_menu_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
) -> MenuItemResponse:
    """Get details for a single menu item."""
    if cache_service.is_connected:
        cached = await cache_service.get_menu_item(item_id)
        if cached:
            return MenuItemResponse(**cached)

    result = await db.execute(select(Menu).where(Menu.id == item_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu item not found")

    item_dict = menu_item_to_dict(item)
    if cache_service.is_connected:
        await cache_service.set_menu_item(item_id, item_dict)
    return MenuItemResponse(**item_dict)


@router.post("", response_model=MenuItemResponse, status_code=status.HTTP_201_CREATED)
async def create_menu_item(
    payload: MenuItemCreate,
    db: AsyncSession = Depends(get_db),
) -> MenuItemResponse:
    """Create a new menu item (admin), invalidate cache, and sync to Pinecone."""
    item = Menu(**payload.model_dump())
    db.add(item)
    await db.flush()
    await db.refresh(item)

    item_dict = menu_item_to_dict(item)
    if vector_service.is_connected:
        await vector_service.upsert_menu_item(str(item.id), item_dict)
        item.embedding_synced = True
        await db.flush()
        await db.refresh(item)

    if cache_service.is_connected:
        await cache_service.invalidate_menu()

    return MenuItemResponse.model_validate(item)


@router.put("/{item_id}", response_model=MenuItemResponse)
async def update_menu_item(
    item_id: str,
    payload: MenuItemUpdate,
    db: AsyncSession = Depends(get_db),
) -> MenuItemResponse:
    """Update an existing menu item (admin), invalidate cache, and update Pinecone."""
    result = await db.execute(select(Menu).where(Menu.id == item_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu item not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(item, field_name, value)

    await db.flush()
    await db.refresh(item)

    if vector_service.is_connected:
        await vector_service.upsert_menu_item(str(item.id), menu_item_to_dict(item))
        item.embedding_synced = True
        await db.flush()
        await db.refresh(item)

    if cache_service.is_connected:
        await cache_service.invalidate_menu()

    return MenuItemResponse.model_validate(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_menu_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a menu item (admin), invalidate cache, and remove from Pinecone."""
    result = await db.execute(select(Menu).where(Menu.id == item_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu item not found")

    await db.delete(item)
    await db.flush()

    if vector_service.is_connected:
        await vector_service.delete_menu_item(item_id)
    if cache_service.is_connected:
        await cache_service.invalidate_menu()
