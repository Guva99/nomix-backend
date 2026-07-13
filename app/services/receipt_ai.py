from __future__ import annotations

import io
import json
import logging
import re
from typing import Any

from PIL import Image
from google import genai
from google.genai import types

from app.core.settings import settings
from app.services.receipt_prompt import RECEIPT_JSON_SCHEMA, RECEIPT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set")
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def _prepare_jpeg(image_bytes: bytes) -> bytes:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=90, optimize=True)
    return buf.getvalue()


def _strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def normalize_receipt_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize model quirks to the API contract."""
    if "is_receipt" not in data and "isreceipt" in data:
        data["is_receipt"] = data.pop("isreceipt")

    if not data.get("is_receipt"):
        return {
            "is_receipt": False,
            "reason": data.get("reason") or "На изображении нет признаков товарного чека",
        }

    items = data.get("items") or []
    normalized_items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        price = item.get("price", 0)
        if isinstance(price, str):
            price = float(price.strip().replace(",", ".").replace(" ", ""))
        normalized_items.append({
            "name": (item.get("name") or "—").strip(),
            "price": round(float(price), 2),
            "category": item.get("category") or "Прочее",
            "category_id": int(item.get("category_id") or 5),
            "subcategory": item.get("subcategory") or "",
            "subcategory_id": int(item.get("subcategory_id") or 0),
        })

    total = data.get("total", 0)
    if isinstance(total, str):
        total = float(total.strip().replace(",", ".").replace(" ", ""))

    result: dict[str, Any] = {
        "is_receipt": True,
        "store": (data.get("store") or "Магазин").strip(),
        "date": data.get("date") or "",
        "time": data.get("time") or "",
        "total": round(float(total), 2),
        "currency": data.get("currency") or "RUB",
        "items": normalized_items,
    }
    return result


def parse_receipt_response(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        return normalize_receipt_payload(raw)

    cleaned = _strip_json_fence(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model response is not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Model response must be a JSON object")

    return normalize_receipt_payload(parsed)


async def analyze_receipt_from_bytes(image_bytes: bytes) -> dict[str, Any]:
    """Analyze receipt image with Gemini and return normalized dict."""
    jpeg_bytes = _prepare_jpeg(image_bytes)
    client = _get_client()

    config = types.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=8192,
        response_mime_type="application/json",
        response_schema=RECEIPT_JSON_SCHEMA,
        system_instruction=RECEIPT_SYSTEM_PROMPT,
    )

    try:
        response = await client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg"),
                types.Part.from_text(
                    text="Проанализируй изображение чека и верни JSON строго по схеме."
                ),
            ],
            config=config,
        )
    except Exception:
        logger.exception("Gemini API request failed")
        raise

    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Empty response from Gemini")

    logger.debug("Gemini raw response length=%s", len(text))
    return parse_receipt_response(text)
