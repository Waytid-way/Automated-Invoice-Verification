#!/usr/bin/env python3
"""
Direct test of Typhoon OCR + LLM extraction on invoice_sample.jpg.
Uses: typhoon_ocr.ocr_document(task_type='v1.5') and typhoon-v2.5-30b-a3b-instruct.
"""
import os
import sys
import json
import time
from pathlib import Path

# Load .env
ENV_PATH = Path(__file__).parent / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().strip().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

# ── 1. OCR ───────────────────────────────────────────────────────────────────
print("=" * 60)
print("STEP 1: Typhoon OCR (task_type='v1.5')")
print("=" * 60)

invoice_path = str(Path(__file__).parent / "invoice_sample.jpg")
if not Path(invoice_path).exists():
    print(f"ERROR: invoice_sample.jpg not found at {invoice_path}")
    sys.exit(1)

try:
    from typhoon_ocr import ocr_document

    api_key = os.getenv("TYHOON_API_KEY", "")
    print(f"API key present: {bool(api_key)}")
    print(f"Calling ocr_document on: {invoice_path}")

    start = time.time()
    ocr_text = ocr_document(
        pdf_or_image_path=invoice_path,
        api_key=api_key,
        task_type="v1.5",
    )
    elapsed_ocr = time.time() - start

    print(f"\nOCR completed in {elapsed_ocr:.1f}s")
    print(f"OCR text length: {len(ocr_text)} chars")
    print("\n--- OCR Output (first 1000 chars) ---")
    print(ocr_text[:1000])
    if len(ocr_text) > 1000:
        print(f"... [+{len(ocr_text)-1000} more chars]")
    print("--- End OCR Output ---\n")

except Exception as e:
    print(f"OCR FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ── 2. LLM Extraction ─────────────────────────────────────────────────────────
print("=" * 60)
print("STEP 2: Typhoon LLM Extraction (typhoon-v2.5-30b-a3b-instruct)")
print("=" * 60)

try:
    from openai import OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.opentyphoon.ai/v1",
    )

    extraction_prompt = f"""Return JSON only with exact keys: 'invoice_number', 'invoice_date' (YYYY-MM-DD format), 
'po_reference', 'tax_id', 'vendor_name', 'subtotal' (number), 'vat_amount' (number), 'total_amount' (number).
Text: {ocr_text}"""

    start = time.time()
    response = client.chat.completions.create(
        model="typhoon-v2.5-30b-a3b-instruct",
        messages=[{"role": "user", "content": extraction_prompt}],
        temperature=0,
        max_tokens=4096,
    )
    elapsed_llm = time.time() - start

    raw_json = response.choices[0].message.content
    print(f"\nLLM completed in {elapsed_llm:.1f}s")

    # Clean markdown
    raw_json = raw_json.replace("```json", "").replace("```", "").strip()
    print("\n--- Raw LLM Response ---")
    print(raw_json)
    print("--- End LLM Response ---\n")

    extracted = json.loads(raw_json)
    print("=" * 60)
    print("EXTRACTED INVOICE DATA")
    print("=" * 60)
    for k, v in extracted.items():
        print(f"  {k}: {v}")

except Exception as e:
    print(f"LLM EXTRACTION FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print(f"\nTotal elapsed: {elapsed_ocr + elapsed_llm:.1f}s")
print("\nDONE")