"""
Celery tasks — background jobs.
Run worker: celery -A app.workers.tasks worker --loglevel=info
"""
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "listify",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_time_limit=120,        # max 2 min per task
    task_soft_time_limit=90,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)


# ─── OCR Task ─────────────────────────────────────────────────

@celery_app.task(
    name="process_receipt",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def process_receipt_task(self, receipt_id: str, user_id: str):
    """
    1. Load receipt image from storage
    2. Run OCR pipeline
    3. Store parsed items in DB
    4. Update receipt status
    """
    import asyncio
    asyncio.run(_process_receipt_async(receipt_id, user_id))


async def _process_receipt_async(receipt_id: str, user_id: str):
    import aiofiles
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.user import Receipt, ReceiptItem, ShoppingList, ShoppingItem
    from app.services.ocr import process_receipt
    import uuid

    async with AsyncSessionLocal() as db:
        # Load receipt
        result = await db.execute(select(Receipt).where(Receipt.id == receipt_id))
        receipt = result.scalar_one_or_none()
        if not receipt:
            return

        try:
            # Update status → processing
            receipt.status = "processing"
            await db.commit()

            # Load image
            async with aiofiles.open(receipt.file_url, "rb") as f:
                image_bytes = await f.read()

            # Load user's active shopping list items for matching
            result = await db.execute(
                select(ShoppingItem)
                .join(ShoppingList, ShoppingList.id == ShoppingItem.list_id)
                .where(
                    ShoppingList.user_id == user_id,
                    ShoppingList.is_archived == False,
                    ShoppingItem.status.in_(["planned", "in_cart"]),
                )
            )
            list_items = [
                {"id": item.id, "name_raw": item.name_raw}
                for item in result.scalars().all()
            ]

            # Run OCR pipeline
            parsed = await process_receipt(image_bytes, list_items)

            # Update status → parsed
            receipt.status = "parsed"
            receipt.store_raw = parsed["store_raw"]
            receipt.receipt_date = parsed["receipt_date"]
            receipt.total = parsed["total"]
            receipt.confidence = parsed["confidence"]
            await db.commit()

            # Save receipt items
            for item_data in parsed["items"]:
                ri = ReceiptItem(
                    id=str(uuid.uuid4()),
                    receipt_id=receipt_id,
                    name_raw=item_data["name_raw"],
                    normalized_name=item_data["name_raw"].lower().strip(),
                    qty=item_data.get("qty"),
                    unit_price=item_data.get("unit_price"),
                    line_total=item_data.get("line_total"),
                    matched_item_id=item_data.get("matched_item_id"),
                    match_confidence=item_data.get("match_confidence"),
                )
                db.add(ri)

            # Final status
            receipt.status = "matched"
            await db.commit()

        except Exception as e:
            receipt.status = "error"
            receipt.error_message = str(e)
            await db.commit()
            raise


# ─── Weekly Stats Task (scheduled) ───────────────────────────

@celery_app.task(name="compute_weekly_stats")
def compute_weekly_stats():
    """Runs every Sunday night — precomputes expense summaries."""
    import asyncio
    asyncio.run(_compute_stats_async())


async def _compute_stats_async():
    # TODO: aggregate expenses, update materialized views
    pass


# ─── Price Trend Task (scheduled) ────────────────────────────

@celery_app.task(name="update_price_trends")
def update_price_trends():
    """Runs daily — computes average prices per product per store."""
    import asyncio
    asyncio.run(_update_prices_async())


async def _update_prices_async():
    from sqlalchemy import text, func, select
    from app.core.database import AsyncSessionLocal
    from app.models.user import PricePoint

    async with AsyncSessionLocal() as db:
        # For each product name, compute 30-day average per store
        result = await db.execute(
            select(
                PricePoint.name_normalized,
                PricePoint.store_raw,
                func.avg(PricePoint.price).label("avg_price"),
                func.count().label("count"),
            )
            .group_by(PricePoint.name_normalized, PricePoint.store_raw)
            .having(func.count() >= 2)
        )
        rows = result.all()
        # TODO: store in price_averages table for fast forecast queries


# ─── Beat Schedule (cron) ─────────────────────────────────────

from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    "weekly-stats": {
        "task": "compute_weekly_stats",
        "schedule": crontab(hour=1, minute=0, day_of_week=0),  # Sunday 01:00
    },
    "daily-price-trends": {
        "task": "update_price_trends",
        "schedule": crontab(hour=3, minute=0),                  # Every day 03:00
    },
}
