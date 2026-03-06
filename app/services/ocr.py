"""
OCR Service
Pipeline: image → preprocess → extract text → parse structure → match items
"""
import re
import io
import uuid
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional
from PIL import Image, ImageFilter, ImageEnhance
from rapidfuzz import fuzz, process as rfuzz_process

# ─── Image Preprocessing ──────────────────────────────────────

def preprocess_image(image_bytes: bytes) -> bytes:
    """
    Enhance receipt image for better OCR accuracy.
    Converts to grayscale, boosts contrast, sharpens.
    """
    img = Image.open(io.BytesIO(image_bytes))

    # Convert to RGB if needed
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Resize if too small (OCR works best at 300+ DPI equivalent)
    width, height = img.size
    if width < 1000:
        scale = 1000 / width
        img = img.resize((int(width * scale), int(height * scale)), Image.LANCZOS)

    # Grayscale
    img = img.convert("L")

    # Boost contrast
    img = ImageEnhance.Contrast(img).enhance(2.0)

    # Sharpen
    img = img.filter(ImageFilter.SHARPEN)

    output = io.BytesIO()
    img.save(output, format="PNG")
    return output.getvalue()


# ─── OCR Backends ─────────────────────────────────────────────

async def extract_text_tesseract(image_bytes: bytes, lang: str = "rus+eng") -> tuple[str, float]:
    """Tesseract OCR — local, free, works offline."""
    import pytesseract
    img = Image.open(io.BytesIO(image_bytes))
    config = "--oem 3 --psm 6"
    data = pytesseract.image_to_data(img, lang=lang, config=config, output_type=pytesseract.Output.DICT)

    text = pytesseract.image_to_string(img, lang=lang, config=config)
    confidences = [int(c) for c in data["conf"] if c != "-1" and int(c) > 0]
    avg_conf = sum(confidences) / len(confidences) / 100 if confidences else 0.0

    return text, avg_conf


async def extract_text_google_vision(image_bytes: bytes) -> tuple[str, float]:
    """Google Cloud Vision — higher accuracy, costs money."""
    import httpx
    import base64
    from app.core.config import settings

    b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "requests": [{
            "image": {"content": b64},
            "features": [{"type": "TEXT_DETECTION"}],
            "imageContext": {"languageHints": ["ru", "en"]},
        }]
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"https://vision.googleapis.com/v1/images:annotate?key={settings.GOOGLE_VISION_API_KEY}",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    annotations = data["responses"][0].get("textAnnotations", [])
    if not annotations:
        return "", 0.0

    full_text = annotations[0]["description"]
    # Google Vision doesn't return confidence per-word directly — estimate from response
    confidence = 0.90  # Vision is generally high quality
    return full_text, confidence


async def extract_text(image_bytes: bytes) -> tuple[str, float]:
    """Pick backend based on config."""
    from app.core.config import settings
    preprocessed = preprocess_image(image_bytes)
    if settings.USE_GOOGLE_VISION and settings.GOOGLE_VISION_API_KEY:
        return await extract_text_google_vision(preprocessed)
    return await extract_text_tesseract(preprocessed)


# ─── Receipt Parser ───────────────────────────────────────────

STORE_PATTERNS = {
    "Пятёрочка": [r"пятёрочк", r"пятерочк", r"pyaterochka"],
    "ВкусВилл": [r"вкусвилл", r"vkusvill"],
    "Магнит":    [r"магнит", r"magnit"],
    "Ашан":      [r"ашан", r"auchan"],
    "Лента":     [r"лента", r"lenta"],
    "Дикси":     [r"дикси", r"dixy"],
    "Lidl":      [r"lidl"],
    "Kaufland":  [r"kaufland"],
    "Maxi":      [r"maxi"],
}

DATE_PATTERNS = [
    r"\d{2}[./-]\d{2}[./-]\d{4}",
    r"\d{2}[./-]\d{2}[./-]\d{2}",
    r"\d{4}[./-]\d{2}[./-]\d{2}",
]

TOTAL_PATTERNS = [
    r"итого[:\s]+(\d+[.,]\d{2})",
    r"итого[:\s]+(\d+)",
    r"сумма[:\s]+(\d+[.,]\d{2})",
    r"total[:\s]+(\d+[.,]\d{2})",
    r"к оплате[:\s]+(\d+[.,]\d{2})",
]

ITEM_LINE_PATTERN = re.compile(
    r"^(.{3,40}?)\s+"            # name (3-40 chars)
    r"(\d+(?:[.,]\d+)?)\s*"      # qty
    r"(?:кг|шт|л|г|мл|уп)?\s*"  # unit (optional)
    r"[*x×]\s*"                   # multiplication sign
    r"(\d+(?:[.,]\d{2})?)\s*"    # unit price
    r"=?\s*"
    r"(\d+(?:[.,]\d{2})?)$",     # line total
    re.IGNORECASE | re.MULTILINE,
)

SIMPLE_ITEM_PATTERN = re.compile(
    r"^(.{3,50}?)\s{2,}(\d+[.,]\d{2})\s*$",
    re.MULTILINE,
)


def _parse_float(s: str) -> float:
    return float(s.replace(",", "."))


class ParsedReceipt:
    def __init__(self):
        self.store: Optional[str] = None
        self.date: Optional[datetime] = None
        self.total: Optional[float] = None
        self.items: list[dict] = []
        self.confidence: float = 0.0


def parse_receipt_text(text: str) -> ParsedReceipt:
    result = ParsedReceipt()
    text_lower = text.lower()

    # ── Store detection ──
    for store_name, patterns in STORE_PATTERNS.items():
        if any(re.search(p, text_lower) for p in patterns):
            result.store = store_name
            break

    # ── Date detection ──
    for pattern in DATE_PATTERNS:
        match = re.search(pattern, text)
        if match:
            raw = match.group()
            for fmt in ["%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y", "%Y-%m-%d"]:
                try:
                    result.date = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    continue
            if result.date:
                break

    # ── Total detection ──
    for pattern in TOTAL_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            try:
                result.total = _parse_float(match.group(1))
                break
            except (ValueError, IndexError):
                continue

    # ── Item extraction — try detailed pattern first ──
    items = []
    for m in ITEM_LINE_PATTERN.finditer(text):
        try:
            items.append({
                "name_raw": m.group(1).strip(),
                "qty": _parse_float(m.group(2)),
                "unit_price": _parse_float(m.group(3)),
                "line_total": _parse_float(m.group(4)),
            })
        except ValueError:
            continue

    # ── Fallback: simple pattern (name + price) ──
    if not items:
        for m in SIMPLE_ITEM_PATTERN.finditer(text):
            name = m.group(1).strip()
            if any(skip in name.lower() for skip in ["итого", "сумма", "скидка", "карт", "наличн", "сдача"]):
                continue
            try:
                items.append({
                    "name_raw": name,
                    "qty": 1.0,
                    "unit_price": _parse_float(m.group(2)),
                    "line_total": _parse_float(m.group(2)),
                })
            except ValueError:
                continue

    result.items = items
    return result


# ─── Item Matching ────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """Lowercase, remove qty/unit suffixes, strip extra spaces."""
    name = name.lower().strip()
    name = re.sub(r"\s*\d+\s*(г|кг|мл|л|шт|уп|пак)\b", "", name)
    name = re.sub(r"\s+", " ", name)
    return name


def match_items_to_list(
    receipt_items: list[dict],
    list_items: list[dict],   # [{"id": ..., "name_raw": ...}]
    threshold: float = 70.0,
) -> list[dict]:
    """
    Fuzzy-match receipt items to shopping list items.
    Returns receipt_items with matched_item_id and match_confidence.
    """
    if not list_items:
        return receipt_items

    list_names = {item["id"]: normalize_name(item["name_raw"]) for item in list_items}

    result = []
    for ri in receipt_items:
        norm = normalize_name(ri["name_raw"])
        best_id = None
        best_score = 0.0

        for item_id, list_name in list_names.items():
            score = max(
                fuzz.ratio(norm, list_name),
                fuzz.partial_ratio(norm, list_name),
                fuzz.token_sort_ratio(norm, list_name),
            )
            if score > best_score:
                best_score = score
                best_id = item_id

        matched = best_score >= threshold
        result.append({
            **ri,
            "matched_item_id": best_id if matched else None,
            "match_confidence": round(best_score / 100, 3),
        })

    return result


# ─── Full Pipeline ────────────────────────────────────────────

async def process_receipt(
    image_bytes: bytes,
    list_items: list[dict],
) -> dict:
    """
    Full pipeline:
    1. Extract text via OCR
    2. Parse structure (store, date, total, items)
    3. Match items to shopping list
    Returns dict ready to store in DB.
    """
    raw_text, ocr_confidence = await extract_text(image_bytes)
    parsed = parse_receipt_text(raw_text)
    matched = match_items_to_list(parsed.items, list_items)

    match_confidences = [i["match_confidence"] for i in matched if i.get("matched_item_id")]
    avg_match = sum(match_confidences) / len(match_confidences) if match_confidences else 0.0
    overall_confidence = round((ocr_confidence + avg_match) / 2, 3)

    return {
        "store_raw": parsed.store,
        "receipt_date": parsed.date,
        "total": parsed.total,
        "confidence": overall_confidence,
        "items": matched,
        "raw_text": raw_text,
    }
