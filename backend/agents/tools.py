"""LLM tool definitions and execution handlers for VoiceServe AI."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.database import Cart, Menu, Order, OrderItem, Session
from backend.services.cache_service import cache_service
from backend.services.recommendation_service import recommendation_service
from backend.services.vector_service import vector_service

logger = logging.getLogger(__name__)

# ── Shared Helpers (reused by agents and routers) ─────────────────────────────


def normalize_uuid(raw_id: str) -> str:
    """Return a canonical UUID string; deterministically hash non-UUID identifiers."""
    try:
        return str(uuid.UUID(str(raw_id)))
    except (ValueError, AttributeError):
        return str(uuid.uuid5(uuid.NAMESPACE_OID, str(raw_id)))


def menu_item_to_dict(item: Menu) -> Dict[str, Any]:
    """Serialize a Menu ORM instance to a JSON-compatible dictionary."""
    return {
        "id": str(item.id),
        "name": item.name,
        "description": item.description,
        "price": float(item.price),
        "category": item.category,
        "tags": item.tags or [],
        "is_available": item.is_available,
        "image_url": item.image_url,
        "calories": item.calories,
        "allergens": item.allergens or [],
        "preparation_time_minutes": item.preparation_time_minutes,
        "embedding_synced": item.embedding_synced,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


async def ensure_session_exists(
    db: AsyncSession,
    session_id: str,
    language: str = "en-IN",
) -> Session:
    """Fetch an existing Session or create one if absent."""
    sid = normalize_uuid(session_id)
    result = await db.execute(select(Session).where(Session.id == sid))
    session = result.scalar_one_or_none()
    if session is None:
        session = Session(
            id=sid,
            is_active=True,
            conversation_history=[],
            context={"raw_session_id": session_id},
            language=language,
        )
        db.add(session)
        await db.flush()
    return session


async def get_all_menu_items_cached(
    db: AsyncSession,
    available_only: bool = False,
) -> List[Dict[str, Any]]:
    """Return all menu items from Redis cache or PostgreSQL (populating cache)."""
    if cache_service.is_connected:
        cached = await cache_service.get_menu()
        if cached is not None:
            return [m for m in cached if m.get("is_available", True)] if available_only else cached

    result = await db.execute(select(Menu).order_by(Menu.category, Menu.name))
    items = [menu_item_to_dict(m) for m in result.scalars().all()]

    if cache_service.is_connected:
        await cache_service.set_menu(items)
        for item in items:
            await cache_service.set_menu_item(item["id"], item)

    return [m for m in items if m.get("is_available", True)] if available_only else items


async def build_cart_response(
    db: AsyncSession,
    session_id: str,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """Build a CartResponse-compatible dict for a session."""
    sid = normalize_uuid(session_id)
    if use_cache and cache_service.is_connected:
        cached = await cache_service.get_cart(sid)
        if cached is not None:
            return cached

    result = await db.execute(
        select(Cart)
        .options(selectinload(Cart.menu_item))
        .where(Cart.session_id == sid)
        .order_by(Cart.added_at)
    )
    rows = result.scalars().all()

    items: List[Dict[str, Any]] = []
    total = Decimal("0.00")
    item_count = 0

    for row in rows:
        menu_dict = menu_item_to_dict(row.menu_item) if row.menu_item else None
        if row.menu_item:
            total += Decimal(str(row.menu_item.price)) * row.quantity
        item_count += row.quantity
        items.append({
            "id": str(row.id),
            "session_id": str(row.session_id),
            "menu_item_id": str(row.menu_item_id),
            "quantity": row.quantity,
            "customizations": row.customizations or {},
            "added_at": row.added_at.isoformat() if row.added_at else None,
            "menu_item": menu_dict,
        })

    cart_data = {
        "session_id": sid,
        "items": items,
        "total": str(total.quantize(Decimal("0.01"))),
        "item_count": item_count,
    }
    if cache_service.is_connected:
        await cache_service.set_cart(sid, cart_data)
    return cart_data


async def resolve_menu_item(
    db: AsyncSession,
    menu_item_id: Optional[str] = None,
    item_name: Optional[str] = None,
) -> Optional[Menu]:
    """Resolve a Menu item by UUID or case-insensitive name match."""
    if menu_item_id:
        try:
            uid = str(uuid.UUID(str(menu_item_id)))
            res = await db.execute(select(Menu).where(Menu.id == uid))
            found = res.scalar_one_or_none()
            if found:
                return found
        except ValueError:
            pass

    if item_name:
        res = await db.execute(
            select(Menu).where(Menu.name.ilike(f"%{item_name.strip()}%")).limit(1)
        )
        return res.scalar_one_or_none()

    return None


async def add_item_to_session_cart(
    db: AsyncSession,
    session_id: str,
    menu_item_id: Optional[str] = None,
    item_name: Optional[str] = None,
    quantity: int = 1,
    customizations: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Add or increment an item in the session's cart and refresh Redis cache."""
    if quantity < 1:
        return {"success": False, "message": "Quantity must be at least 1."}

    sid = normalize_uuid(session_id)
    await ensure_session_exists(db, session_id)

    menu_item = await resolve_menu_item(db, menu_item_id=menu_item_id, item_name=item_name)
    if menu_item is None:
        return {"success": False, "message": "Menu item not found."}
    if not menu_item.is_available:
        return {"success": False, "message": f"{menu_item.name} is currently unavailable."}

    existing_res = await db.execute(
        select(Cart).where(Cart.session_id == sid, Cart.menu_item_id == menu_item.id)
    )
    cart_row = existing_res.scalar_one_or_none()

    if cart_row:
        cart_row.quantity = min(cart_row.quantity + quantity, 99)
        if customizations:
            merged = dict(cart_row.customizations or {})
            merged.update(customizations)
            cart_row.customizations = merged
    else:
        cart_row = Cart(
            session_id=sid,
            menu_item_id=menu_item.id,
            quantity=min(quantity, 99),
            customizations=customizations or {},
        )
        db.add(cart_row)

    await db.flush()
    if cache_service.is_connected:
        await cache_service.invalidate_cart(sid)
        await cache_service.delete(f"recs:{sid}")
    cart = await build_cart_response(db, sid, use_cache=False)

    return {
        "success": True,
        "message": f"Added {quantity}x {menu_item.name} to cart.",
        "added_item": menu_item_to_dict(menu_item),
        "cart": cart,
    }


async def remove_item_from_session_cart(
    db: AsyncSession,
    session_id: str,
    menu_item_id: Optional[str] = None,
    item_name: Optional[str] = None,
    quantity: Optional[int] = None,
) -> Dict[str, Any]:
    """Remove or decrement an item from the session's cart."""
    sid = normalize_uuid(session_id)
    target_id = menu_item_id

    if not target_id and item_name:
        menu_item = await resolve_menu_item(db, item_name=item_name)
        if menu_item:
            target_id = str(menu_item.id)

    if not target_id:
        return {"success": False, "message": "Could not identify item to remove."}

    res = await db.execute(
        select(Cart)
        .options(selectinload(Cart.menu_item))
        .where(Cart.session_id == sid, Cart.menu_item_id == target_id)
    )
    cart_row = res.scalar_one_or_none()
    if cart_row is None:
        return {"success": False, "message": "Item is not in your cart."}

    item_label = cart_row.menu_item.name if cart_row.menu_item else target_id

    if quantity is not None and quantity > 0 and cart_row.quantity > quantity:
        cart_row.quantity -= quantity
        msg = f"Reduced {item_label} quantity to {cart_row.quantity}."
    else:
        await db.delete(cart_row)
        msg = f"Removed {item_label} from cart."

    await db.flush()
    if cache_service.is_connected:
        await cache_service.invalidate_cart(sid)
        await cache_service.delete(f"recs:{sid}")
    cart = await build_cart_response(db, sid, use_cache=False)
    return {"success": True, "message": msg, "cart": cart}


async def validate_session_cart(db: AsyncSession, session_id: str) -> Dict[str, Any]:
    """Validate that the cart is non-empty and all items are available."""
    sid = normalize_uuid(session_id)
    result = await db.execute(
        select(Cart).options(selectinload(Cart.menu_item)).where(Cart.session_id == sid)
    )
    rows = result.scalars().all()
    if not rows:
        return {
            "valid": False,
            "errors": ["Your cart is empty."],
            "warnings": [],
            "total": "0.00",
            "item_count": 0,
        }

    errors: List[str] = []
    warnings: List[str] = []
    total = Decimal("0.00")
    item_count = 0
    max_prep = 0

    for row in rows:
        if row.menu_item is None:
            errors.append(f"Item {row.menu_item_id} no longer exists on the menu.")
            continue
        if not row.menu_item.is_available:
            errors.append(f"{row.menu_item.name} is currently out of stock.")
            continue
        if row.quantity < 1:
            errors.append(f"Invalid quantity for {row.menu_item.name}.")
            continue
        total += Decimal(str(row.menu_item.price)) * row.quantity
        item_count += row.quantity
        if row.menu_item.preparation_time_minutes:
            max_prep = max(max_prep, row.menu_item.preparation_time_minutes)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "total": str(total.quantize(Decimal("0.01"))),
        "item_count": item_count,
        "estimated_prep_time_minutes": max_prep or 15,
    }


async def checkout_session_cart(
    db: AsyncSession,
    session_id: str,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate cart, create an Order + OrderItems, and clear the cart."""
    sid = normalize_uuid(session_id)
    await ensure_session_exists(db, session_id)

    validation = await validate_session_cart(db, sid)
    if not validation["valid"]:
        return {
            "success": False,
            "message": "; ".join(validation["errors"]),
            "errors": validation["errors"],
        }

    cart_res = await db.execute(
        select(Cart).options(selectinload(Cart.menu_item)).where(Cart.session_id == sid)
    )
    cart_rows = cart_res.scalars().all()

    total_amount = Decimal("0.00")
    order = Order(
        session_id=sid,
        status="confirmed",
        total_amount=Decimal("0.00"),
        notes=notes,
        metadata_={"source": "voiceserve"},
    )
    db.add(order)
    await db.flush()

    order_items_summary: List[Dict[str, Any]] = []
    for row in cart_rows:
        unit_price = Decimal(str(row.menu_item.price))
        total_amount += unit_price * row.quantity
        order_item = OrderItem(
            order_id=order.id,
            menu_item_id=row.menu_item_id,
            quantity=row.quantity,
            unit_price=unit_price,
            customizations=row.customizations or {},
        )
        db.add(order_item)
        order_items_summary.append({
            "name": row.menu_item.name,
            "quantity": row.quantity,
            "unit_price": float(unit_price),
        })

    order.total_amount = total_amount.quantize(Decimal("0.01"))
    await db.execute(delete(Cart).where(Cart.session_id == sid))
    await db.flush()

    if cache_service.is_connected:
        await cache_service.invalidate_cart(sid)
        await cache_service.delete(f"recs:{sid}")

    empty_cart = {"session_id": sid, "items": [], "total": "0.00", "item_count": 0}
    return {
        "success": True,
        "order_id": str(order.id),
        "status": order.status,
        "total_amount": float(order.total_amount),
        "estimated_prep_time_minutes": validation.get("estimated_prep_time_minutes", 15),
        "items": order_items_summary,
        "cart": empty_cart,
        "message": f"Order confirmed! Total is ${float(order.total_amount):.2f}.",
    }


# ── OpenAI-compatible Tool Definitions ────────────────────────────────────────

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_menu",
            "description": "Search the restaurant menu using natural language, item names, categories, or dietary tags (e.g., spicy, vegetarian, dessert, drinks).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language query or item name to search for.",
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category filter (e.g., Burgers, Sides, Drinks, Desserts).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of matching items to return (default 5).",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_cart",
            "description": "Add a menu item to the customer's cart.",
            "parameters": {
                "type": "object",
                "properties": {
                    "menu_item_id": {
                        "type": "string",
                        "description": "UUID of the menu item from search_menu.",
                    },
                    "item_name": {
                        "type": "string",
                        "description": "Name of the menu item if ID is not yet known.",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "Quantity to add (default 1).",
                        "default": 1,
                    },
                    "customizations": {
                        "type": "object",
                        "description": "Optional customizations such as spice_level, extra_cheese, no_onions.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_from_cart",
            "description": "Remove an item or reduce its quantity in the customer's cart.",
            "parameters": {
                "type": "object",
                "properties": {
                    "menu_item_id": {
                        "type": "string",
                        "description": "UUID of the menu item to remove.",
                    },
                    "item_name": {
                        "type": "string",
                        "description": "Name of the item to remove.",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "Quantity to remove; omit to remove the item completely.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cart",
            "description": "Get the current items, quantities, and total price in the customer's cart.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_order",
            "description": "Validate the customer's cart items and availability before placing the order.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "checkout",
            "description": "Finalize and place the customer's order from their current cart.",
            "parameters": {
                "type": "object",
                "properties": {
                    "notes": {
                        "type": "string",
                        "description": "Optional special instructions or delivery notes.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recommendations",
            "description": "Get smart add-on and pairing recommendations based on the items currently in the cart.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]


# ── Tool Handlers ─────────────────────────────────────────────────────────────


async def _handle_search_menu(
    arguments: Dict[str, Any],
    session_id: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    query = (arguments.get("query") or "").strip()
    category = (arguments.get("category") or "").strip().lower()
    limit = min(max(int(arguments.get("limit") or 5), 1), 15)

    all_items = await get_all_menu_items_cached(db, available_only=True)
    item_by_id = {item["id"]: item for item in all_items}

    # Try Pinecone semantic search first if connected
    matched_items: List[Dict[str, Any]] = []
    if query and vector_service.is_connected:
        vector_hits = await vector_service.search_menu(query=query, top_k=limit)
        for hit in vector_hits:
            item = item_by_id.get(hit["id"])
            if item:
                if category and category not in item["category"].lower():
                    continue
                matched_items.append(item)

    # Fallback / supplement with keyword & tag matching over cached menu
    if not matched_items:
        tokens = [t for t in query.lower().split() if t]
        scored: List[tuple[int, Dict[str, Any]]] = []
        for item in all_items:
            if category and category not in item["category"].lower():
                continue
            haystack = " ".join([
                item.get("name") or "",
                item.get("description") or "",
                item.get("category") or "",
                " ".join(item.get("tags") or []),
            ]).lower()
            if not tokens:
                scored.append((1, item))
            else:
                hits = sum(1 for tok in tokens if tok in haystack)
                if hits > 0:
                    scored.append((hits, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        matched_items = [pair[1] for pair in scored[:limit]]

    return {
        "success": True,
        "count": len(matched_items),
        "items": [
            {
                "id": it["id"],
                "name": it["name"],
                "price": it["price"],
                "category": it["category"],
                "description": it["description"],
                "tags": it["tags"],
                "calories": it["calories"],
            }
            for it in matched_items[:limit]
        ],
    }


async def _handle_add_to_cart(
    arguments: Dict[str, Any],
    session_id: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    return await add_item_to_session_cart(
        db=db,
        session_id=session_id,
        menu_item_id=arguments.get("menu_item_id"),
        item_name=arguments.get("item_name"),
        quantity=int(arguments.get("quantity") or 1),
        customizations=arguments.get("customizations"),
    )


async def _handle_remove_from_cart(
    arguments: Dict[str, Any],
    session_id: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    qty = arguments.get("quantity")
    return await remove_item_from_session_cart(
        db=db,
        session_id=session_id,
        menu_item_id=arguments.get("menu_item_id"),
        item_name=arguments.get("item_name"),
        quantity=int(qty) if qty is not None else None,
    )


async def _handle_get_cart(
    arguments: Dict[str, Any],
    session_id: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    cart = await build_cart_response(db, session_id)
    return {"success": True, "cart": cart}


async def _handle_validate_order(
    arguments: Dict[str, Any],
    session_id: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    return await validate_session_cart(db, session_id)


async def _handle_checkout(
    arguments: Dict[str, Any],
    session_id: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    return await checkout_session_cart(db, session_id, notes=arguments.get("notes"))


async def _handle_get_recommendations(
    arguments: Dict[str, Any],
    session_id: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    cart = await build_cart_response(db, session_id)
    cart_item_ids = [item["menu_item_id"] for item in cart["items"]]
    menu_items = await get_all_menu_items_cached(db, available_only=True)
    recs = await recommendation_service.get_recommendations_with_details(
        session_id=normalize_uuid(session_id),
        cart_item_ids=cart_item_ids,
        menu_items=menu_items,
    )
    return {
        "success": True,
        "recommendations": [
            {
                "id": r["menu_item"]["id"],
                "name": r["menu_item"]["name"],
                "price": r["menu_item"]["price"],
                "category": r["menu_item"]["category"],
                "score": r["score"],
                "reason": r["reason"],
            }
            for r in recs
        ],
    }


_TOOL_HANDLERS = {
    "search_menu": _handle_search_menu,
    "add_to_cart": _handle_add_to_cart,
    "remove_from_cart": _handle_remove_from_cart,
    "get_cart": _handle_get_cart,
    "validate_order": _handle_validate_order,
    "checkout": _handle_checkout,
    "get_recommendations": _handle_get_recommendations,
}


async def execute_tool(
    tool_name: str,
    arguments: Dict[str, Any],
    session_id: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    """Dispatch an LLM tool call to its handler and return JSON-serializable output."""
    handler = _TOOL_HANDLERS.get(tool_name)
    if handler is None:
        logger.warning("Unknown tool requested: %s", tool_name)
        return {"success": False, "message": f"Unknown tool: {tool_name}"}

    try:
        return await handler(arguments or {}, session_id, db)
    except Exception as exc:
        logger.exception("Tool execution failed for %s: %s", tool_name, exc)
        return {"success": False, "message": f"Tool execution error: {exc}"}
