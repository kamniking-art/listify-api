from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime


# ─── Auth ─────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = Field(min_length=1, max_length=100)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class AnonymousLoginRequest(BaseModel):
    device_id: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: "UserOut"

class UserOut(BaseModel):
    id: str
    email: Optional[str]
    name: Optional[str]
    country: str
    currency: str
    is_anonymous: bool
    created_at: datetime
    model_config = {"from_attributes": True}


# ─── Items ────────────────────────────────────────────────────

class ItemOut(BaseModel):
    id: str
    list_id: str
    name_raw: str
    product_id: Optional[str]
    qty: float
    unit: Optional[str]
    category: Optional[str]
    status: str
    note: Optional[str]
    estimated_price: Optional[float]
    position: int
    added_by: Optional[str]
    created_at: datetime
    model_config = {"from_attributes": True}

class AddItemRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    qty: float = 1.0
    unit: Optional[str] = None
    category: Optional[str] = None
    note: Optional[str] = None

class UpdateItemRequest(BaseModel):
    name: Optional[str] = None
    qty: Optional[float] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    note: Optional[str] = None
    estimated_price: Optional[float] = None
    position: Optional[int] = None

class UpdateItemStatusRequest(BaseModel):
    status: str = Field(pattern="^(planned|in_cart|bought|not_found)$")

class BatchStatusRequest(BaseModel):
    item_ids: List[str]
    status: str = Field(pattern="^(planned|in_cart|bought|not_found)$")

class ReorderRequest(BaseModel):
    item_ids: List[str]


# ─── Lists ────────────────────────────────────────────────────

class ListOut(BaseModel):
    id: str
    user_id: str
    name: str
    emoji: str
    accent_color: str
    budget: Optional[float]
    is_shared: bool
    is_archived: bool
    items: List[ItemOut] = []
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class CreateListRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    emoji: str = "🛒"
    accent_color: str = "#6c63ff"
    budget: Optional[float] = None

class UpdateListRequest(BaseModel):
    name: Optional[str] = None
    emoji: Optional[str] = None
    accent_color: Optional[str] = None
    budget: Optional[float] = None
    is_archived: Optional[bool] = None

class ShareListRequest(BaseModel):
    emails: List[EmailStr]


# ─── Receipts ─────────────────────────────────────────────────

class ReceiptItemOut(BaseModel):
    id: str
    receipt_id: str
    name_raw: str
    normalized_name: Optional[str]
    qty: Optional[float]
    unit_price: Optional[float]
    line_total: Optional[float]
    matched_item_id: Optional[str]
    match_confidence: Optional[float]
    model_config = {"from_attributes": True}

class ReceiptOut(BaseModel):
    id: str
    user_id: str
    file_url: str
    store_raw: Optional[str]
    receipt_date: Optional[datetime]
    total: Optional[float]
    currency: str
    status: str
    confidence: Optional[float]
    items: List[ReceiptItemOut] = []
    created_at: datetime
    model_config = {"from_attributes": True}

class ReceiptStatusOut(BaseModel):
    id: str
    status: str
    confidence: Optional[float]
    store_raw: Optional[str]
    total: Optional[float]
    items_count: int
    matched_count: int

class ConfirmReceiptRequest(BaseModel):
    matched_item_ids: List[str]

class MarkAllBoughtRequest(BaseModel):
    list_id: str


# ─── Expenses ─────────────────────────────────────────────────

class ExpenseSummary(BaseModel):
    total: float
    currency: str
    transactions_count: int
    stores_count: int
    by_category: dict
    chart_data: List[dict]

class ExpenseTransaction(BaseModel):
    id: str
    store_name: str
    total: float
    currency: str
    category: str
    item_count: int
    date: datetime


# ─── Prices ───────────────────────────────────────────────────

class ForecastItem(BaseModel):
    item_id: str
    name: str
    estimated_price: float
    price_min: float
    price_max: float
    confidence: float
    last_seen_store: Optional[str]

class ForecastOut(BaseModel):
    list_id: str
    total: float
    total_min: float
    total_max: float
    currency: str
    items: List[ForecastItem]

class StoreCompare(BaseModel):
    store_id: Optional[str]
    store_name: str
    store_emoji: str
    total: float
    currency: str
    saving: Optional[float]
    is_best: bool
    distance_km: Optional[float]
    last_updated: Optional[datetime]
    breakdown: List[dict]

class CompareOut(BaseModel):
    list_id: str
    stores: List[StoreCompare]


# ─── Budget ───────────────────────────────────────────────────

class BudgetCategoryOut(BaseModel):
    name: str
    emoji: str
    spent: float
    limit: float
    color: str

class BudgetOut(BaseModel):
    month: str
    total_spent: float
    total_limit: float
    currency: str
    categories: List[BudgetCategoryOut]
    tip: Optional[str]

class SetBudgetRequest(BaseModel):
    total: float = Field(gt=0)

class SetCategoryLimitRequest(BaseModel):
    limit: float = Field(gt=0)


# ─── Smart ────────────────────────────────────────────────────

class SmartSuggestion(BaseModel):
    id: str
    name: str
    emoji: str
    reason: str
    days_until_needed: Optional[int]
    estimated_price: Optional[float]
    confidence: float

class SuggestionsOut(BaseModel):
    buy_now: List[SmartSuggestion]
    running_low: List[SmartSuggestion]
    seasonal: List[SmartSuggestion]
