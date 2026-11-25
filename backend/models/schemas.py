"""Pydantic schemas for request/response validation."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Menu Schemas ──────────────────────────────────────────────────────────────

class MenuItemBase(BaseModel):
    """Shared fields for menu item schemas."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    price: Decimal = Field(..., ge=0, decimal_places=2)
    category: str = Field(..., min_length=1, max_length=100)
    tags: List[str] = Field(default_factory=list)
    is_available: bool = True
    image_url: Optional[str] = None
    calories: Optional[int] = Field(None, ge=0)
    allergens: List[str] = Field(default_factory=list)
    preparation_time_minutes: Optional[int] = Field(None, ge=0)


class MenuItemCreate(MenuItemBase):
    """Schema for creating a new menu item."""
    pass


class MenuItemUpdate(BaseModel):
    """Schema for partially updating a menu item."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    price: Optional[Decimal] = Field(None, ge=0)
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    is_available: Optional[bool] = None
    image_url: Optional[str] = None
    calories: Optional[int] = None
    allergens: Optional[List[str]] = None
    preparation_time_minutes: Optional[int] = None


class MenuItemResponse(MenuItemBase):
    """Schema for returning a menu item."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    embedding_synced: bool
    created_at: datetime
    updated_at: datetime


class MenuListResponse(BaseModel):
    """Paginated menu list response."""
    items: List[MenuItemResponse]
    total: int
    page: int
    page_size: int


# ── Cart Schemas ──────────────────────────────────────────────────────────────

class CartItemBase(BaseModel):
    """Shared cart item fields."""
    menu_item_id: str
    quantity: int = Field(1, ge=1, le=99)
    customizations: Dict[str, Any] = Field(default_factory=dict)


class CartItemAdd(CartItemBase):
    """Schema for adding an item to the cart."""
    pass


class CartItemResponse(BaseModel):
    """Cart item response with menu item details."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    menu_item_id: str
    quantity: int
    customizations: Dict[str, Any]
    added_at: datetime
    menu_item: Optional[MenuItemResponse] = None

    @property
    def subtotal(self) -> Decimal:
        if self.menu_item:
            return self.menu_item.price * self.quantity
        return Decimal("0.00")


class CartResponse(BaseModel):
    """Full cart for a session."""
    session_id: str
    items: List[CartItemResponse]
    total: Decimal
    item_count: int


# ── Order Schemas ─────────────────────────────────────────────────────────────

class OrderItemBase(BaseModel):
    """Shared order item fields."""
    menu_item_id: str
    quantity: int = Field(1, ge=1)
    unit_price: Decimal
    customizations: Dict[str, Any] = Field(default_factory=dict)


class OrderItemResponse(OrderItemBase):
    """Order item response."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: str
    created_at: datetime
    menu_item: Optional[MenuItemResponse] = None


class OrderCreate(BaseModel):
    """Schema for creating an order."""
    session_id: Optional[str] = None
    notes: Optional[str] = None


class OrderStatusUpdate(BaseModel):
    """Schema for updating order status."""
    status: str = Field(..., pattern="^(pending|confirmed|preparing|ready|delivered|cancelled)$")
    notes: Optional[str] = None


class OrderResponse(BaseModel):
    """Full order response."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: Optional[str]
    status: str
    total_amount: Decimal
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemResponse] = Field(default_factory=list)


class OrderListResponse(BaseModel):
    """Paginated order list response."""
    orders: List[OrderResponse]
    total: int
    page: int
    page_size: int


# ── Session Schemas ───────────────────────────────────────────────────────────

class SessionCreate(BaseModel):
    """Schema for creating a voice session."""
    language: str = "en-IN"
    context: Dict[str, Any] = Field(default_factory=dict)


class SessionResponse(BaseModel):
    """Voice session response."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    is_active: bool
    language: str
    created_at: datetime
    last_active_at: datetime


# ── Recommendation Schemas ────────────────────────────────────────────────────

class RecommendationItem(BaseModel):
    """A single recommendation."""
    menu_item: MenuItemResponse
    score: float = Field(..., ge=0.0, le=1.0)
    reason: str


class RecommendationResponse(BaseModel):
    """List of recommendations for a session."""
    session_id: str
    recommendations: List[RecommendationItem]


# ── Report Schemas ────────────────────────────────────────────────────────────

class ReportRequest(BaseModel):
    """Request to generate an AI report."""
    report_type: str = Field(
        ..., pattern="^(menu_performance|sales_summary|customer_insights|daily_digest)$"
    )
    language: str = "en"
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    extra_context: Optional[str] = None


class ReportResponse(BaseModel):
    """Generated report response."""
    report_type: str
    language: str
    content: str
    generated_at: datetime
    model_used: str


# ── WebSocket Message Schemas ─────────────────────────────────────────────────

class WSMessage(BaseModel):
    """Incoming WebSocket message from client."""
    type: str = Field(
        ...,
        pattern="^(audio_chunk|interrupt|pause|resume|end_of_speech|text_input|ping)$",
    )
    data: Optional[str] = None  # base64 audio for audio_chunk
    text: Optional[str] = None  # optional text payload for text_input


class WSServerMessage(BaseModel):
    """Outgoing WebSocket message from server."""
    type: str
    data: Optional[str] = None
    text: Optional[str] = None
    is_final: Optional[bool] = None
    cart: Optional[CartResponse] = None
    message: Optional[str] = None
    timestamp: Optional[datetime] = None
