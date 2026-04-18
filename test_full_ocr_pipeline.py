#!/usr/bin/env python3
"""
Comprehensive test of Typhoon OCR + LLM on invoice_sample.jpg.
Tests with the exact spec: typhoon_ocr.ocr_document(task_type='v1.5')
and typhoon-v2.5-30b-a3b-instruct.
"""
import os
import sys
import json
import time
from pathlib import Path

# ── Load .env ───────────────────────────────────────────────────────────────
ENV_PATH = Path(__file__).parent / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().strip().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

invoice_path = str(Path(__file__).parent / "invoice_sample.jpg")
api_key = os.getenv("TYHOON_API_KEY", "")

print("=" * 70)
print("COMPREHENSIVE OCR + LLM PIPELINE TEST")
print("=" * 70)
print(f"Invoice: {invoice_path}")
print(f"File exists: {Path(invoice_path).exists()}")
print(f"API key available: {bool(api_key)}")
print()

# ── STEP 1: OCR ─────────────────────────────────────────────────────────────
print("=" * 70)
print("STEP 1: Typhoon OCR  (typhoon_ocr.ocr_document, task_type='v1.5')")
print("=" * 70)

from typhoon_ocr import ocr_document

try:
    start = time.time()
    ocr_text = ocr_document(
        pdf_or_image_path=invoice_path,
        api_key=api_key,
        task_type="v1.5",
    )
    elapsed_ocr = time.time() - start
    print(f"SUCCESS — {elapsed_ocr:.1f}s")
    print(f"OCR text length: {len(ocr_text)} chars")
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n--- Full OCR Output ---")
print(ocr_text)
print("--- End OCR Output ---\n")

# ── STEP 2: LLM Extraction ─────────────────────────────────────────────────
print("=" * 70)
print("STEP 2: Typhoon LLM  (typhoon-v2.5-30b-a3b-instruct)")
print("=" * 70)

from openai import OpenAI

client = OpenAI(api_key=api_key, base_url="https://api.opentyphoon.ai/v1")

extraction_prompt = f"""Return JSON only with exact keys: 'invoice_number', 'invoice_date' (YYYY-MM-DD format), 
'po_reference', 'tax_id', 'vendor_name', 'subtotal' (number), 'vat_amount' (number), 'total_amount' (number).
Text: {ocr_text}"""

try:
    start = time.time()
    response = client.chat.completions.create(
        model="typhoon-v2.5-30b-a3b-instruct",
        messages=[{"role": "user", "content": extraction_prompt}],
        temperature=0,
        max_tokens=4096,
    )
    elapsed_llm = time.time() - start
    raw_json = response.choices[0].message.content
    raw_json_clean = raw_json.replace("```json", "").replace("```", "").strip()
    extracted = json.loads(raw_json_clean)
    print(f"SUCCESS — {elapsed_llm:.1f}s")
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n--- Extracted Data ---")
for k, v in extracted.items():
    print(f"  {k}: {v}")

print(f"\nTotal elapsed: {elapsed_ocr + elapsed_llm:.1f}s")

# ── BUG ANALYSIS ────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("BUG / ISSUE ANALYSIS")
print("=" * 70)

# Check 1: VAT amount
vat = extracted.get("vat_amount", "MISSING")
total = extracted.get("total_amount", "MISSING")
subtotal = extracted.get("subtotal", "MISSING")
print(f"\n[CHECK 1] VAT Amount: {vat} (expected 28.70 if 7% VAT on 410)")
print(f"  subtotal={subtotal}, total={total}")
if isinstance(vat, (int, float)) and vat == 0 and isinstance(subtotal, (int, float)) and subtotal > 0:
    print("  BUG: VAT is 0 but should be ~7% of subtotal for Thai invoice")

# Check 2: PO reference placeholder
po_ref = extracted.get("po_reference", "")
print(f"\n[CHECK 2] PO Reference: '{po_ref}'")
if "xxx" in str(po_ref) or "xxxx" in str(po_ref):
    print("  BUG: LLM returned a placeholder instead of reading from OCR text")

# Check 3: OCR text content check
print("\n[CHECK 3] OCR Text Quality")
if "PO" in ocr_text or "Purchase Order" in ocr_text or "ใบสั่งซื้อ" in ocr_text:
    print("  OCR contains PO reference text — LLM should have extracted it")
else:
    print("  WARNING: OCR text may not contain PO reference at all")

# Check 4: invoice_date format
inv_date = extracted.get("invoice_date", "")
print(f"\n[CHECK 4] Invoice Date: '{inv_date}' (format should be YYYY-MM-DD)")
import re
if inv_date and not re.match(r"\d{4}-\d{2}-\d{2}", str(inv_date)):
    print(f"  WARNING: Date not in YYYY-MM-DD format")

print("\nDONE")