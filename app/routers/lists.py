from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User, ShoppingList, ShoppingItem
from app.schemas import (
    ListOut, CreateListRequest, UpdateListRequest,
    ItemOut, AddItemRequest, UpdateItemRequest,
    UpdateItemStatusRequest, BatchStatusRequest, ReorderRequest,
)
import uuid

router = APIRouter(prefix="/lists", tags=["lists"])


def _new_id():
    return str(uuid.uuid4())


# ─── Lists CRUD ───────────────────────────────────────────────

@router.get("", response_model=List[ListOut])
async def get_lists(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ShoppingList)
        .where(ShoppingList.user_id == user.id, ShoppingList.is_archived == False)
        .order_by(ShoppingList.updated_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=ListOut, status_code=201)
async def create_list(
    body: CreateListRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    lst = ShoppingList(
        id=_new_id(),
        user_id=user.id,
        name=body.name,
        emoji=body.emoji,
        accent_color=body.accent_color,
        budget=body.budget,
    )
    db.add(lst)
    await db.commit()
    await db.refresh(lst)
    return lst


@router.get("/{list_id}", response_model=ListOut)
async def get_list(
    list_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    lst = await _get_list_or_404(db, list_id, user.id)
    return lst


@router.patch("/{list_id}", response_model=ListOut)
async def update_list(
    list_id: str,
    body: UpdateListRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    lst = await _get_list_or_404(db, list_id, user.id)

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(lst, field, value)

    await db.commit()
    await db.refresh(lst)
    return lst


@router.delete("/{list_id}", status_code=204)
async def delete_list(
    list_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    lst = await _get_list_or_404(db, list_id, user.id)
    await db.delete(lst)


# ─── Items ────────────────────────────────────────────────────

@router.get("/{list_id}/items", response_model=List[ItemOut])
async def get_items(
    list_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_list_or_404(db, list_id, user.id)
    result = await db.execute(
        select(ShoppingItem)
        .where(ShoppingItem.list_id == list_id)
        .order_by(ShoppingItem.position, ShoppingItem.created_at)
    )
    return result.scalars().all()


@router.post("/{list_id}/items", response_model=ItemOut, status_code=201)
async def add_item(
    list_id: str,
    body: AddItemRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_list_or_404(db, list_id, user.id)

    # Auto-detect category if not provided
    category = body.category or _guess_category(body.name)

    # Get current max position
    result = await db.execute(
        select(ShoppingItem.position)
        .where(ShoppingItem.list_id == list_id)
        .order_by(ShoppingItem.position.desc())
        .limit(1)
    )
    max_pos = result.scalar() or 0

    item = ShoppingItem(
        id=_new_id(),
        list_id=list_id,
        name_raw=body.name,
        qty=body.qty,
        unit=body.unit,
        category=category,
        note=body.note,
        position=max_pos + 1,
        added_by=user.name,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.patch("/{list_id}/items/{item_id}", response_model=ItemOut)
async def update_item(
    list_id: str,
    item_id: str,
    body: UpdateItemRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_list_or_404(db, list_id, user.id)
    item = await _get_item_or_404(db, item_id, list_id)

    data = body.model_dump(exclude_none=True)
    if "name" in data:
        item.name_raw = data.pop("name")
    for field, value in data.items():
        setattr(item, field, value)

    await db.commit()
    await db.refresh(item)
    return item


@router.patch("/{list_id}/items/{item_id}/status", response_model=ItemOut)
async def update_item_status(
    list_id: str,
    item_id: str,
    body: UpdateItemStatusRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_list_or_404(db, list_id, user.id)
    item = await _get_item_or_404(db, item_id, list_id)
    item.status = body.status
    await db.commit()
    await db.refresh(item)
    return item


@router.post("/{list_id}/items/batch-status", response_model=List[ItemOut])
async def batch_update_status(
    list_id: str,
    body: BatchStatusRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_list_or_404(db, list_id, user.id)
    result = await db.execute(
        select(ShoppingItem).where(
            ShoppingItem.list_id == list_id,
            ShoppingItem.id.in_(body.item_ids),
        )
    )
    items = result.scalars().all()
    for item in items:
        item.status = body.status
    await db.commit()
    return items


@router.post("/{list_id}/items/reorder", status_code=204)
async def reorder_items(
    list_id: str,
    body: ReorderRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_list_or_404(db, list_id, user.id)
    for pos, item_id in enumerate(body.item_ids):
        result = await db.execute(
            select(ShoppingItem).where(ShoppingItem.id == item_id, ShoppingItem.list_id == list_id)
        )
        item = result.scalar_one_or_none()
        if item:
            item.position = pos


@router.delete("/{list_id}/items/{item_id}", status_code=204)
async def delete_item(
    list_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_list_or_404(db, list_id, user.id)
    item = await _get_item_or_404(db, item_id, list_id)
    await db.delete(item)


# ─── Helpers ──────────────────────────────────────────────────

async def _get_list_or_404(db: AsyncSession, list_id: str, user_id: str) -> ShoppingList:
    result = await db.execute(
        select(ShoppingList).where(ShoppingList.id == list_id, ShoppingList.user_id == user_id)
    )
    lst = result.scalar_one_or_none()
    if not lst:
        raise HTTPException(404, "List not found")
    return lst


async def _get_item_or_404(db: AsyncSession, item_id: str, list_id: str) -> ShoppingItem:
    result = await db.execute(
        select(ShoppingItem).where(ShoppingItem.id == item_id, ShoppingItem.list_id == list_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item not found")
    return item


# ─── Category auto-detection ──────────────────────────────────

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "молочное":  ["молоко", "кефир", "творог", "сметана", "йогурт", "сыр", "масло сливочное"],
    "мясо":      ["курица", "говядина", "свинина", "фарш", "колбаса", "сосиски"],
    "овощи":     ["помидор", "огурец", "картофель", "морковь", "лук", "капуста", "перец"],
    "фрукты":    ["яблоко", "банан", "апельсин", "мандарин", "груша", "виноград"],
    "крупы":     ["гречка", "рис", "овсянка", "манка", "пшено", "перловка"],
    "хлеб":      ["хлеб", "батон", "булка", "лаваш", "тост"],
    "напитки":   ["вода", "сок", "чай", "кофе", "газировка", "компот"],
    "масла":     ["масло растительное", "масло оливковое", "масло подсолнечное"],
    "консервы":  ["тушёнка", "рыбные консервы", "фасоль", "горошек"],
    "заморозка": ["пельмени", "вареники", "блины", "пицца замороженная"],
    "аптека":    ["аспирин", "парацетамол", "витамин", "таблетки", "мазь"],
    "бытовая химия": ["стиральный порошок", "гель", "шампунь", "мыло", "зубная"],
    "хозтовары": ["пакеты", "фольга", "бумага", "губка", "мешки"],
}


def _guess_category(name: str) -> str:
    name_lower = name.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in name_lower for kw in keywords):
            return category
    return "другое"
