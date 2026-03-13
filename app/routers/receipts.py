from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import uuid, aiofiles, os
from pathlib import Path

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.config import settings
from app.models.user import User, Receipt, ReceiptItem, ShoppingItem
from app.schemas import ReceiptOut, ReceiptStatusOut, ConfirmReceiptRequest, MarkAllBoughtRequest

router = APIRouter(prefix="/receipts", tags=["receipts"])

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
MAX_FILE_MB = 10


# ─── Upload ───────────────────────────────────────────────────

@router.post("/upload", response_model=ReceiptOut, status_code=201)
async def upload_receipt(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, f"Unsupported file type: {file.content_type}")

    content = await file.read()
    if len(content) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {MAX_FILE_MB}MB)")

    # Save file
    receipt_id = str(uuid.uuid4())
    file_url = await _save_file(receipt_id, content, file.content_type)

    # Create receipt record
    receipt = Receipt(
        id=receipt_id,
        user_id=user.id,
        file_url=file_url,
        status="uploaded",
        currency=user.currency,
    )
    db.add(receipt)
    await db.commit()

    # Kick off OCR in background
    from app.workers.tasks import process_receipt_task
    process_receipt_task.delay(receipt_id, user.id)

    await db.refresh(receipt)
    return receipt


# ─── List ─────────────────────────────────────────────────────

@router.get("", response_model=List[ReceiptOut])
async def get_receipts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Receipt)
        .where(Receipt.user_id == user.id)
        .order_by(Receipt.created_at.desc())
        .limit(50)
    )
    return result.scalars().all()


# ─── Status (for polling) ─────────────────────────────────────

@router.get("/{receipt_id}/status", response_model=ReceiptStatusOut)
async def get_status(
    receipt_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    receipt = await _get_receipt_or_404(db, receipt_id, user.id)

    items_count = len(receipt.items)
    matched_count = sum(1 for i in receipt.items if i.matched_item_id)

    return ReceiptStatusOut(
        id=receipt.id,
        status=receipt.status,
        confidence=receipt.confidence,
        store_raw=receipt.store_raw,
        total=receipt.total,
        items_count=items_count,
        matched_count=matched_count,
    )


# ─── Confirm matches ──────────────────────────────────────────

@router.post("/{receipt_id}/confirm", status_code=200)
async def confirm_receipt(
    receipt_id: str,
    body: ConfirmReceiptRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark selected receipt items as confirmed → update shopping list items to 'bought'."""
    receipt = await _get_receipt_or_404(db, receipt_id, user.id)

    # Find matched shopping list items
    result = await db.execute(
        select(ReceiptItem).where(
            ReceiptItem.receipt_id == receipt_id,
            ReceiptItem.matched_item_id.in_(body.matched_item_ids),
        )
    )
    receipt_items = result.scalars().all()

    # Update shopping list items
    shopping_item_ids = [ri.matched_item_id for ri in receipt_items if ri.matched_item_id]
    if shopping_item_ids:
        result = await db.execute(
            select(ShoppingItem).where(ShoppingItem.id.in_(shopping_item_ids))
        )
        shopping_items = result.scalars().all()
        for item in shopping_items:
            item.status = "bought"

        # Record price points for future forecasting
        for ri in receipt_items:
            if ri.unit_price and ri.matched_item_id:
                from app.models.user import PricePoint
                pp = PricePoint(
                    id=str(uuid.uuid4()),
                    name_normalized=ri.normalized_name or ri.name_raw.lower().strip(),
                    store_raw=receipt.store_raw,
                    price=ri.unit_price,
                    currency=receipt.currency,
                )
                db.add(pp)

    receipt.status = "confirmed"
    await db.commit()

    return {"confirmed_count": len(shopping_item_ids)}


@router.post("/{receipt_id}/mark-all-bought", status_code=200)
async def mark_all_bought(
    receipt_id: str,
    body: MarkAllBoughtRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark all items in a list as bought — triggered after receipt confirmed."""
    await _get_receipt_or_404(db, receipt_id, user.id)

    result = await db.execute(
        select(ShoppingItem).where(
            ShoppingItem.list_id == body.list_id,
            ShoppingItem.status.in_(["planned", "in_cart"]),
        )
    )
    items = result.scalars().all()
    for item in items:
        item.status = "bought"

    await db.commit()
    return {"marked_count": len(items)}


@router.delete("/{receipt_id}", status_code=204)
async def delete_receipt(
    receipt_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    receipt = await _get_receipt_or_404(db, receipt_id, user.id)
    await db.delete(receipt)


# ─── Helpers ──────────────────────────────────────────────────

async def _get_receipt_or_404(db: AsyncSession, receipt_id: str, user_id: str) -> Receipt:
    result = await db.execute(
        select(Receipt).where(Receipt.id == receipt_id, Receipt.user_id == user_id)
    )
    receipt = result.scalar_one_or_none()
    if not receipt:
        raise HTTPException(404, "Receipt not found")
    return receipt


async def _save_file(receipt_id: str, content: bytes, content_type: str) -> str:
    if settings.USE_LOCAL_STORAGE:
        path = Path(settings.LOCAL_STORAGE_PATH) / "receipts"
        path.mkdir(parents=True, exist_ok=True)
        ext = "pdf" if content_type == "application/pdf" else "jpg"
        file_path = path / f"{receipt_id}.{ext}"
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(content)
        return str(file_path)
    else:
        # Upload to S3
        import boto3
        from app.core.config import settings as s
        s3 = boto3.client("s3", region_name=s.S3_REGION)
        key = f"receipts/{receipt_id}"
        s3.put_object(Bucket=s.S3_BUCKET, Key=key, Body=content, ContentType=content_type)
        return f"https://{s.S3_BUCKET}.s3.{s.S3_REGION}.amazonaws.com/{key}"
