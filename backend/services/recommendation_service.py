"""FP-Growth based recommendation service for smart menu suggestions."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd
from mlxtend.frequent_patterns import association_rules, fpgrowth
from mlxtend.preprocessing import TransactionEncoder
from sqlalchemy import select, text

from backend.config import get_settings
from backend.services.cache_service import cache_service

logger = logging.getLogger(__name__)
settings = get_settings()


class RecommendationService:
    """
    FP-Growth based association rule mining for menu recommendations.

    Analyzes historical order data to find frequently co-purchased items
    and uses association rules to generate relevant suggestions.
    """

    def __init__(self) -> None:
        self._rules: Optional[pd.DataFrame] = None
        self._item_lookup: Dict[str, Dict] = {}  # item_id -> item metadata
        self._trained: bool = False

    async def train(self, db_session) -> None:
        """
        Train the FP-Growth model on historical order data.

        Args:
            db_session: Async SQLAlchemy session.
        """
        from backend.models.database import Order, OrderItem

        # Fetch all completed orders with their items
        result = await db_session.execute(
            select(OrderItem.order_id, OrderItem.menu_item_id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.status.in_(["delivered", "confirmed", "ready"]))
        )
        rows = result.fetchall()

        if not rows:
            logger.warning("No order data available for FP-Growth training.")
            return

        # Build transaction list: each order is a list of item IDs
        transactions: Dict[str, List[str]] = {}
        for order_id, item_id in rows:
            transactions.setdefault(str(order_id), []).append(str(item_id))

        transaction_list = list(transactions.values())
        if len(transaction_list) < 5:
            logger.info("Insufficient data for FP-Growth (%d orders).", len(transaction_list))
            return

        # Encode transactions
        te = TransactionEncoder()
        te_array = te.fit_transform(transaction_list)
        df = pd.DataFrame(te_array, columns=te.columns_)

        # Mine frequent itemsets
        try:
            frequent_itemsets = fpgrowth(
                df,
                min_support=settings.fpgrowth_min_support,
                use_colnames=True,
            )
        except Exception as exc:
            logger.error("FP-Growth mining error: %s", exc)
            return

        if frequent_itemsets.empty:
            logger.info("No frequent itemsets found.")
            return

        # Generate association rules
        try:
            self._rules = association_rules(
                frequent_itemsets,
                metric="confidence",
                min_threshold=settings.fpgrowth_min_confidence,
            )
            self._rules = self._rules.sort_values("lift", ascending=False)
        except Exception as exc:
            logger.error("Association rules error: %s", exc)
            return

        self._trained = True
        logger.info(
            "FP-Growth trained: %d rules from %d orders.",
            len(self._rules),
            len(transaction_list),
        )

    def get_recommendations(
        self,
        cart_item_ids: List[str],
        exclude_ids: Optional[Set[str]] = None,
    ) -> List[Tuple[str, float]]:
        """
        Get item recommendations based on current cart contents.

        Args:
            cart_item_ids: List of item IDs currently in the cart.
            exclude_ids: Item IDs to exclude from results (already in cart, etc.)

        Returns:
            List of (item_id, confidence_score) tuples, sorted by relevance.
        """
        if not self._trained or self._rules is None or self._rules.empty:
            return []

        exclude = set(cart_item_ids) | (exclude_ids or set())
        cart_set = frozenset(cart_item_ids)
        recommendations: Dict[str, float] = {}

        for _, rule in self._rules.iterrows():
            antecedent = rule["antecedents"]
            consequent = rule["consequents"]
            confidence = float(rule["confidence"])
            lift = float(rule["lift"])

            # Check if antecedent is a subset of cart
            if antecedent.issubset(cart_set):
                for item_id in consequent:
                    if item_id not in exclude:
                        # Score = confidence * lift (bounded to 1.0)
                        score = min(confidence * lift / 3.0, 1.0)
                        recommendations[item_id] = max(
                            recommendations.get(item_id, 0.0), score
                        )

        # Sort and limit
        sorted_recs = sorted(recommendations.items(), key=lambda x: x[1], reverse=True)
        return sorted_recs[: settings.fpgrowth_max_recommendations]

    async def get_recommendations_with_details(
        self,
        session_id: str,
        cart_item_ids: List[str],
        menu_items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Get recommendations with full menu item details.

        Args:
            session_id: Session ID for cache lookups.
            cart_item_ids: Items currently in cart.
            menu_items: All available menu items.

        Returns:
            List of recommendation dicts with item details and scores.
        """
        # Check cache first
        cached = await cache_service.get_recommendations(session_id)
        if cached:
            return cached

        item_map = {str(item["id"]): item for item in menu_items}
        raw_recs = self.get_recommendations(cart_item_ids)

        if not raw_recs:
            # Fallback: recommend popular items (top 3 from most common in item_map)
            popular = list(menu_items)[:3]
            recs = [
                {
                    "menu_item": item,
                    "score": 0.5,
                    "reason": "Popular item",
                }
                for item in popular
                if str(item["id"]) not in cart_item_ids
            ]
        else:
            recs = []
            for item_id, score in raw_recs:
                if item_id in item_map:
                    recs.append({
                        "menu_item": item_map[item_id],
                        "score": round(score, 3),
                        "reason": self._generate_reason(score),
                    })

        await cache_service.set_recommendations(session_id, recs)
        return recs

    def _generate_reason(self, score: float) -> str:
        """Generate a human-readable reason for a recommendation."""
        if score >= 0.8:
            return "Customers who ordered similar items almost always get this too"
        elif score >= 0.6:
            return "Frequently ordered together"
        elif score >= 0.4:
            return "Popular pairing"
        else:
            return "Others also enjoyed this"


# Global singleton
recommendation_service = RecommendationService()
