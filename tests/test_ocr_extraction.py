"""End-to-end test for OCR + LLM extraction pipeline.

Tests the Typhoon OCR + LLM extraction pipeline on a real invoice image,
verifying that structured fields can be extracted.
"""

import json
import logging
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import typhoon_ocr

logger = logging.getLogger(__name__)

INVOICE_SAMPLE = PROJECT_ROOT / "invoice_sample.jpg"
LLM_API_URL = "https://api.opentyphoon.ai/v1/chat/completions"
LLM_MODEL = "typhoon-v2.5-30b-a3b-instruct"


def _load_api_key() -> str:
    """Load TYHOON_API_KEY from .env file or environment."""
    # Try environment first
    key = os.getenv("TYHOON_API_KEY")
    if key:
        return key
    # Try loading from .env in project root
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("TYHOON_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("TYHOON_API_KEY not found in environment or .env file")


def _call_llm(ocr_text: str, api_key: str) -> dict:
    """Call Typhoon LLM via OpenAI-compatible API to extract invoice fields."""
    prompt = f"""You are an invoice data extraction system. Given the raw OCR text from an invoice image, extract the following structured fields:

- invoice_number (string): Invoice number/id
- vendor_name (string): Name of the vendor/supplier
- invoice_date (string): Date on the invoice (if any)
- total_amount (float): Total amount shown on the invoice (numeric value only, no currency symbols)
- po_reference (string): PO (Purchase Order) reference number if present
- tax_id (string): Tax ID / VAT number if visible

Return ONLY a valid JSON object with those exact keys. If a field is not present in the OCR text, use null.
Do not include any explanation, only the JSON object.

OCR TEXT:
{ocr_text}
"""
    import urllib.request

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 4096,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        LLM_API_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    content = result["choices"][0]["message"]["content"].strip()
    # Try to extract JSON from response (handle markdown code blocks)
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    return json.loads(content)


class TestOCRAndLLMExtraction:
    """Test OCR + LLM extraction pipeline end-to-end."""

    def test_ocr_on_invoice_sample(self):
        """Step 1: Run Typhoon OCR on invoice_sample.jpg and verify text is extracted."""
        if not INVOICE_SAMPLE.exists():
            pytest.skip(f"Invoice sample not found at {INVOICE_SAMPLE}")

        api_key = _load_api_key()

        try:
            ocr_text = typhoon_ocr.ocr_document(
                str(INVOICE_SAMPLE),
                task_type="v1.5",
                api_key=api_key,
            )
        except Exception as e:
            pytest.fail(f"typhoon_ocr.ocr_document raised an exception: {e}")

        print("\n" + "=" * 60)
        print("OCR RESULT (first 1000 chars)")
        print("=" * 60)
        print(ocr_text[:1000])
        if len(ocr_text) > 1000:
            print(f"... [+{len(ocr_text) - 1000} more characters]")
        print("=" * 60)

        assert ocr_text is not None, "OCR returned None"
        assert len(ocr_text) > 10, f"OCR text too short: {ocr_text!r}"
        logger.info("OCR raw text:\n%s", ocr_text)

    def test_llm_structured_extraction(self):
        """Step 2: Pass OCR text to LLM for structured extraction and verify fields."""
        if not INVOICE_SAMPLE.exists():
            pytest.skip(f"Invoice sample not found at {INVOICE_SAMPLE}")

        api_key = _load_api_key()

        # Run OCR first
        ocr_text = typhoon_ocr.ocr_document(
            str(INVOICE_SAMPLE),
            task_type="v1.5",
            api_key=api_key,
        )

        assert ocr_text and len(ocr_text) > 10, "OCR step must succeed before LLM test"

        # Call LLM
        try:
            extracted = _call_llm(ocr_text, api_key)
        except Exception as e:
            pytest.fail(f"LLM extraction raised an exception: {e}")

        print("\n" + "=" * 60)
        print("LLM EXTRACTED FIELDS")
        print("=" * 60)
        print(json.dumps(extracted, indent=2, ensure_ascii=False))
        print("=" * 60)

        assert isinstance(extracted, dict), f"LLM returned non-dict: {type(extracted)}"

        # Verify non-empty plausible fields
        # At minimum, we expect some field to be non-null since the invoice is real
        non_null_fields = [k for k, v in extracted.items() if v is not None]
        assert len(non_null_fields) >= 1, (
            f"Expected at least 1 non-null field, got {extracted}. "
            "LLM may have failed to parse the OCR output."
        )

        # If total_amount was extracted, verify it's a plausible number
        if extracted.get("total_amount") is not None:
            try:
                amount = float(extracted["total_amount"])
                assert amount >= 0, f"total_amount should be non-negative, got {amount}"
                print(f"  total_amount = {amount} ✓")
            except (ValueError, TypeError):
                pytest.fail(f"total_amount is not a valid number: {extracted['total_amount']!r}")

        # If po_reference was extracted, verify it's a non-empty string
        if extracted.get("po_reference") is not None:
            assert isinstance(extracted["po_reference"], str), (
                f"po_reference should be string, got {type(extracted['po_reference'])}"
            )
            assert len(extracted["po_reference"]) > 0, "po_reference should not be empty"
            print(f"  po_reference = {extracted['po_reference']} ✓")

        logger.info("Extracted invoice fields: %s", extracted)

    def test_full_pipeline_ocr_then_llm(self):
        """Full end-to-end: OCR -> LLM -> verify extracted fields are non-empty and plausible."""
        if not INVOICE_SAMPLE.exists():
            pytest.skip(f"Invoice sample not found at {INVOICE_SAMPLE}")

        api_key = _load_api_key()

        # Step 1: OCR
        try:
            ocr_text = typhoon_ocr.ocr_document(
                str(INVOICE_SAMPLE),
                task_type="v1.5",
                api_key=api_key,
            )
        except Exception as e:
            pytest.fail(f"OCR step failed: {e}")

        assert ocr_text and len(ocr_text) > 10, "OCR produced insufficient text"

        # Step 2: LLM extraction
        try:
            extracted = _call_llm(ocr_text, api_key)
        except Exception as e:
            pytest.fail(f"LLM extraction step failed: {e}")

        print("\n" + "=" * 60)
        print("FULL PIPELINE — EXTRACTED FIELDS")
        print("=" * 60)
        print(json.dumps(extracted, indent=2, ensure_ascii=False))
        print("=" * 60)

        # Assertions: fields are non-empty and plausible
        assert isinstance(extracted, dict), "LLM must return a dict"

        non_null_count = sum(1 for v in extracted.values() if v is not None)
        assert non_null_count >= 1, f"Expected at least 1 field extracted, got none: {extracted}"

        # Validate total_amount if present
        if extracted.get("total_amount") is not None:
            try:
                amount = float(extracted["total_amount"])
                assert amount >= 0, f"Amount must be non-negative, got {amount}"
            except (ValueError, TypeError):
                pytest.fail(f"total_amount is not a valid float: {extracted['total_amount']!r}")

        # Validate invoice_number if present
        if extracted.get("invoice_number") is not None:
            assert isinstance(extracted["invoice_number"], str)
            assert len(extracted["invoice_number"]) > 0

        logger.info("Full pipeline extraction successful: %s", extracted)


if __name__ == "__main__":
    print("Running OCR + LLM Extraction Pipeline Test...")
    print(f"Invoice sample: {INVOICE_SAMPLE}")
    pytest.main([__file__, "-v", "-s"])
