"""Order, cart, and recommendation management endpoints."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.agents.tools import (
    add_item_to_session_cart,
    build_cart_response,
    checkout_session_cart,
    ensure_session_exists,
    get_all_menu_items_cached,
    normalize_uuid,
    remove_item_from_session_cart,
)
from backend.database import get_db
from backend.models.database import Order, OrderItem
from backend.models.schemas import (
    CartItemAdd,
    CartResponse,
    MenuItemResponse,
    OrderCreate,
    OrderListResponse,
    OrderResponse,
    OrderStatusUpdate,
    RecommendationItem,
    RecommendationResponse,
)
from backend.services.recommendation_service import recommendation_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Orders & Cart"])


async def _load_order(db: AsyncSession, order_id: str) -> Optional[Order]:
    """Load an order with its items and associated menu items."""
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.menu_item))
        .where(Order.id == order_id)
    )
    return result.scalar_one_or_none()


# ── Order Endpoints ───────────────────────────────────────────────────────────


@router.get("/orders", response_model=OrderListResponse)
async def list_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    session_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> OrderListResponse:
    """List orders with pagination and optional status/session filters."""
    stmt = select(Order).options(
        selectinload(Order.items).selectinload(OrderItem.menu_item)
    )
    count_stmt = select(func.count(Order.id))

    if status_filter:
        stmt = stmt.where(Order.status == status_filter)
        count_stmt = count_stmt.where(Order.status == status_filter)
    if session_id:
        sid = normalize_uuid(session_id)
        stmt = stmt.where(Order.session_id == sid)
        count_stmt = count_stmt.where(Order.session_id == sid)

    total_res = await db.execute(count_stmt)
    total = total_res.scalar() or 0

    stmt = stmt.order_by(desc(Order.created_at)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    orders = result.scalars().all()

    return OrderListResponse(
        orders=[OrderResponse.model_validate(o) for o in orders],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    """Get order details by ID."""
    order = await _load_order(db, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return OrderResponse.model_validate(order)


@router.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    """Create an order from a session's cart or create an empty pending order."""
    if payload.session_id:
        res = await checkout_session_cart(db, payload.session_id, notes=payload.notes)
        if not res["success"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=res["message"])
        order = await _load_order(db, res["order_id"])
        return OrderResponse.model_validate(order)

    order = Order(
        session_id=None,
        status="pending",
        total_amount=Decimal("0.00"),
        notes=payload.notes,
    )
    db.add(order)
    await db.flush()
    loaded = await _load_order(db, str(order.id))
    return OrderResponse.model_validate(loaded)


@router.put("/orders/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: str,
    payload: OrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    """Update an order's fulfillment status."""
    order = await _load_order(db, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    order.status = payload.status
    if payload.notes is not None:
        order.notes = payload.notes
    await db.flush()

    refreshed = await _load_order(db, order_id)
    return OrderResponse.model_validate(refreshed)


# ── Cart Endpoints ────────────────────────────────────────────────────────────


@router.get("/cart/{session_id}", response_model=CartResponse)
async def get_cart(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> CartResponse:
    """Get the current cart for a session."""
    await ensure_session_exists(db, session_id)
    cart_data = await build_cart_response(db, session_id)
    return CartResponse(**cart_data)


@router.post("/cart/{session_id}/add", response_model=CartResponse)
async def add_to_cart(
    session_id: str,
    payload: CartItemAdd,
    db: AsyncSession = Depends(get_db),
) -> CartResponse:
    """Add an item to a session's cart."""
    result = await add_item_to_session_cart(
        db=db,
        session_id=session_id,
        menu_item_id=payload.menu_item_id,
        quantity=payload.quantity,
        customizations=payload.customizations,
    )
    if not result["success"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["message"])
    return CartResponse(**result["cart"])


@router.delete("/cart/{session_id}/item/{item_id}", response_model=CartResponse)
async def remove_from_cart(
    session_id: str,
    item_id: str,
    quantity: Optional[int] = Query(None, ge=1),
    db: AsyncSession = Depends(get_db),
) -> CartResponse:
    """Remove an item (or decrement quantity) from a session's cart."""
    result = await remove_item_from_session_cart(
        db=db,
        session_id=session_id,
        menu_item_id=item_id,
        quantity=quantity,
    )
    if not result["success"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["message"])
    return CartResponse(**result["cart"])


@router.post("/cart/{session_id}/checkout", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def checkout_cart(
    session_id: str,
    payload: Optional[OrderCreate] = Body(default=None),
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    """Checkout a session's cart and create a confirmed order."""
    notes = payload.notes if payload else None
    result = await checkout_session_cart(db=db, session_id=session_id, notes=notes)
    if not result["success"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["message"])

    order = await _load_order(db, result["order_id"])
    return OrderResponse.model_validate(order)


# ── Recommendation Endpoint ───────────────────────────────────────────────────


@router.get("/recommendations/{session_id}", response_model=RecommendationResponse)
async def get_recommendations(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> RecommendationResponse:
    """Get FP-Growth personalized recommendations for a session's current cart."""
    sid = normalize_uuid(session_id)
    cart_data = await build_cart_response(db, sid)
    cart_item_ids = [item["menu_item_id"] for item in cart_data["items"]]
    menu_items = await get_all_menu_items_cached(db, available_only=True)

    raw_recs = await recommendation_service.get_recommendations_with_details(
        session_id=sid,
        cart_item_ids=cart_item_ids,
        menu_items=menu_items,
    )

    return RecommendationResponse(
        session_id=sid,
        recommendations=[
            RecommendationItem(
                menu_item=MenuItemResponse(**rec["menu_item"]),
                score=float(rec["score"]),
                reason=rec["reason"],
            )
            for rec in raw_recs
        ],
    )
