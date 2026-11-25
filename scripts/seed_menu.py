"""Seed sample restaurant menu items and historical orders for VoiceServe AI."""

from __future__ import annotations

import asyncio
import logging
import sys
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

# Allow running directly via `python scripts/seed_menu.py`
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import func, select

from backend.agents.tools import menu_item_to_dict
from backend.database import close_db, get_db_session, init_db
from backend.models.database import Menu, Order, OrderItem
from backend.services.vector_service import vector_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_menu")

SAMPLE_MENU: List[Dict] = [
    {
        "name": "Classic Smash Burger",
        "description": "Double smashed beef patty, aged cheddar, caramelized onions, house pickles, and brioche bun.",
        "price": Decimal("11.99"),
        "category": "Burgers",
        "tags": ["bestseller", "savory", "beef"],
        "calories": 720,
        "allergens": ["gluten", "dairy"],
        "preparation_time_minutes": 12,
    },
    {
        "name": "Spicy Crispy Chicken Burger",
        "description": "Buttermilk fried chicken glazed in chili-garlic oil with slaw and jalapeño aioli.",
        "price": Decimal("12.49"),
        "category": "Burgers",
        "tags": ["spicy", "crispy", "bestseller"],
        "calories": 760,
        "allergens": ["gluten", "dairy", "eggs"],
        "preparation_time_minutes": 14,
    },
    {
        "name": "Truffle Mushroom Veggie Burger",
        "description": "Char-grilled portobello and black bean patty with roasted garlic truffle mayo and arugula.",
        "price": Decimal("11.49"),
        "category": "Burgers",
        "tags": ["vegetarian", "gourmet"],
        "calories": 580,
        "allergens": ["gluten"],
        "preparation_time_minutes": 12,
    },
    {
        "name": "Paneer Tikka Wrap",
        "description": "Tandoor-charred cottage cheese cubes, mint chutney, pickled red onions in warm flatbread.",
        "price": Decimal("10.99"),
        "category": "Mains",
        "tags": ["vegetarian", "spicy", "indian-fusion"],
        "calories": 540,
        "allergens": ["gluten", "dairy"],
        "preparation_time_minutes": 10,
    },
    {
        "name": "Margherita Wood-Fired Pizza",
        "description": "San Marzano tomato sauce, fresh buffalo mozzarella, basil leaves, and extra virgin olive oil.",
        "price": Decimal("13.99"),
        "category": "Mains",
        "tags": ["vegetarian", "classic"],
        "calories": 820,
        "allergens": ["gluten", "dairy"],
        "preparation_time_minutes": 15,
    },
    {
        "name": "Quinoa Harvest Bowl",
        "description": "Roasted sweet potatoes, avocado, chickpeas, baby kale, and lemon-tahini dressing.",
        "price": Decimal("12.99"),
        "category": "Mains",
        "tags": ["vegan", "vegetarian", "gluten-free", "healthy"],
        "calories": 460,
        "allergens": ["sesame"],
        "preparation_time_minutes": 9,
    },
    {
        "name": "Crispy Truffle Fries",
        "description": "Hand-cut shoestring fries tossed in white truffle oil, parmesan, and fresh parsley.",
        "price": Decimal("5.49"),
        "category": "Sides",
        "tags": ["vegetarian", "bestseller", "crispy"],
        "calories": 410,
        "allergens": ["dairy"],
        "preparation_time_minutes": 7,
    },
    {
        "name": "Peri-Peri Sweet Potato Fries",
        "description": "Crispy sweet potato wedges dusted with smoky peri-peri spice and vegan herb dip.",
        "price": Decimal("5.99"),
        "category": "Sides",
        "tags": ["vegan", "vegetarian", "spicy", "gluten-free"],
        "calories": 380,
        "allergens": [],
        "preparation_time_minutes": 8,
    },
    {
        "name": "Roasted Garlic Cheesy Bread",
        "description": "Toasted sourdough batard brushed with roasted garlic butter and melted mozzarella.",
        "price": Decimal("6.49"),
        "category": "Sides",
        "tags": ["vegetarian", "shareable"],
        "calories": 450,
        "allergens": ["gluten", "dairy"],
        "preparation_time_minutes": 8,
    },
    {
        "name": "Craft Cola",
        "description": "Small-batch cane sugar cola brewed with Madagascar vanilla and citrus zest.",
        "price": Decimal("3.49"),
        "category": "Drinks",
        "tags": ["vegan", "gluten-free", "cold", "bestseller"],
        "calories": 140,
        "allergens": [],
        "preparation_time_minutes": 2,
    },
    {
        "name": "Spiced Masala Lemonade",
        "description": "Fresh-squeezed lime & lemon cooler infused with mint, roasted cumin, and sparkling water.",
        "price": Decimal("4.29"),
        "category": "Drinks",
        "tags": ["vegan", "gluten-free", "refreshing", "tangy"],
        "calories": 95,
        "allergens": [],
        "preparation_time_minutes": 3,
    },
    {
        "name": "Mango Lassi Smoothie",
        "description": "Creamy Alphonso mango blended with probiotic yogurt and a hint of cardamom.",
        "price": Decimal("4.99"),
        "category": "Drinks",
        "tags": ["vegetarian", "gluten-free", "sweet"],
        "calories": 240,
        "allergens": ["dairy"],
        "preparation_time_minutes": 3,
    },
    {
        "name": "Cold Brew Iced Coffee",
        "description": "18-hour slow-steeped single-origin Arabica served over crystal ice.",
        "price": Decimal("4.49"),
        "category": "Drinks",
        "tags": ["vegan", "gluten-free", "caffeine"],
        "calories": 15,
        "allergens": [],
        "preparation_time_minutes": 2,
    },
    {
        "name": "Warm Chocolate Lava Cake",
        "description": "Rich 70% dark chocolate fondant with a molten center and vanilla bean gelato.",
        "price": Decimal("6.99"),
        "category": "Desserts",
        "tags": ["vegetarian", "sweet", "bestseller"],
        "calories": 520,
        "allergens": ["gluten", "dairy", "eggs"],
        "preparation_time_minutes": 10,
    },
    {
        "name": "Classic Espresso Tiramisu",
        "description": "Espresso-soaked savoiardi layered with whipped mascarpone and Dutch cocoa.",
        "price": Decimal("6.49"),
        "category": "Desserts",
        "tags": ["vegetarian", "sweet"],
        "calories": 430,
        "allergens": ["gluten", "dairy", "eggs"],
        "preparation_time_minutes": 4,
    },
]

# Frequent co-purchase baskets for FP-Growth training
HISTORICAL_BASKETS: List[List[str]] = [
    ["Classic Smash Burger", "Crispy Truffle Fries", "Craft Cola"],
    ["Classic Smash Burger", "Crispy Truffle Fries", "Craft Cola"],
    ["Classic Smash Burger", "Crispy Truffle Fries", "Craft Cola"],
    ["Classic Smash Burger", "Crispy Truffle Fries", "Warm Chocolate Lava Cake"],
    ["Classic Smash Burger", "Craft Cola"],
    ["Spicy Crispy Chicken Burger", "Crispy Truffle Fries", "Spiced Masala Lemonade"],
    ["Spicy Crispy Chicken Burger", "Peri-Peri Sweet Potato Fries", "Spiced Masala Lemonade"],
    ["Spicy Crispy Chicken Burger", "Spiced Masala Lemonade"],
    ["Spicy Crispy Chicken Burger", "Crispy Truffle Fries", "Craft Cola"],
    ["Truffle Mushroom Veggie Burger", "Peri-Peri Sweet Potato Fries", "Cold Brew Iced Coffee"],
    ["Paneer Tikka Wrap", "Spiced Masala Lemonade", "Mango Lassi Smoothie"],
    ["Paneer Tikka Wrap", "Peri-Peri Sweet Potato Fries", "Mango Lassi Smoothie"],
    ["Paneer Tikka Wrap", "Mango Lassi Smoothie"],
    ["Margherita Wood-Fired Pizza", "Roasted Garlic Cheesy Bread", "Classic Espresso Tiramisu"],
    ["Margherita Wood-Fired Pizza", "Roasted Garlic Cheesy Bread", "Craft Cola"],
    ["Margherita Wood-Fired Pizza", "Classic Espresso Tiramisu"],
    ["Quinoa Harvest Bowl", "Cold Brew Iced Coffee"],
    ["Quinoa Harvest Bowl", "Spiced Masala Lemonade"],
    ["Classic Smash Burger", "Crispy Truffle Fries", "Warm Chocolate Lava Cake"],
    ["Spicy Crispy Chicken Burger", "Crispy Truffle Fries", "Warm Chocolate Lava Cake"],
]


async def seed() -> None:
    """Populate menu items and sample orders idempotently."""
    await init_db()

    menu_map: Dict[str, Menu] = {}
    async with get_db_session() as db:
        existing_rows = (await db.execute(select(Menu))).scalars().all()
        existing_by_name = {m.name: m for m in existing_rows}

        inserted = 0
        for item_data in SAMPLE_MENU:
            if item_data["name"] in existing_by_name:
                menu_map[item_data["name"]] = existing_by_name[item_data["name"]]
                continue
            item = Menu(**item_data)
            db.add(item)
            await db.flush()
            menu_map[item.name] = item
            inserted += 1

        logger.info("Menu items: %d inserted, %d already existed.", inserted, len(existing_rows))

        order_count = (await db.execute(select(func.count(Order.id)))).scalar() or 0
        if order_count == 0:
            for idx, basket in enumerate(HISTORICAL_BASKETS, start=1):
                total = Decimal("0.00")
                order = Order(
                    status="delivered",
                    total_amount=Decimal("0.00"),
                    notes=f"Seeded historical order #{idx}",
                )
                db.add(order)
                await db.flush()

                for name in basket:
                    menu_item = menu_map.get(name)
                    if not menu_item:
                        continue
                    total += Decimal(str(menu_item.price))
                    db.add(
                        OrderItem(
                            order_id=order.id,
                            menu_item_id=menu_item.id,
                            quantity=1,
                            unit_price=menu_item.price,
                        )
                    )
                order.total_amount = total
            logger.info("Seeded %d historical orders for FP-Growth recommendations.", len(HISTORICAL_BASKETS))
        else:
            logger.info("Skipped order seeding (%d orders already exist).", order_count)

    # Optionally sync embeddings to Pinecone if configured
    await vector_service.connect()
    if vector_service.is_connected:
        async with get_db_session() as db:
            items = (await db.execute(select(Menu))).scalars().all()
            synced = await vector_service.bulk_upsert_menu([menu_item_to_dict(i) for i in items])
            for it in items:
                it.embedding_synced = True
            logger.info("Synced %d menu items to Pinecone.", synced)
    await vector_service.disconnect()
    await close_db()


if __name__ == "__main__":
    asyncio.run(seed())
