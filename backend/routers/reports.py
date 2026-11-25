"""Analytics and Gemini-driven multilingual reporting endpoints."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import google.generativeai as genai
from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db
from backend.models.database import Menu, Order, OrderItem
from backend.models.schemas import ReportRequest, ReportResponse

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/reports", tags=["Reports"])


async def _fetch_menu_performance(
    db: AsyncSession,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Aggregate menu item sales performance from PostgreSQL."""
    stmt = (
        select(
            Menu.id,
            Menu.name,
            Menu.category,
            Menu.price,
            Menu.is_available,
            func.coalesce(func.sum(OrderItem.quantity), 0).label("units_sold"),
            func.coalesce(
                func.sum(OrderItem.quantity * OrderItem.unit_price), 0
            ).label("revenue"),
        )
        .outerjoin(OrderItem, OrderItem.menu_item_id == Menu.id)
        .outerjoin(Order, Order.id == OrderItem.order_id)
    )

    if date_from:
        stmt = stmt.where((Order.created_at >= date_from) | (Order.id.is_(None)))
    if date_to:
        stmt = stmt.where((Order.created_at <= date_to) | (Order.id.is_(None)))

    stmt = stmt.group_by(Menu.id).order_by(desc("units_sold"), Menu.name)
    rows = (await db.execute(stmt)).all()

    items: List[Dict[str, Any]] = []
    category_totals: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        units = int(row.units_sold or 0)
        rev = float(row.revenue or 0)
        items.append({
            "id": str(row.id),
            "name": row.name,
            "category": row.category,
            "price": float(row.price),
            "is_available": row.is_available,
            "units_sold": units,
            "revenue": round(rev, 2),
        })
        cat_entry = category_totals.setdefault(
            row.category, {"category": row.category, "units_sold": 0, "revenue": 0.0}
        )
        cat_entry["units_sold"] += units
        cat_entry["revenue"] = round(cat_entry["revenue"] + rev, 2)

    return {
        "total_menu_items": len(items),
        "top_items": items[:10],
        "category_breakdown": list(category_totals.values()),
        "items": items,
    }


async def _fetch_sales_summary(
    db: AsyncSession,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Aggregate order and revenue summary from PostgreSQL."""
    stmt = select(Order)
    if date_from:
        stmt = stmt.where(Order.created_at >= date_from)
    if date_to:
        stmt = stmt.where(Order.created_at <= date_to)

    orders = (await db.execute(stmt)).scalars().all()
    total_orders = len(orders)
    non_cancelled = [o for o in orders if o.status != "cancelled"]
    total_revenue = sum(float(o.total_amount or 0) for o in non_cancelled)
    avg_order_value = (total_revenue / len(non_cancelled)) if non_cancelled else 0.0

    status_counts: Dict[str, int] = {}
    for order in orders:
        status_counts[order.status] = status_counts.get(order.status, 0) + 1

    return {
        "total_orders": total_orders,
        "completed_or_active_orders": len(non_cancelled),
        "total_revenue": round(total_revenue, 2),
        "average_order_value": round(avg_order_value, 2),
        "orders_by_status": status_counts,
    }


@router.get("/menu-performance")
async def get_menu_performance(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return menu performance analytics."""
    return await _fetch_menu_performance(db, date_from=date_from, date_to=date_to)


@router.get("/sales-summary")
async def get_sales_summary(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return sales and order volume summary."""
    return await _fetch_sales_summary(db, date_from=date_from, date_to=date_to)


@router.post("/generate", response_model=ReportResponse)
async def generate_ai_report(
    payload: ReportRequest,
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    """Generate a Gemini-powered multilingual restaurant analytics report."""
    menu_perf = await _fetch_menu_performance(
        db, date_from=payload.date_from, date_to=payload.date_to
    )
    sales = await _fetch_sales_summary(
        db, date_from=payload.date_from, date_to=payload.date_to
    )

    analytics_snapshot = {
        "report_type": payload.report_type,
        "sales_summary": sales,
        "top_menu_items": menu_perf["top_items"],
        "category_breakdown": menu_perf["category_breakdown"],
        "extra_context": payload.extra_context,
    }

    api_key = (settings.gemini_api_key or "").strip()
    if api_key and not api_key.startswith("your-"):
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(settings.gemini_model)
            prompt = (
                f"You are an expert restaurant business analyst.\n"
                f"Generate a concise, actionable '{payload.report_type}' report "
                f"written entirely in language code '{payload.language}'.\n"
                f"Use Markdown formatting with bullet points, key KPIs, top performers, "
                f"and 3 concrete recommendations.\n\n"
                f"Analytics Data:\n{json.dumps(analytics_snapshot, indent=2)}"
            )
            response = await model.generate_content_async(prompt)
            content = (response.text or "").strip()
            if content:
                return ReportResponse(
                    report_type=payload.report_type,
                    language=payload.language,
                    content=content,
                    generated_at=datetime.now(timezone.utc),
                    model_used=settings.gemini_model,
                )
        except Exception as exc:
            logger.error("Gemini report generation failed: %s", exc)

    # Deterministic fallback when Gemini API key is not configured
    top_names = ", ".join(
        f"{it['name']} ({it['units_sold']} sold)" for it in menu_perf["top_items"][:5]
    ) or "No sales recorded yet"
    fallback_content = (
        f"## {payload.report_type.replace('_', ' ').title()} ({payload.language})\n\n"
        f"- **Total Orders:** {sales['total_orders']}\n"
        f"- **Total Revenue:** ${sales['total_revenue']:.2f}\n"
        f"- **Average Order Value:** ${sales['average_order_value']:.2f}\n"
        f"- **Top Items:** {top_names}\n"
        f"- **Orders by Status:** {json.dumps(sales['orders_by_status'])}\n\n"
        f"_Configure `GEMINI_API_KEY` to enable full Gemini AI multilingual narrative insights._"
    )
    return ReportResponse(
        report_type=payload.report_type,
        language=payload.language,
        content=fallback_content,
        generated_at=datetime.now(timezone.utc),
        model_used="fallback-summary",
    )
