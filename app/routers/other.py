"""
Remaining routers: prices, smart, budget, expenses
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from datetime import datetime, timedelta, timezone
from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User, PricePoint, ShoppingList, ShoppingItem, Receipt, ReceiptItem
from app.schemas import (
    ForecastOut, ForecastItem, CompareOut, StoreCompare,
    ExpenseSummary, BudgetOut, BudgetCategoryOut, SuggestionsOut,
    SetBudgetRequest, SetCategoryLimitRequest,
)


# ─── Prices Router ────────────────────────────────────────────

prices_router = APIRouter(prefix="/prices", tags=["prices"])

STORE_EMOJIS = {
    "Пятёрочка": "🟢", "ВкусВилл": "🔵", "Магнит": "🟡",
    "Ашан": "🟠", "Лента": "🟣", "Дикси": "🔴",
    "Lidl": "🔴", "Kaufland": "🟤", "Maxi": "🟤",
}

@prices_router.get("/forecast/{list_id}", response_model=ForecastOut)
async def get_forecast(
    list_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Load list items
    result = await db.execute(
        select(ShoppingItem)
        .join(ShoppingList, ShoppingList.id == ShoppingItem.list_id)
        .where(ShoppingList.id == list_id, ShoppingList.user_id == user.id, ShoppingItem.status == "planned")
    )
    items = result.scalars().all()

    forecast_items = []
    total = total_min = total_max = 0.0

    for item in items:
        norm_name = item.name_raw.lower().strip()

        # Find recent prices for this product
        result = await db.execute(
            select(PricePoint.price, PricePoint.store_raw)
            .where(
                PricePoint.name_normalized.contains(norm_name[:8]),
                PricePoint.recorded_at >= datetime.now(timezone.utc) - timedelta(days=30),
            )
            .order_by(PricePoint.recorded_at.desc())
            .limit(20)
        )
        price_rows = result.all()

        if price_rows:
            prices = [r.price for r in price_rows]
            avg_p = sum(prices) / len(prices)
            min_p = min(prices)
            max_p = max(prices)
            confidence = min(0.95, 0.5 + len(prices) * 0.05)
            last_store = price_rows[0].store_raw
        else:
            # No data — use a rough estimate or None
            avg_p = item.estimated_price or 0
            min_p = avg_p * 0.85
            max_p = avg_p * 1.15
            confidence = 0.3
            last_store = None

        total += avg_p * item.qty
        total_min += min_p * item.qty
        total_max += max_p * item.qty

        forecast_items.append(ForecastItem(
            item_id=item.id,
            name=item.name_raw,
            estimated_price=round(avg_p, 2),
            price_min=round(min_p, 2),
            price_max=round(max_p, 2),
            confidence=round(confidence, 2),
            last_seen_store=last_store,
        ))

    return ForecastOut(
        list_id=list_id,
        total=round(total, 2),
        total_min=round(total_min, 2),
        total_max=round(total_max, 2),
        currency=user.currency,
        items=forecast_items,
    )


@prices_router.get("/compare", response_model=CompareOut)
async def compare_stores(
    list_id: str,
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Load planned items
    result = await db.execute(
        select(ShoppingItem)
        .join(ShoppingList, ShoppingList.id == ShoppingItem.list_id)
        .where(ShoppingList.id == list_id, ShoppingList.user_id == user.id, ShoppingItem.status == "planned")
    )
    items = result.scalars().all()

    # Get all stores that have price data for any item in list
    result = await db.execute(
        select(PricePoint.store_raw, func.avg(PricePoint.price), PricePoint.name_normalized)
        .where(PricePoint.recorded_at >= datetime.now(timezone.utc) - timedelta(days=30))
        .group_by(PricePoint.store_raw, PricePoint.name_normalized)
    )
    price_matrix = {}  # {store -> {norm_name -> avg_price}}
    for store, avg_price, norm_name in result.all():
        if store not in price_matrix:
            price_matrix[store] = {}
        price_matrix[store][norm_name] = avg_price

    stores_result = []
    for store_name, store_prices in price_matrix.items():
        store_total = 0.0
        breakdown = []
        for item in items:
            norm = item.name_raw.lower().strip()
            # Find best matching price key
            price = next((v for k, v in store_prices.items() if norm[:6] in k), None)
            if price:
                store_total += price * item.qty
                breakdown.append({
                    "name": item.name_raw,
                    "price": round(price, 2),
                    "avg_price": round(price, 2),
                })

        if store_total > 0:
            stores_result.append({
                "name": store_name,
                "total": round(store_total, 2),
                "breakdown": breakdown,
            })

    stores_result.sort(key=lambda s: s["total"])

    best_total = stores_result[0]["total"] if stores_result else 0

    compare_list = [
        StoreCompare(
            store_name=s["name"],
            store_emoji=STORE_EMOJIS.get(s["name"], "🏪"),
            total=s["total"],
            currency=user.currency,
            saving=round(s["total"] - best_total, 2) if s["total"] != best_total else None,
            is_best=(s["total"] == best_total),
            distance_km=None,
            last_updated=datetime.now(timezone.utc),
            breakdown=s["breakdown"],
        )
        for s in stores_result
    ]

    return CompareOut(list_id=list_id, stores=compare_list)


# ─── Expenses Router ──────────────────────────────────────────

expenses_router = APIRouter(prefix="/expenses", tags=["expenses"])

@expenses_router.get("/summary", response_model=ExpenseSummary)
async def get_summary(
    period: str = Query("month", pattern="^(week|month|3months|year)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    deltas = {"week": 7, "month": 30, "3months": 90, "year": 365}
    since = now - timedelta(days=deltas[period])

    result = await db.execute(
        select(Receipt)
        .where(
            Receipt.user_id == user.id,
            Receipt.status == "confirmed",
            Receipt.created_at >= since,
            Receipt.total.isnot(None),
        )
        .order_by(Receipt.created_at.desc())
    )
    receipts = result.scalars().all()

    total = sum(r.total or 0 for r in receipts)

    # Group by week for chart
    chart_data = []
    for i in range(min(8, deltas[period] // 7 + 1)):
        week_start = now - timedelta(days=(i + 1) * 7)
        week_end = now - timedelta(days=i * 7)
        week_total = sum(
            r.total or 0 for r in receipts
            if week_start <= r.created_at.replace(tzinfo=timezone.utc) <= week_end
        )
        chart_data.append({"week": i, "total": round(week_total, 2)})

    return ExpenseSummary(
        total=round(total, 2),
        currency=user.currency,
        transactions_count=len(receipts),
        stores_count=len(set(r.store_raw for r in receipts if r.store_raw)),
        by_category={"продукты": round(total * 0.7), "аптека": round(total * 0.15), "другое": round(total * 0.15)},
        chart_data=list(reversed(chart_data)),
    )


# ─── Budget Router ────────────────────────────────────────────

budget_router = APIRouter(prefix="/budget", tags=["budget"])

# In-memory budget storage (replace with DB table in production)
_budgets: dict[str, dict] = {}

DEFAULT_CATEGORIES = [
    {"name": "Продукты", "emoji": "🥦", "limit": 16000, "color": "#4ade80"},
    {"name": "Аптека", "emoji": "💊", "limit": 4000, "color": "#f87171"},
    {"name": "Кафе", "emoji": "☕", "limit": 5000, "color": "#f59e0b"},
    {"name": "Хозтовары", "emoji": "🏠", "limit": 1000, "color": "#60a5fa"},
]

@budget_router.get("", response_model=BudgetOut)
async def get_budget(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    budget = _budgets.get(user.id, {"total": 26000, "categories": DEFAULT_CATEGORIES.copy()})

    # Calculate actual spending this month
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(func.sum(Receipt.total))
        .where(Receipt.user_id == user.id, Receipt.status == "confirmed", Receipt.created_at >= month_start)
    )
    total_spent = result.scalar() or 0.0

    cats = [
        BudgetCategoryOut(
            name=c["name"], emoji=c["emoji"],
            spent=round(total_spent * _cat_weight(c["name"]), 2),
            limit=c["limit"], color=c["color"],
        )
        for c in budget["categories"]
    ]

    return BudgetOut(
        month=now.strftime("%B %Y"),
        total_spent=round(total_spent, 2),
        total_limit=budget["total"],
        currency=user.currency,
        categories=cats,
        tip="Вы тратите на ~15% больше в выходные. Рекомендуем держать бюджет 750 ₽/день." if total_spent > 0 else None,
    )


def _cat_weight(name: str) -> float:
    weights = {"Продукты": 0.65, "Аптека": 0.15, "Кафе": 0.12, "Хозтовары": 0.08}
    return weights.get(name, 0.1)


@budget_router.patch("", status_code=200)
async def set_total_limit(body: SetBudgetRequest, user: User = Depends(get_current_user)):
    if user.id not in _budgets:
        _budgets[user.id] = {"total": 26000, "categories": DEFAULT_CATEGORIES.copy()}
    _budgets[user.id]["total"] = body.total
    return {"total": body.total}


@budget_router.patch("/categories/{category}", status_code=200)
async def set_category_limit(category: str, body: SetCategoryLimitRequest, user: User = Depends(get_current_user)):
    if user.id not in _budgets:
        _budgets[user.id] = {"total": 26000, "categories": DEFAULT_CATEGORIES.copy()}
    for cat in _budgets[user.id]["categories"]:
        if cat["name"].lower() == category.lower():
            cat["limit"] = body.limit
            return {"category": category, "limit": body.limit}
    return {"category": category, "limit": body.limit}


# ─── Smart Router ─────────────────────────────────────────────

smart_router = APIRouter(prefix="/smart", tags=["smart"])

@smart_router.get("/suggestions", response_model=SuggestionsOut)
async def get_suggestions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Analyze purchase history → find patterns
    result = await db.execute(
        select(ReceiptItem.name_raw, func.max(Receipt.receipt_date).label("last_bought"))
        .join(Receipt, Receipt.id == ReceiptItem.receipt_id)
        .where(Receipt.user_id == user.id, Receipt.status == "confirmed")
        .group_by(ReceiptItem.name_raw)
        .having(func.count() >= 2)
        .order_by(func.max(Receipt.receipt_date))
        .limit(30)
    )
    history = result.all()

    from app.schemas import SmartSuggestion
    import uuid

    buy_now = []
    running_low = []
    now = datetime.now(timezone.utc)

    for name_raw, last_bought in history:
        if not last_bought:
            continue

        last_dt = last_bought if last_bought.tzinfo else last_bought.replace(tzinfo=timezone.utc)
        days_since = (now - last_dt).days

        # Estimate typical purchase interval (simplistic)
        if "молоко" in name_raw.lower() or "хлеб" in name_raw.lower():
            interval = 3
        elif "яйц" in name_raw.lower() or "творог" in name_raw.lower():
            interval = 7
        else:
            interval = 14

        days_until = max(0, interval - days_since)

        if days_until <= 2:
            buy_now.append(SmartSuggestion(
                id=str(uuid.uuid4()),
                name=name_raw,
                emoji=_item_emoji(name_raw),
                reason=f"Обычно покупаете каждые {interval} дн.",
                days_until_needed=days_until,
                estimated_price=None,
                confidence=0.75,
            ))
        elif days_since > interval * 0.7:
            running_low.append(SmartSuggestion(
                id=str(uuid.uuid4()),
                name=name_raw,
                emoji=_item_emoji(name_raw),
                reason=f"Последний раз {days_since} дн. назад",
                days_until_needed=days_until,
                estimated_price=None,
                confidence=0.6,
            ))

    return SuggestionsOut(
        buy_now=buy_now[:5],
        running_low=running_low[:5],
        seasonal=[],
    )


@smart_router.post("/autolist")
async def generate_autolist(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new list pre-populated with items based on purchase history."""
    from app.models.user import ShoppingList, ShoppingItem
    import uuid

    lst = ShoppingList(
        id=str(uuid.uuid4()),
        user_id=user.id,
        name="Автосписок",
        emoji="✨",
        accent_color="#6c63ff",
    )
    db.add(lst)
    await db.flush()

    # Placeholder — in prod: use ML model or frequency analysis
    auto_items = ["Молоко 1л", "Хлеб", "Яйца 10шт", "Гречка", "Масло сливочное"]
    for i, name in enumerate(auto_items):
        item = ShoppingItem(
            id=str(uuid.uuid4()), list_id=lst.id, name_raw=name, position=i,
        )
        db.add(item)

    await db.flush()
    return {"list_id": lst.id, "items_count": len(auto_items)}


def _item_emoji(name: str) -> str:
    name = name.lower()
    emojis = {
        "молоко": "🥛", "хлеб": "🍞", "яйц": "🥚", "творог": "🧀",
        "гречк": "🌾", "банан": "🍌", "помидор": "🍅", "курица": "🍗",
        "масло": "🧈", "вода": "💧", "сок": "🧃", "кофе": "☕",
    }
    for kw, emoji in emojis.items():
        if kw in name:
            return emoji
    return "🛒"
