from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import datetime, timezone
import uuid

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User
from app.models.push import PushToken

router = APIRouter(prefix="/users", tags=["users"])


class PushTokenRequest(BaseModel):
    token: str
    platform: str = "ios"


@router.post("/push-token", status_code=204)
async def register_push_token(
    body: PushTokenRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Save or update push token for current user's device."""
    # Check if token already exists
    result = await db.execute(select(PushToken).where(PushToken.token == body.token))
    existing = result.scalar_one_or_none()

    if existing:
        # Re-activate and update ownership if needed
        existing.user_id = user.id
        existing.is_active = True
        existing.last_used_at = datetime.now(timezone.utc)
    else:
        pt = PushToken(
            id=str(uuid.uuid4()),
            user_id=user.id,
            token=body.token,
            platform=body.platform,
        )
        db.add(pt)

    await db.flush()


@router.delete("/push-token", status_code=204)
async def unregister_push_token(
    body: PushTokenRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Deactivate push token (e.g. on logout)."""
    result = await db.execute(
        select(PushToken).where(PushToken.token == body.token, PushToken.user_id == user.id)
    )
    pt = result.scalar_one_or_none()
    if pt:
        pt.is_active = False
        await db.flush()
