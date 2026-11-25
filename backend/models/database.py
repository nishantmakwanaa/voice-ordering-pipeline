"""SQLAlchemy ORM models for VoiceServe AI."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Menu(Base):
    """Restaurant menu item."""

    __tablename__ = "menu_items"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    tags: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), default=list)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    image_url: Mapped[Optional[str]] = mapped_column(String(500))
    calories: Mapped[Optional[int]] = mapped_column(Integer)
    allergens: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), default=list)
    preparation_time_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    # Embedding stored externally in Pinecone; this is a flag for sync state
    embedding_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    order_items: Mapped[List["OrderItem"]] = relationship(
        "OrderItem", back_populates="menu_item"
    )
    cart_items: Mapped[List["Cart"]] = relationship("Cart", back_populates="menu_item")


class Order(Base):
    """Customer order."""

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    session_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False, index=True
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )
    notes: Mapped[Optional[str]] = mapped_column(Text)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    session: Mapped[Optional["Session"]] = relationship("Session", back_populates="orders")
    items: Mapped[List["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    """Individual line item in an order."""

    __tablename__ = "order_items"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    menu_item_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("menu_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    customizations: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    order: Mapped["Order"] = relationship("Order", back_populates="items")
    menu_item: Mapped["Menu"] = relationship("Menu", back_populates="order_items")


class Session(Base):
    """Voice ordering session."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    conversation_history: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    context: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    language: Mapped[str] = mapped_column(String(10), default="en-IN", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    orders: Mapped[List["Order"]] = relationship("Order", back_populates="session")
    cart_items: Mapped[List["Cart"]] = relationship(
        "Cart", back_populates="session", cascade="all, delete-orphan"
    )


class Cart(Base):
    """Shopping cart item (linked to a session)."""

    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("session_id", "menu_item_id", name="uq_cart_session_item"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    session_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    menu_item_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("menu_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    customizations: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped["Session"] = relationship("Session", back_populates="cart_items")
    menu_item: Mapped["Menu"] = relationship("Menu", back_populates="cart_items")
