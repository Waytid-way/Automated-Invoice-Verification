"""
LLM-based invoice data extraction using Typhoon LLM.
"""
import json
import re
from typing import Optional

from openai import OpenAI

from mock_data import API_RATE_LIMIT_DELAY
from utils.agent import ExtractedInvoice
from utils.prompts import INVOICE_EXTRACTION_PROMPT, INVOICE_EXTRACTION_STRICT_PROMPT


def _clean_json_response(text: str) -> str:
    """Strip markdown code fences and normalize escaped/quoted JSON from LLM response."""
    text = re.sub(r"```json", "", text)
    text = re.sub(r"```", "", text)
    text = text.strip()
    # Handle responses wrapped in an extra JSON string literal: "{\"key\": ...}"
    if text.startswith('"') and text.endswith('"'):
        try:
            text = json.loads(text)  # unescape the outer string
        except Exception:
            pass
    # Handle JSON with literal \n escape at the start
    if text.startswith('\\n'):
        text = text[2:]
    if text.startswith('\n'):
        text = text[1:]
    return text.strip()


def _validate_extraction(raw: dict) -> bool:
    """
    Validate that required fields are present and well-formed.
    Returns True if valid, False otherwise.
    """
    required_keys = ["invoice_number", "po_reference", "total_amount"]
    for key in required_keys:
        if key not in raw:
            return False

    tax_id = raw.get("tax_id")
    if tax_id and (not isinstance(tax_id, str) or len(tax_id) != 13 or not tax_id.isdigit()):
        return False

    total = raw.get("total_amount", 0)
    if not isinstance(total, (int, float)) or total < 0:
        return False

    items = raw.get("items")
    if items is not None and not isinstance(items, list):
        return False

    return True


def _safe_float(value) -> float:
    try:
        if isinstance(value, str):
            value = value.replace(",", "").strip()
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def extract_invoice_data(
    ocr_text: str,
    mode: str = "API (Typhoon Cloud)",
    *,
    api_key: Optional[str] = None,
) -> ExtractedInvoice:
    """
    Extract structured invoice data from OCR text using Typhoon LLM.

    Steps:
      1. Insert OCR text into extraction prompt template
      2. Call Typhoon LLM API (or Ollama fallback)
      3. Parse JSON, validate fields
      4. Retry once with strict prompt on parse failure
      5. Return ExtractedInvoice dataclass
    """
    if mode == "LOCAL (Ollama)":
        base_url = "http://localhost:11434/v1"
        model = "scb10x/typhoon2.5-qwen3-4b"
        key = "ollama"
    else:
        base_url = "https://api.opentyphoon.ai/v1"
        model = "typhoon-v2.5-30b-a3b-instruct"
        key = api_key or ""

    client = OpenAI(api_key=key, base_url=base_url)

    prompt = INVOICE_EXTRACTION_PROMPT.format(invoice_text=ocr_text)

    def _call_llm(prompt: str) -> dict:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=4096,
        )
        raw_text = response.choices[0].message.content
        return json.loads(_clean_json_response(raw_text))

    def _call_strict(text: str) -> dict:
        response = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": INVOICE_EXTRACTION_STRICT_PROMPT.format(invoice_text=text),
            }],
            temperature=0,
            max_tokens=4096,
        )
        raw_text = response.choices[0].message.content
        return json.loads(_clean_json_response(raw_text))

    # First attempt
    raw = None
    try:
        raw = _call_llm(prompt)
    except (json.JSONDecodeError, Exception) as e:
        # Retry once with stricter prompt
        try:
            raw = _call_strict(ocr_text)
        except Exception:
            raw = None

    if raw is None:
        return ExtractedInvoice(
            invoice_number="",
            invoice_date="",
            po_ref=None,
            vendor_name=None,
            tax_id=None,
            items=[],
            subtotal=0.0,
            vat_amount=0.0,
            total_amount=0.0,
            confidence=0.0,
        )

    # Normalize po_reference key name
    if "po_reference" not in raw and "po_ref" in raw:
        raw["po_reference"] = raw.pop("po_ref")

    if not _validate_extraction(raw):
        return ExtractedInvoice.from_dict(raw)

    # Normalize amounts
    raw["subtotal"] = _safe_float(raw.get("subtotal"))
    raw["vat_amount"] = _safe_float(raw.get("vat_amount"))
    raw["total_amount"] = _safe_float(raw.get("total_amount"))
    raw["confidence"] = float(raw.get("confidence") or 0)

    return ExtractedInvoice.from_dict(raw)
