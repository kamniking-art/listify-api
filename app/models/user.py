import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, Float, Integer, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)

def new_uuid():
    return str(uuid.uuid4())


# ─── User ─────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(10), default="RU")
    currency: Mapped[str] = mapped_column(String(10), default="RUB")
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=False)
    device_id: Mapped[str | None] = mapped_column(String(255), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    lists: Mapped[list["ShoppingList"]] = relationship("ShoppingList", back_populates="user", cascade="all, delete-orphan")
    receipts: Mapped[list["Receipt"]] = relationship("Receipt", back_populates="user", cascade="all, delete-orphan")


# ─── Shopping List ────────────────────────────────────────────

class ShoppingList(Base):
    __tablename__ = "shopping_lists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    emoji: Mapped[str] = mapped_column(String(10), default="🛒")
    accent_color: Mapped[str] = mapped_column(String(20), default="#6c63ff")
    budget: Mapped[float | None] = mapped_column(Float)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    store_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship("User", back_populates="lists")
    items: Mapped[list["ShoppingItem"]] = relationship(
        "ShoppingItem", back_populates="list",
        cascade="all, delete-orphan",
        order_by="ShoppingItem.position"
    )


# ─── Shopping Item ────────────────────────────────────────────

class ShoppingItem(Base):
    __tablename__ = "shopping_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    list_id: Mapped[str] = mapped_column(String(36), ForeignKey("shopping_lists.id", ondelete="CASCADE"), index=True)
    name_raw: Mapped[str] = mapped_column(String(255))
    product_id: Mapped[str | None] = mapped_column(String(36), index=True)
    qty: Mapped[float] = mapped_column(Float, default=1.0)
    unit: Mapped[str | None] = mapped_column(String(30))
    category: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(
        SAEnum("planned", "in_cart", "bought", "not_found", name="item_status"),
        default="planned"
    )
    note: Mapped[str | None] = mapped_column(Text)
    estimated_price: Mapped[float | None] = mapped_column(Float)
    position: Mapped[int] = mapped_column(Integer, default=0)
    added_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    list: Mapped["ShoppingList"] = relationship("ShoppingList", back_populates="items")


# ─── Receipt ──────────────────────────────────────────────────

class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    file_url: Mapped[str] = mapped_column(String(500))
    store_id: Mapped[str | None] = mapped_column(String(36))
    store_raw: Mapped[str | None] = mapped_column(String(200))
    receipt_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(10), default="RUB")
    status: Mapped[str] = mapped_column(
        SAEnum("uploaded", "processing", "parsed", "matched", "confirmed", "error", name="receipt_status"),
        default="uploaded"
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship("User", back_populates="receipts")
    items: Mapped[list["ReceiptItem"]] = relationship("ReceiptItem", back_populates="receipt", cascade="all, delete-orphan")


# ─── Receipt Item ─────────────────────────────────────────────

class ReceiptItem(Base):
    __tablename__ = "receipt_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    receipt_id: Mapped[str] = mapped_column(String(36), ForeignKey("receipts.id", ondelete="CASCADE"), index=True)
    name_raw: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str | None] = mapped_column(String(255))
    qty: Mapped[float | None] = mapped_column(Float)
    unit_price: Mapped[float | None] = mapped_column(Float)
    line_total: Mapped[float | None] = mapped_column(Float)
    matched_item_id: Mapped[str | None] = mapped_column(String(36))
    match_confidence: Mapped[float | None] = mapped_column(Float)

    receipt: Mapped["Receipt"] = relationship("Receipt", back_populates="items")


# ─── Price Point ──────────────────────────────────────────────

class PricePoint(Base):
    __tablename__ = "price_points"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    product_id: Mapped[str | None] = mapped_column(String(36), index=True)
    name_normalized: Mapped[str] = mapped_column(String(255), index=True)
    store_id: Mapped[str | None] = mapped_column(String(36), index=True)
    store_raw: Mapped[str | None] = mapped_column(String(200))
    price: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(10), default="RUB")
    country: Mapped[str] = mapped_column(String(10), default="RU")
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
