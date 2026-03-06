"""
Push notification service — шлёт уведомления через Expo Push API.
Expo бесплатно доставляет в APNs (iOS) и FCM (Android).

Документация: https://docs.expo.dev/push-notifications/sending-notifications/
"""
import httpx
import asyncio
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.push import PushToken   # модель ниже


EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_PUSH_RECEIPT_URL = "https://exp.host/--/api/v2/push/getReceipts"
CHUNK_SIZE = 100  # Expo принимает до 100 уведомлений за раз


# ─── Message builder ──────────────────────────────────────────

def _msg(
    to: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
    sound: str | None = "default",
    badge: Optional[int] = None,
    channel_id: str = "default",
) -> dict:
    return {
        "to": to,
        "title": title,
        "body": body,
        "data": data or {},
        "sound": sound,
        "badge": badge,
        "channelId": channel_id,
        "_contentAvailable": True,
    }


# ─── Core sender ──────────────────────────────────────────────

async def send_push(messages: list[dict]) -> list[dict]:
    """
    Send push notifications via Expo Push API.
    Returns list of ticket objects (one per message).
    """
    if not messages:
        return []

    tickets = []
    # Send in chunks of 100
    for i in range(0, len(messages), CHUNK_SIZE):
        chunk = messages[i:i + CHUNK_SIZE]
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                EXPO_PUSH_URL,
                json=chunk,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Accept-Encoding": "gzip, deflate",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            tickets.extend(data.get("data", []))

    return tickets


async def send_to_user(
    db: AsyncSession,
    user_id: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
    sound: str | None = "default",
    channel_id: str = "default",
) -> None:
    """Send notification to all devices of a user."""
    tokens = await _get_user_tokens(db, user_id)
    if not tokens:
        return
    messages = [_msg(t, title, body, data, sound, channel_id=channel_id) for t in tokens]
    try:
        await send_push(messages)
    except Exception as e:
        print(f"[Push] Failed to send to user {user_id}: {e}")


async def send_to_list_members(
    db: AsyncSession,
    list_id: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
    exclude_user_id: Optional[str] = None,
    channel_id: str = "family",
) -> None:
    """Send notification to all members of a shared list (except sender)."""
    from app.models.user import ShoppingList
    result = await db.execute(select(ShoppingList).where(ShoppingList.id == list_id))
    lst = result.scalar_one_or_none()
    if not lst:
        return

    # TODO: when sharing is implemented, get all member user_ids
    # For now — just the owner
    member_ids = [lst.user_id]
    if exclude_user_id:
        member_ids = [uid for uid in member_ids if uid != exclude_user_id]

    tasks = [
        send_to_user(db, uid, title, body, data, channel_id=channel_id)
        for uid in member_ids
    ]
    await asyncio.gather(*tasks, return_exceptions=True)


# ─── Specific notification types ──────────────────────────────

async def notify_item_added(
    db: AsyncSession,
    list_id: str,
    item_name: str,
    list_name: str,
    by_user_name: str,
    exclude_user_id: str,
) -> None:
    await send_to_list_members(
        db, list_id,
        title=f"{list_name} 🛒",
        body=f"{by_user_name} добавил(а) {item_name}",
        data={"type": "item_added", "list_id": list_id},
        exclude_user_id=exclude_user_id,
        channel_id="family",
    )


async def notify_item_bought(
    db: AsyncSession,
    list_id: str,
    item_name: str,
    list_name: str,
    by_user_name: str,
    exclude_user_id: str,
) -> None:
    await send_to_list_members(
        db, list_id,
        title=f"{list_name} ✅",
        body=f"{by_user_name} купил(а) {item_name}",
        data={"type": "item_bought", "list_id": list_id},
        exclude_user_id=exclude_user_id,
        channel_id="family",
        sound=None,  # тихое — за каждый товар не звонить
    )


async def notify_receipt_ready(
    db: AsyncSession,
    user_id: str,
    store_name: str,
    item_count: int,
    total: Optional[float],
) -> None:
    total_str = f" · {int(total):,} ₽".replace(",", " ") if total else ""
    await send_to_user(
        db, user_id,
        title="Чек обработан 📄",
        body=f"{store_name} · {item_count} поз.{total_str}",
        data={"type": "receipt_ready"},
        channel_id="default",
    )


async def notify_budget_warning(
    db: AsyncSession,
    user_id: str,
    spent: float,
    limit: float,
    currency: str,
) -> None:
    pct = round((spent / limit) * 100)
    await send_to_user(
        db, user_id,
        title=f"Бюджет использован на {pct}% ⚠️",
        body=f"Потрачено {int(spent):,} из {int(limit):,} {currency}".replace(",", " "),
        data={"type": "budget_warning"},
        channel_id="default",
    )


async def notify_buy_reminder(
    db: AsyncSession,
    user_id: str,
    item_name: str,
    days_until: int,
) -> None:
    when = "сегодня" if days_until == 0 else "завтра" if days_until == 1 else f"через {days_until} дн."
    await send_to_user(
        db, user_id,
        title="Пора в магазин 🛍",
        body=f"{item_name} заканчивается {when}",
        data={"type": "reminder", "item": item_name},
        channel_id="reminders",
    )


# ─── Token helpers ────────────────────────────────────────────

async def _get_user_tokens(db: AsyncSession, user_id: str) -> list[str]:
    result = await db.execute(
        select(PushToken.token).where(PushToken.user_id == user_id, PushToken.is_active == True)
    )
    return [row[0] for row in result.all()]
