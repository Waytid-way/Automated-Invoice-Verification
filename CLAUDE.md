# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Automated Invoice Verification system using Typhoon OCR and Typhoon LLM. Finance staff upload invoice images/PDFs, the system extracts data and verifies against PO database, then allows human review/editing before CSV export.

## Running the Application

```bash
# Main demo UI (Streamlit)
streamlit run demo_for_invoice.py

# Alternative web UI
streamlit run app.py

# Webhook server for LINE integration
python webhook_server.py

# Run OCR pipeline tests
python test_full_ocr_pipeline.py
```

## Architecture

- **orchestrator.py** - Core invoice processing: OCR → LLM extraction → PO matching → HITL review workflow
- **line_orchestrator.py** - LINE messaging integration for notification and approval workflow
- **swarm_invoice_agent.py** - Multi-agent swarm for complex invoice analysis
- **demo_for_invoice.py** / **app.py** - Streamlit web UIs
- **webhook_server.py** - Flask/FastAPI webhook endpoint for LINE bot
- **error_handler.py** - Error handling and retry logic
- **utils/llm.py** - Typhoon LLM API wrapper
- **line_notification.py** - LINE Notify/ Messaging API integration

## Typhoon API Rate Limits

Critical: Typhoon OCR enforces **20 req/min**. The code implements mandatory `time.sleep(3.1)` between OCR calls. If 429 occurs, triggers 10s cooldown retry. Never remove or reduce this delay.

- OCR: 20 req/min
- LLM: 200 req/min

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Individual test files
python -m pytest tests/test_ocr_extraction.py -v
python -m pytest tests/test_po_matching.py -v
python -m pytest tests/test_duplicate_detection.py -v
python -m pytest tests/test_error_handler.py -v
```

## Environment Variables

```env
TYPHOON_API_KEY=your_api_key_here
```

## Data Files

- `pending_review.json` - Invoices awaiting human review
- `paid_invoices.json` - Confirmed/paid invoices
- `po_vendor_data.json` - Purchase Order database for verification
- `discovered_group_ids.json` - LINE group IDs for notifications

## Key Workflow

1. Upload invoice images (JPG/PNG/PDF)
2. Batch OCR extraction with rate limiting
3. LLM structured data extraction (invoice_number, po_reference, total_amount, vendor_name)
4. PO matching verification
5. Human review via editable table (HITL)
6. Export audit CSV with utf-8-sig encoding for Thai characters
