"""
WebSocket — реалтайм синхронизация семейных списков.

Протокол:
  client → server:  {"type": "join", "list_id": "...", "token": "..."}
  client → server:  {"type": "item_status", "item_id": "...", "status": "bought"}
  client → server:  {"type": "item_add", "name": "...", "qty": 1}
  client → server:  {"type": "typing", "item_name": "..."}
  client → server:  {"type": "ping"}

  server → client:  {"type": "joined", "list_id": "...", "members": [...]}
  server → client:  {"type": "item_updated", "item": {...}, "by": "Маша"}
  server → client:  {"type": "item_added", "item": {...}, "by": "Маша"}
  server → client:  {"type": "member_joined", "name": "Кирилл", "is_online": true}
  server → client:  {"type": "member_left", "name": "Кирилл"}
  server → client:  {"type": "typing", "name": "Маша", "item_name": "молоко"}
  server → client:  {"type": "pong"}
  server → client:  {"type": "error", "message": "..."}
"""

import asyncio
import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect


# ─── Connection ───────────────────────────────────────────────

class Connection:
    def __init__(self, ws: WebSocket, user_id: str, user_name: str, list_id: str):
        self.id = str(uuid.uuid4())
        self.ws = ws
        self.user_id = user_id
        self.user_name = user_name
        self.list_id = list_id
        self.connected_at = datetime.now(timezone.utc)

    async def send(self, data: dict):
        try:
            await self.ws.send_text(json.dumps(data, default=str))
        except Exception:
            pass  # Connection might already be closed


# ─── Manager ──────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        # list_id → [Connection]
        self._rooms: dict[str, list[Connection]] = defaultdict(list)
        # connection_id → Connection
        self._connections: dict[str, Connection] = {}
        # list_id → {user_id: last_activity}
        self._activity: dict[str, dict[str, datetime]] = defaultdict(dict)

    # ── Connect / Disconnect ──────────────────────────────────

    async def connect(self, conn: Connection):
        self._rooms[conn.list_id].append(conn)
        self._connections[conn.id] = conn
        self._activity[conn.list_id][conn.user_id] = datetime.now(timezone.utc)

        # Notify others in room
        await self._broadcast_to_room(conn.list_id, {
            "type": "member_joined",
            "name": conn.user_name,
            "user_id": conn.user_id,
            "is_online": True,
            "ts": datetime.now(timezone.utc).isoformat(),
        }, exclude=conn.id)

        # Send room state to new member
        members = self._get_room_members(conn.list_id)
        await conn.send({
            "type": "joined",
            "list_id": conn.list_id,
            "members": members,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

    async def disconnect(self, conn: Connection):
        self._rooms[conn.list_id] = [
            c for c in self._rooms[conn.list_id] if c.id != conn.id
        ]
        self._connections.pop(conn.id, None)
        self._activity[conn.list_id].pop(conn.user_id, None)

        # Clean up empty rooms
        if not self._rooms[conn.list_id]:
            del self._rooms[conn.list_id]

        # Notify others
        await self._broadcast_to_room(conn.list_id, {
            "type": "member_left",
            "name": conn.user_name,
            "user_id": conn.user_id,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

    # ── Broadcasting ──────────────────────────────────────────

    async def broadcast_item_updated(self, list_id: str, item: dict, by_name: str, exclude_id: Optional[str] = None):
        await self._broadcast_to_room(list_id, {
            "type": "item_updated",
            "item": item,
            "by": by_name,
            "ts": datetime.now(timezone.utc).isoformat(),
        }, exclude=exclude_id)

    async def broadcast_item_added(self, list_id: str, item: dict, by_name: str, exclude_id: Optional[str] = None):
        await self._broadcast_to_room(list_id, {
            "type": "item_added",
            "item": item,
            "by": by_name,
            "ts": datetime.now(timezone.utc).isoformat(),
        }, exclude=exclude_id)

    async def broadcast_item_deleted(self, list_id: str, item_id: str, by_name: str):
        await self._broadcast_to_room(list_id, {
            "type": "item_deleted",
            "item_id": item_id,
            "by": by_name,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

    async def broadcast_typing(self, list_id: str, user_name: str, item_name: str, exclude_id: str):
        await self._broadcast_to_room(list_id, {
            "type": "typing",
            "name": user_name,
            "item_name": item_name,
            "ts": datetime.now(timezone.utc).isoformat(),
        }, exclude=exclude_id)

    # ── Internal ──────────────────────────────────────────────

    async def _broadcast_to_room(self, list_id: str, data: dict, exclude: Optional[str] = None):
        conns = self._rooms.get(list_id, [])
        dead = []
        for conn in conns:
            if conn.id == exclude:
                continue
            try:
                await conn.send(data)
            except Exception:
                dead.append(conn)
        # Clean up dead connections
        for conn in dead:
            await self.disconnect(conn)

    def _get_room_members(self, list_id: str) -> list[dict]:
        seen_users = set()
        members = []
        for conn in self._rooms.get(list_id, []):
            if conn.user_id not in seen_users:
                seen_users.add(conn.user_id)
                members.append({
                    "user_id": conn.user_id,
                    "name": conn.user_name,
                    "is_online": True,
                })
        return members

    def get_online_users(self, list_id: str) -> list[str]:
        return list({c.user_id for c in self._rooms.get(list_id, [])})

    def room_size(self, list_id: str) -> int:
        return len(self._rooms.get(list_id, []))


# ─── Singleton ────────────────────────────────────────────────

manager = ConnectionManager()
