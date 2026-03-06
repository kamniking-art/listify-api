import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db, AsyncSessionLocal
from app.core.auth import decode_token
from app.models.user import User, ShoppingList, ShoppingItem
from app.services.ws_manager import manager, Connection
from app.routers.lists import _guess_category
import uuid

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/lists/{list_id}")
async def ws_list(list_id: str, websocket: WebSocket):
    """
    WebSocket endpoint for real-time list collaboration.

    Client must send {"type": "join", "token": "<access_token>"} first.
    After that, all item changes are broadcast to all members in the room.
    """
    await websocket.accept()
    conn: Connection | None = None

    try:
        # ── Auth handshake ────────────────────────────────────
        raw = await websocket.receive_text()
        msg = json.loads(raw)

        if msg.get("type") != "join" or not msg.get("token"):
            await websocket.send_text(json.dumps({"type": "error", "message": "Send {type:join, token:...} first"}))
            await websocket.close(4001)
            return

        # Verify token
        try:
            payload = decode_token(msg["token"])
        except Exception:
            await websocket.send_text(json.dumps({"type": "error", "message": "Invalid token"}))
            await websocket.close(4001)
            return

        user_id = payload["sub"]

        async with AsyncSessionLocal() as db:
            # Load user
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                await websocket.send_text(json.dumps({"type": "error", "message": "User not found"}))
                await websocket.close(4001)
                return

            # Verify user has access to this list
            result = await db.execute(
                select(ShoppingList).where(
                    ShoppingList.id == list_id,
                    ShoppingList.user_id == user_id,  # TODO: also check shared lists
                )
            )
            lst = result.scalar_one_or_none()
            if not lst:
                await websocket.send_text(json.dumps({"type": "error", "message": "List not found or access denied"}))
                await websocket.close(4003)
                return

        user_name = user.name or "Аноним"
        conn = Connection(websocket, user_id, user_name, list_id)
        await manager.connect(conn)

        # ── Message loop ──────────────────────────────────────
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await conn.send({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = msg.get("type")

            # ── Ping / Pong ───────────────────────────────────
            if msg_type == "ping":
                await conn.send({"type": "pong"})

            # ── Item status update ────────────────────────────
            elif msg_type == "item_status":
                item_id = msg.get("item_id")
                status = msg.get("status")
                if not item_id or status not in ("planned", "in_cart", "bought", "not_found"):
                    await conn.send({"type": "error", "message": "item_id and valid status required"})
                    continue

                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(ShoppingItem).where(
                            ShoppingItem.id == item_id,
                            ShoppingItem.list_id == list_id,
                        )
                    )
                    item = result.scalar_one_or_none()
                    if item:
                        item.status = status
                        await db.commit()
                        await db.refresh(item)
                        item_dict = _item_to_dict(item)

                        # Broadcast to ALL including sender (so sender gets server-confirmed state)
                        await manager.broadcast_item_updated(list_id, item_dict, user_name)

            # ── Add item ──────────────────────────────────────
            elif msg_type == "item_add":
                name = (msg.get("name") or "").strip()
                if not name:
                    await conn.send({"type": "error", "message": "name required"})
                    continue

                async with AsyncSessionLocal() as db:
                    new_item = ShoppingItem(
                        id=str(uuid.uuid4()),
                        list_id=list_id,
                        name_raw=name,
                        qty=msg.get("qty", 1),
                        unit=msg.get("unit"),
                        category=_guess_category(name),
                        added_by=user_name,
                        position=9999,
                    )
                    db.add(new_item)
                    await db.commit()
                    await db.refresh(new_item)
                    item_dict = _item_to_dict(new_item)

                await manager.broadcast_item_added(list_id, item_dict, user_name, exclude_id=conn.id)
                # Confirm to sender
                await conn.send({"type": "item_added", "item": item_dict, "by": "you"})

            # ── Delete item ───────────────────────────────────
            elif msg_type == "item_delete":
                item_id = msg.get("item_id")
                if not item_id:
                    continue
                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(ShoppingItem).where(ShoppingItem.id == item_id, ShoppingItem.list_id == list_id)
                    )
                    item = result.scalar_one_or_none()
                    if item:
                        await db.delete(item)
                        await db.commit()
                        await manager.broadcast_item_deleted(list_id, item_id, user_name)

            # ── Typing indicator ──────────────────────────────
            elif msg_type == "typing":
                item_name = msg.get("item_name", "")
                await manager.broadcast_typing(list_id, user_name, item_name, exclude_id=conn.id)

            else:
                await conn.send({"type": "error", "message": f"Unknown message type: {msg_type}"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass
    finally:
        if conn:
            await manager.disconnect(conn)


# ─── REST endpoint: online members ────────────────────────────

from fastapi import Depends
from app.core.auth import get_current_user

members_router = APIRouter(prefix="/lists", tags=["websocket"])

@members_router.get("/{list_id}/online")
async def get_online_members(
    list_id: str,
    user: User = Depends(get_current_user),
):
    """Returns list of user_ids currently connected to this list's room."""
    return {
        "list_id": list_id,
        "online_count": manager.room_size(list_id),
        "online_users": manager.get_online_users(list_id),
    }


# ─── Helpers ──────────────────────────────────────────────────

def _item_to_dict(item: ShoppingItem) -> dict:
    return {
        "id": item.id,
        "list_id": item.list_id,
        "name_raw": item.name_raw,
        "qty": item.qty,
        "unit": item.unit,
        "category": item.category,
        "status": item.status,
        "note": item.note,
        "estimated_price": item.estimated_price,
        "position": item.position,
        "added_by": item.added_by,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }
