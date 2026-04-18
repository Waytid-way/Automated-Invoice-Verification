# Automated Invoice Verification Agent
## Proposal for Mango Co., Ltd.

---

## 1. Problem Statement

### Context
พนักงานฝ่ายบัญชี/การเงินของ Mango ต้องตรวจสอบใบแจ้งหนี้ (Invoice) จากคู่ค้าทุกวัน โดยการเปิดเอกสาร PDF ทีละใบและเทียบยอดกับใบสั่งซื้อ (PO) ในระบบด้วยตนเอง

### Pain Points
- **Manual ทั้งหมด** — อ่าน Invoice, ค้นหา PO, เปรียบเทียบยอดเงิน, ตรวจสอบรายการสินค้า, บันทึกผล
- **ข้อผิดพลาดจากมนุษย์** — พิมพ์ตัวเลขผิด, อ่านตัวเลขผิด โดยเฉพาะเมื่อปริมาณงานสูง
- **ความเสี่ยงทางการเงิน** — จ่ายซ้ำ หรือจ่ายผิดยอด

### Impact
| ตัวชี้วัด | ค่า |
|-----------|-----|
| เวลาตรวจสอบเฉลี่ย | 20–40 นาที/ใบ |
| ปริมาณงาน/วัน | 20 ใบ |
| ภาระงานรวม | 7–13 ชั่วโมง/วัน |
| ความเสี่ยง | จ่ายซ้ำ, จ่ายผิดยอด, รายงานการเงินผิดพลาด |

---

## 2. Proposed Solution

### Overview
สร้าง **Agentic AI Web Application** ที่ทำงานอัตโนมัติ 3 ขั้นตอน:

```
[Invoice Image/PDF]
       │
       ▼
┌─────────────────┐
│  1. Typhoon OCR │  ← Vision model สกัด text จากเอกสาร
└────────┬────────┘
         ▼
┌─────────────────┐
│  2. Typhoon LLM │  ← แปลง text → structured JSON
└────────┬────────┘
         ▼
┌─────────────────┐
│ 3. Verification │  ← เปรียบเทียบกับ PO Database
└────────┬────────┘
         ▼
  [Staff Approval]
         │
         ▼
   [Export CSV]
```

### Human-in-the-Loop (HITL)
- ทุกผลลัพธ์ผ่าน staff approve ก่อน post เข้า ERP เสมอ
- ระบบแจ้งเตือนผ่าน LINE เมื่อมีเอกสารรอตรวจสอบ
- Staff สามารถแก้ไขข้อมูลก่อน approve ได้ทันที

---

## 3. System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         USER INTERFACE                            │
│  ┌─────────────────────┐         ┌─────────────────────────────┐ │
│  │   Streamlit Web UI   │         │      LINE Messaging OA     │ │
│  │  (Upload + Review)   │         │   (Notification + Approve) │ │
│  └──────────┬───────────┘         └──────────────┬──────────────┘ │
└─────────────┼─────────────────────────────────────┼───────────────┘
              │                                     │
              │          ┌──────────────────────────┘
              ▼          ▼
┌──────────────────────────────────────────────────────────────────┐
│                      PROCESSING LAYER                             │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │                    orchestrator.py                          │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐  │  │
│  │  │  OCR     │→ │ LLM      │→ │ Verify   │→ │ Queue     │  │  │
│  │  │  Agent   │  │ Extract  │  │ Agent    │  │ Manager   │  │  │
│  │  └──────────┘  └──────────┘  └──────────┘  └───────────┘  │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                              │                                    │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │                   error_handler.py                           │  │
│  │  Retry logic │ Graceful degradation │ Rate limit handling    │  │
│  └─────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
              │
              ▼
┌──────────────────────────────────────────────────────────────────┐
│                       DATA LAYER                                  │
│  ┌────────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │ po_vendor_data │  │ pending_review  │  │  paid_invoices     │  │
│  │ (PO Database)  │  │ (Review Queue)  │  │ (Paid History)    │  │
│  └────────────────┘  └─────────────────┘  └────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
              │
              ▼
┌──────────────────────────────────────────────────────────────────┐
│                    EXTERNAL SERVICES                              │
│  ┌──────────────────┐              ┌──────────────────────────┐  │
│  │ Typhoon OCR API  │              │   Typhoon LLM API        │  │
│  │ (Vision Model)   │              │   (Chat Completions)     │  │
│  └──────────────────┘              └──────────────────────────┘  │
│  ┌──────────────────┐              ┌──────────────────────────┐  │
│  │ LINE Messaging   │              │   LINE Data API         │  │
│  │ (Push/Reply)     │              │   (Download content)    │  │
│  └──────────────────┘              └──────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. Workflow Detail

### 4.1 Invoice Processing Pipeline

```
Step 1: OCR (Typhoon Vision Model)
──────────────────────────────────
Input : Invoice image (JPG/PNG/PDF)
Output: Raw text (markdown format)

Step 2: LLM Extraction (Typhoon Language Model)
───────────────────────────────────────────────
Input : Raw OCR text
Output: Structured JSON
{
  "invoice_number": "IV1806-0002",
  "invoice_date": "2024-06-28",
  "po_reference": "PO-2024-001",
  "vendor_name": "Surebatt Store",
  "tax_id": "1234567890123",
  "subtotal": 410.00,
  "vat_amount": 0.00,
  "total_amount": 410.00
}

Step 3: Verification (Rule-based Agent)
──────────────────────────────────────
Logic :
  IF invoice_number IN paid_invoices:
      → DUPLICATE_INVOICE → Reject
  ELSE IF po_reference IN po_database:
      IF total_amount == approved_amount:
          → MATCHED → Approve
      ELSE:
          → AMOUNT_MISMATCH → Hold (แจ้ง staff ตรวจสอบ)
  ELSE:
      → PO_NOT_FOUND → Hold (แจ้ง staff ตรวจสอบ)
```

### 4.2 LINE Integration Workflow

```
User sends invoice image
         │
         ▼
┌─────────────────────┐
│ LINE Webhook Server  │  ← Flask app on Railway
│ (webhook_server.py)  │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ line_orchestrator   │  ← Download image → Process
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ orchestrator.py     │  ← OCR → LLM → Verify
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ LINE Notification   │  ← ส่งผลกลับ LINE Group
│ (line_notification) │
└─────────────────────┘

Message Types:
  ✅ [APPROVED]  Invoice X — 410 THB — Vendor: Surebatt Store
  ⚠️ [ESCALATION] Invoice X — PO_NOT_FOUND — PO: PO-2024-999
  ❌ [REJECTED]  Invoice X — พบประวัติการจ่ายแล้ว
  🔴 [ERROR]     OCR/LLM processing failed
```

### 4.3 Human Review Workflow

```
Invoice ที่ผ่าน OCR+LLM+Verify
           │
           ▼
┌─────────────────────────────────────┐
│ 3 กรณี                             │
├─────────────────────────────────────┤
│ ✅ MATCHED     → แนะนำ Approve      │
│ ⚠️ HOLD        → รอ staff ตัดสินใจ   │
│ ❌ REJECT      → แนะนำ Reject        │
└─────────────────────────────────────┘
           │
           ▼
Staff ตรวจสอบใน Streamlit UI
  - ดูข้อมูลที่ AI สกัด
  - แก้ไขได้ถ้าผิด
  - เลือก Action: Approve / Hold / Reject
           │
           ▼
Export CSV สำหรับโหลดเข้า ERP
  - กรองเฉพาะที่ไม่ Reject
  - Format: utf-8-sig (ภาษาไทยไม่เพี้ยน)
  - Columns: Status, DocDate, InvoiceNo, PONumber, VendorName, VendorTaxID, AmountBeforeTax, TaxAmount, TotalAmount, Memo
```

---

## 5. Component Specifications

### 5.1 Core Components

| File | Responsibility | Key Functions |
|------|---------------|---------------|
| `orchestrator.py` | Invoice processing pipeline | `process_invoice_from_file()` — OCR → LLM → Verify loop |
| `line_orchestrator.py` | LINE integration | `LineOrchestrator.process_invoice_from_line()` — LINE download + process |
| `line_notification.py` | LINE push notifications | `send_line_notification()` — ส่ง message ไป LINE Group |
| `error_handler.py` | Error recovery | Retry logic, rate limit backoff, graceful degradation |
| `webhook_server.py` | LINE webhook endpoint | Flask app, filter by GROUP_ID, handle image/file/text |
| `demo_for_invoice.py` | Streamlit web UI | Upload, batch process, HITL review, CSV export |

### 5.2 Data Files

| File | Purpose | Schema |
|------|---------|--------|
| `po_vendor_data.json` | PO Database | `{po_number: {vendor, tax_id, approved_amount}}` |
| `pending_review.json` | Review Queue | `{items: [{item_id, invoice_data, action, remarks}]}` |
| `paid_invoices.json` | Paid History | `{invoices: [invoice_number, ...]}` |

### 5.3 External APIs

| Service | Purpose | Rate Limit |
|---------|---------|------------|
| Typhoon OCR | Image → Text | 20 req/min |
| Typhoon LLM | Text → JSON | 200 req/min |
| LINE Messaging API | Notifications | 1000 req/day |
| LINE Data API | Download image | 1000 req/day |

---

## 6. LINE Open API Integration

### 6.1 LINE Messaging API Features

```
Webhook Events Handled:
  • message (image, file, text)
  • postback
  • join/leave group

Reply/Push Messages:
  • Text messages with emoji indicators
  • Formatted status updates
  • Escalation alerts
```

### 6.2 LINE OA User Flow

```
┌──────────────────────────────────────────────────────┐
│ LINE Group: Mango AP Team                            │
│                                                      │
│  📱 User sends invoice image to LINE OA              │
│                                                      │
│  🤖 Bot replies: "Processing your invoice image..."  │
│                                                      │
│  📊 After OCR+LLM: Bot posts to Group:              │
│     "⚠️ [ESCALATION] Invoice IV1806-0002"           │
│      "PO_NOT_FOUND — PO: PO-2024-999"               │
│                                                      │
│  👨‍💻 Staff reviews in Streamlit:                    │
│     - Confirms correct PO number                     │
│     - Edits data if needed                           │
│     - Clicks "Approve"                              │
│                                                      │
│  📋 Export CSV for ERP upload                        │
└──────────────────────────────────────────────────────┘
```

---

## 7. Rate Limiting & Error Handling

### 7.1 Typhoon API Rate Limits

```python
API_RATE_LIMIT_DELAY = 3.1  # วินาทีระหว่าง OCR call (20 req/min)

On 429 (Rate Limited):
  → รอ 10 วินาที แล้ว retry
  → ถ้า retry สำเร็จ ดำเนินการต่อ
  → ถ้า retry ล้มเหลว ส่ง LINE notification แจ้ง error
```

### 7.2 LINE API Rate Limits

```python
On 429:
  → Exponential backoff: 2s, 4s, 8s
  → Max 3 attempts

On 5xx:
  → Exponential backoff: 2s, 4s, 8s
  → Max 3 attempts
```

### 7.3 Error Recovery Strategies

| Step | Error | Recovery |
|------|-------|----------|
| OCR | Connection timeout | Retry 3 ครั้ง, ถ้าล้มเหลวส่ง error notification |
| OCR | Rate limit | รอ 10 วินาที, ลองใหม่ |
| LLM | JSON parse error | Retry, ถ้าล้มเหลว mark as FAILED |
| LLM | 429 Rate limit | รอ 10 วินาที, ลองใหม่ |
| LINE | 401 Unauthorized | Log + แจ้ง config error |
| LINE | 429 Rate limit | Exponential backoff |

---

## 8. Deployment Architecture

### 8.1 Railway (Webhook Server)

```
Railway Service: harmonious-creativity
URL: https://harmonious-creativity-production.up.railway.app/webhook

Environment Variables:
  • LINE_CHANNEL_ACCESS_TOKEN
  • LINE_GROUP_ID
  • TYHOON_API_KEY

Deploy Config:
  • Build: Python 3.11 (NIXPACKS auto-detect)
  • Start: gunicorn webhook_server:app --bind :$PORT --workers 2 --timeout 120
```

### 8.2 Streamlit Cloud (Web UI)

```
Streamlit Cloud App
URL: https://share.streamlit.io/YOUR-USER/Automated-Invoice-Verification

Secrets (Set in Streamlit Cloud dashboard):
  • TYHOON_API_KEY
  • LINE_CHANNEL_ACCESS_TOKEN
  • LINE_GROUP_ID
```

### 8.3 LINE Webhook Configuration

```
Webhook URL:
  https://harmonious-creativity-production.up.railway.app/webhook

LINE Developers Console:
  1. Messaging API settings → Webhook URL
  2. กด "Verify" to confirm
  3. Enable auto-reply (off)
  4. Enable group mode
```

---

## 9. Export Format (ERP Import)

### 9.1 CSV Structure

```csv
Status,DocDate,InvoiceNo,PONumber,VendorName,VendorTaxID,AmountBeforeTax,TaxAmount,TotalAmount,Memo
Approve,2024-06-28,IV1806-0002,PO-2024-001,Surebatt Store,1234567890123,410.00,0.00,410.00,
Approve,2024-06-29,IV1806-0003,PO-2024-002,ABC Co.,,9876543210987,10000.00,700.00,10700.00,
Hold,2024-06-30,IV1806-0004,PO-2024-999,Unknown Vendor,,500.00,35.00,535.00,ไม่พบเลข PO ในระบบ
```

### 9.2 Encoding
- **UTF-8-BOM** — เพื่อให้ Excel แสดงภาษาไทยถูกต้อง

---

## 10. Expected Benefits

| ตัวชี้วัด | ก่อน | หลัง | ลดลง |
|-----------|------|------|------|
| เวลาตรวจสอบ/ใบ | 20–40 นาที | 2–3 นาที | **~90%** |
| ภาระงาน/วัน (20 ใบ) | 7–13 ชั่วโมง | 40–60 นาที | **~90%** |
| ความผิดพลาดจากมนุษย์ | สูง | ต่ำ | **~95%** |
| การจ่ายซ้ำ/จ่ายผิดยอด | มีโอกาส | ป้องกันได้ | **100%** |

---

## 11. Future Enhancements (Phase 2)

- [ ] **Multi-language OCR** — รองรับ Invoice ภาษาอังกฤษ/จีน/เขมร
- [ ] **Role-based Approval** — วงเงินต่ำกว่า 10,000 บาท approve ได้ทันที, สูงกว่านั้นต้อง manager
- [ ] **ERP Integration** — เชื่อมตรงกับ SAP/Oracle/Eloquent แทน CSV export
- [ ] **Dashboard Analytics** — สถิติประจำเดือน, vendor ranking, error rates
- [ ] **Mobile UI** — ตรวจสอบและ approve ผ่าน LINE OA ได้เลย

---

## 12. Project Structure

```
Automated-Invoice-Verification/
├── demo_for_invoice.py              # Streamlit Web UI
├── webhook_server.py                # LINE Webhook Server (Flask)
├── orchestrator.py                  # Core Invoice Processing Pipeline
├── line_orchestrator.py            # LINE Integration Wrapper
├── line_notification.py            # LINE Push Notifications
├── error_handler.py                 # Retry & Error Recovery
├── swarm_invoice_agent.py          # Multi-agent Swarm Architecture
│
├── railway.json                     # Railway deployment config
├── requirements.txt                # Python dependencies
│
├── po_vendor_data.json             # PO database
├── pending_review.json             # Review queue
├── paid_invoices.json              # Paid invoice history
│
└── tests/                          # Test suite
    ├── test_ocr_extraction.py
    ├── test_po_matching.py
    ├── test_duplicate_detection.py
    └── test_error_handler.py
```

---

## 13. Technical Constraints & Notes

1. **Typhoon API Rate Limit** — บังคับ delay 3.1 วินาทีระหว่าง OCR calls
2. **LINE Reply Token** — ใช้ได้ครั้งเดียว ต้อง reply ทันทีหลัง receive webhook
3. **Temporary File Cleanup** — ลบไฟล์ชั่วคราวหลัง OCR เสร็จทุกครั้ง
4. **JSON Validation** — LLM อาจ return ไม่ตรง format ต้องมี try/catch + retry
5. **Duplicate Prevention** — ตรวจสอบ invoice_number กับ paid_invoices ก่อน approve

---

*Document version: 1.0*
*Last updated: 2026-04-18*
*Prepared by: Automated Invoice Verification Team*
