# เอกสารออกแบบระบบ
## Automated Invoice Verification Agent

---

## 1. สถาปัตยกรรมระดับสูง (High-Level Architecture)

ระบบประกอบด้วยสถาปัตยกรรมแบบ 3 ชั้น (3-Layer Architecture) ที่แต่ละชั้นทำหน้าที่แยกกันอย่างชัดเจน ดังแสดงในแผนภาพต่อไปนี้

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│                         AUTOMATED INVOICE VERIFICATION AGENT                                  │
│                                    SYSTEM ARCHITECTURE                                         │
│                                                                                                │
│  ┌────────────────────────────────────────────────────────────────────────────────────────┐   │
│  │                              PRESENTATION LAYER (ชั้นนำเสนอ)                            │   │
│  │                                                                                        │   │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────┐ │   │
│  │  │                        Streamlit Web Application                                  │ │   │
│  │  │                                                                                  │ │   │
│  │  │  [Sidebar]                  [Main Area]               [Admin Panel]              │ │   │
│  │  │  • Mode Select (LOCAL/API)  • File Upload Zone        • PO/Vendor Management    │ │   │
│  │  │  • API Configuration        • Results Table           • Paid Invoice Management │ │   │
│  │  │  • Rate Limit Info          • HITL Approve Column     • Audit Log Viewer        │ │   │
│  │  │                            • Export CSV Button                                        │ │   │
│  │  └──────────────────────────────────────────────────────────────────────────────────┘ │   │
│  └────────────────────────────────────────────────────────────────────────────────────────┘   │
│                                              │                                                  │
│                                              ▼                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────────────────┐   │
│  │                        AGENT ORCHESTRATION LAYER (ชั้นประสานงานตัวแทน)                   │   │
│  │                                                                                        │   │
│  │                     OrchestratorAgent (orchestrator.py)                                │   │
│  │                     ทำหน้าที่ประสานงาน (Coordinate) และส่งต่อ (Hand-off)                  │   │
│  │                                                                                        │   │
│  │   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────┐│   │
│  │   │    OCR       │  │   LLM       │  │  Duplicate   │  │   PO        │  │  Error   ││   │
│  │   │   Agent      │→ │ Extraction  │→ │  Detection   │→ │  Matching   │→ │ Handler  ││   │
│  │   │  (Typhoon    │  │   Agent     │  │    Agent     │  │   Agent     │  │  Agent   ││   │
│  │   │   OCR)       │  │  (Typhoon   │  │  (3-Layer:   │  │  (2-Way: PO │  │ (Retry/  ││   │
│  │   │              │  │   LLM)      │  │  Exact/Finger│  │  Number +   │  │  Fallback││   │
│  │   │              │  │              │  │  /Fuzzy)     │  │  Amount)    │  │ /RateLt) ││   │
│  │   └──────────────┘  └──────────────┘  └──────────────┘  └──────┬─────┘  └────┬─────┘│   │
│  │                                                                   │             │      │   │
│  │                                            ◀──────────────────────┘             │      │   │
│  │                                            (Error → Recovery Loop)             │      │   │
│  └────────────────────────────────────────────────────────────────────────────────────────┘   │
│                                              │                                                  │
│                                              ▼                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────────────────┐   │
│  │                            DATA / MODEL LAYER (ชั้นข้อมูลและโมเดล)                      │   │
│  │                                                                                        │   │
│  │   ┌───────────────────────┐    ┌────────────────────────┐   ┌─────────────────────┐ │   │
│  │   │   Typhoon OCR Model   │    │   Typhoon LLM Model    │   │  JSON Data Stores  │ │   │
│  │   │   scb10x/typhoon-     │    │   typhoon-v2.5-30b-    │   │                     │ │   │
│  │   │   ocr1.5-3b           │    │   a3b-instruct         │   │  • po_vendor_data  │ │   │
│  │   │                       │    │                        │   │  • paid_invoices    │ │   │
│  │   │   LOCAL: Ollama        │    │   LOCAL: Ollama        │   │  • audit_logs.json  │ │   │
│  │   │   CLOUD: Typhoon API   │    │   CLOUD: Typhoon API   │   │                     │ │   │
│  │   └───────────────────────┘    └────────────────────────┘   └─────────────────────┘ │   │
│  └────────────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                                │
│  ┌────────────────────────────────────────────────────────────────────────────────────────┐   │
│  │                         EXTERNAL INTERFACE (อินเทอร์เฟซภายนอก — อนาคต)                   │   │
│  │                                                                                        │   │
│  │   ┌───────────────────────┐    ┌────────────────────────┐                            │   │
│  │   │   ERP System           │    │   REST API             │                            │   │
│  │   │   (SAP / Oracle /      │←── │   (Future Export)      │                            │   │
│  │   │    Microsoft Dynamics)  │    │                        │                            │   │
│  │   └───────────────────────┘    └────────────────────────┘                            │   │
│  └────────────────────────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

**โปรดสังเกต:** ทิศทางลูกศรแสดงทิศทางการไหลของข้อมูล (Data Flow) จากการอัปโหลดเอกสาร → OCR → LLM Extraction → Duplicate Detection → PO Matching → ผลลัพธ์สำหรับ HITL Review โดย Error Handler Agent ทำหน้าที่รับข้อผิดพลาดจากทุก Agent และส่งกลับไปยังขั้นตอนที่เหมาะสมเพื่อ Retry หรือ Fallback

---

## 2. รายละเอียดส่วนประกอบหลักของระบบ (Component Details)

### 2.1 Streamlit Web Application (`app.py`)

| หน้าที่ | รายละเอียด |
|--------|-----------|
| **File Upload** | รับ PDF, JPG, PNG หลายไฟล์พร้อมกัน (Batch Upload) ขนาดสูงสุด 10 MB ต่อไฟล์ |
| **Mode Selection** | สลับระหว่าง LOCAL (Ollama ที่ localhost:11434) กับ API (Typhoon Cloud) |
| **Results Table** | แสดงผล OCR + LLM Extraction + PO Matching + สถานะ + ช่อง Approve (HITL) |
| **Admin Panel** | CRUD ข้อมูล PO/Vendor, ดู Paid Invoice, ดู Audit Log, Export CSV |
| **Export CSV** | ดาวน์โหลด Audit Log เป็น CSV (UTF-8-sig) สำหรับ Import เข้า ERP |

### 2.2 OCR Agent (`orchestrator.py` → `_handle_ocr`)

| หน้าที่ | รายละเอียด |
|--------|-----------|
| **Input** | ไฟล์ PDF หรือ Image (JPG, PNG) |
| **Process** | ใช้ `typhoon_ocr.ocr_document()` สกัด Raw Text จากเอกสาร |
| **Output** | Raw Thai/English text สำหรับส่งต่อให้ LLM Extraction Agent |
| **Runtime Support** | LOCAL: Ollama endpoint; CLOUD: Typhoon API endpoint |

### 2.3 LLM Extraction Agent (`orchestrator.py` → `_handle_extraction`)

| หน้าที่ | รายละเอียด |
|--------|-----------|
| **Input** | Raw Text จาก OCR Agent |
| **Process** | ใช้ Typhoon LLM (`typhoon-v2.5-30b-a3b-instruct`) สกัดข้อมูลโครงสร้างตาม Prompt ที่กำหนด |
| **Output** | Structured JSON: `{invoice_number, po_reference, vendor_name, tax_id, subtotal, vat_amount, total_amount}` |
| **Prompt Design** | กำหนด Schema ชัดเจน + Few-shot examples เพื่อให้ LLM เข้าใจรูปแบบ |
| **VAT Post-process** | หาก LLM คืน `vat_amount=0` แต่ `subtotal>0` จะคำนวณ Thai VAT (7%) อัตโนมัติ |

### 2.4 Duplicate Detection Agent (`orchestrator.py` → `_handle_verification` ส่วน Duplicate)

| หน้าที่ | รายละเอียด |
|--------|-----------|
| **Layer 1: Exact Match** | เปรียบเทียบ Invoice Number ตรงกัน (case-insensitive) กับ `paid_invoices.json` |
| **Layer 2: Fingerprint Match** | Hash จาก `{vendor_name + total_amount + invoice_date}` เทียบกับ Cache |
| **Layer 3: Fuzzy Match** | SequenceMatcher บน Invoice Number (similarity ≥ 0.85) กรณีชื่อคล้ายกัน |
| **Output** | `DuplicateResult(is_duplicate, layer, matched_invoice, confidence)` |
| **Action** | Layer 1 → ปฏิเสธอัตโนมัติ (Reject); Layer 2-3 → แจ้งเตือน HITL ตรวจสอบ |

### 2.5 PO Matching Agent (`orchestrator.py` → `_handle_verification` ส่วน PO Matching)

| หน้าที่ | รายละเอียด |
|--------|-----------|
| **2-Way Matching** | ทางที่ 1: Invoice → PO Number เทียบกับ `po_vendor_data.json`; ทางที่ 2: PO → Invoice Amount |
| **Status** | `MATCHED` (POพบ+ยอดตรง), `AMOUNT_MISMATCH` (POพบ但ยอดไม่ตรง), `PO_NOT_FOUND` (POไม่พบ) |
| **VAT Handling** | คำนวณ Thai VAT (7%) อัตโนมัติหาก LLM คืน vat=0 แต่ total=subtotal*1.07 |
| **Output** | `POMatchResult(matched, po_number, status, approved_amount, invoice_amount, diff)` |

### 2.6 Error Handler Agent (`error_handler.py`)

| หน้าที่ | รายละเอียด |
|--------|-----------|
| **Retry Logic** | Retry 3 ครั้งก่อน Mark as Failed |
| **Fallback Strategy** | Cloud API fail → Fallback ไป LOCAL Ollama |
| **Rate Limit Handling** | 429 Too Many Requests → Cooldown 10 วินาที → Retry |
| **Error Severity** | `LOW` / `MEDIUM` / `HIGH` / `CRITICAL` สำหรับจัดลำดับการจัดการ |
| **Recovery Hooks** | มี Hook เฉพาะสำหรับแต่ละ Agent (OCR/Extraction/Verification) เพื่อ Recovery แบบเฉพาะ |

---

## 3. รูปแบบข้อมูลเข้าและออก (Input/Output Data)

### 3.1 Invoice Extraction Output (Structured JSON)

```json
{
  "invoice_number": "INV-2024-001",
  "invoice_date": "2024-03-15",
  "po_reference": "PO-2023-001",
  "vendor_name": "บริษัท วัสดุก่อสร้าง จำกัด",
  "tax_id": "0105555555555",
  "subtotal": 10000.00,
  "vat_amount": 700.00,
  "total_amount": 10700.00,
  "extraction_confidence": 0.95,
  "raw_ocr_text": "... (ต้นฉบับ OCR ฉบับเต็ม) ..."
}
```

**สี公道说明:**
- `invoice_number` — เลขที่ใบแจ้งหนี้
- `invoice_date` — วันที่ออกใบแจ้งหนี้ (รูปแบบ YYYY-MM-DD)
- `po_reference` — เลขที่ใบสั่งซื้อที่อ้างถึง
- `vendor_name` — ชื่อผู้ขาย/ผู้รับจ้าง
- `tax_id` — เลขประจำตัวผู้เสียภาษี
- `subtotal` — ราคาก่อน VAT
- `vat_amount` — ภาษีมูลค่าเพิ่ม (Thai VAT = 7%)
- `total_amount` — ราคารวมทั้งสิ้น
- `extraction_confidence` — ความมั่นใจของ LLM ในการสกัดข้อมูล (0.0–1.0)

### 3.2 PO Database Schema (`po_vendor_data.json`)

```json
{
  "PO-2023-001": {
    "vendor": "บริษัท วัสดุก่อสร้าง จำกัด",
    "tax_id": "0105555555555",
    "approved_amount": 10700.00
  },
  "PO-2023-002": {
    "vendor": "ร้านเหล็กไทย",
    "tax_id": "0104444444444",
    "approved_amount": 50000.00
  },
  "IV1806-0002": {
    "vendor": "surebattstore",
    "tax_id": "0103333333333",
    "approved_amount": 410.00
  }
}
```

### 3.3 Paid Invoices Database Schema (`paid_invoices.json`)

```json
[
  "INV-0001",
  "INV-9999",
  "IV1806-0001"
]
```

### 3.4 CSV Export Format

```csv
Invoice Number,PO Reference,Vendor Name,Total Amount,Status,Verified By,Verified At,Approved,Approved By
INV-2024-001,PO-2023-001,บริษัท วัสดุก่อสร้าง จำกัด,10700.00,MATCHED,สมชาย,2024-03-15 10:30:00,true,สมชาย
INV-2024-002,PO-2023-002,ร้านเหล็กไทย,52000.00,AMOUNT_MISMATCH,สมหญิง,2024-03-15 11:00:00,false,
INV-2024-003,PO-2023-003,บริษัท ขนส่ง จำกัด,8300.00,PO_NOT_FOUND,สมชาย,2024-03-15 11:15:00,false,
```

---

## 4. แนวทางการเชื่อมต่อกับระบบหลัก / ERP (ERP Integration Future)

### 4.1 สถาปัตยกรรมการเชื่อมต่อในอนาคต

```
┌─────────────────────────────────┐     ┌──────────────────────┐
│  Invoice Verification Agent     │────→│   ERP System         │
│                                 │     │  (SAP / Oracle /     │
│  Current: JSON File Storage    │     │   Microsoft Dynamics) │
│  Future: REST API Export        │     └──────────────────────┘
└─────────────────────────────────┘
```

### 4.2 REST API Endpoints Design (อนาคต)

| Endpoint | Method | Request Body / Query | Response | รายละเอียด |
|----------|--------|----------------------|----------|------------|
| `/api/v1/invoices` | POST | `{invoice_data, verification_result, approved_by}` | `{invoice_id, status}` | ส่ง Invoice ที่ Approved เข้า ERP |
| `/api/v1/pos` | GET | `?vendor=&amount=` | `{pos: [...]}` | ดึงข้อมูล PO จาก ERP มาตรวจสอบ |
| `/api/v1/invoices/{id}/status` | PATCH | `{status, updated_by, remarks}` | `{invoice_id, new_status}` | อัปเดตสถานะหลัง ERP ประมวลผล |
| `/api/v1/vendors` | GET | `?tax_id=` | `{vendor_id, name, tax_id}` | ดึงข้อมูลผู้ขายจาก ERP |
| `/api/v1/audit` | GET | `?from=&to=&user=` | `{audit_logs: [...]}` | ดึง Audit Log จาก ERP |

### 4.3 ข้อจำกัดในเวอร์ชันปัจจุบัน (Current Limitation)

| ข้อจำกัด | รายละเอียด |
|----------|------------|
| **ไม่มี ERP จริง** | ระบบปัจจุบันใช้ JSON File (`po_vendor_data.json`, `paid_invoices.json`) เป็น Database จำลองเท่านั้น |
| **CSV Export แทน API** | การส่งมอบข้อมูลใช้วิธี Export CSV (UTF-8-sig) สำหรับ Import เข้า ERP ด้วยมือ (Manual Entry) |
| **Vendor Master จำลอง** | ข้อมูลผู้ขายเก็บใน JSON ไม่ได้เชื่อมต่อ Vendor Master จริง |
| **Phase ถัดไป** | การเชื่อมต่อ REST API กับ ERP จริง (SAP/Oracle) ต้องพัฒนาเพิ่มใน Phase ถัดไป |

---

## 5. การจัดการสิทธิ์และการตรวจสอบย้อนหลัง (Access Control & Audit)

### 5.1 Role-Based Access Control (RBAC)

| บทบาท (Role) | สิทธิ์และขอบเขต |
|-------------|----------------|
| **Staff (พนักงาน)** | อัปโหลด Invoice, ดูผลประมวลผล OCR/LLM, ตรวจสอบรายการ, อนุมัติวงเงิน ≤ 10,000 บาท |
| **Supervisor (หัวหน้างาน)** | ทุกสิทธิ์ของ Staff + อนุมัติวงเงิน ≤ 50,000 บาท + ดู Audit Log |
| **Manager (ผู้จัดการ)** | ทุกสิทธิ์ + อนุมัติทุกวงเงิน + ตั้งค่า/แก้ไข PO ละ Vendor + สั่ง Export CSV |
| **Admin (ผู้ดูแลระบบ)** | ทุกสิทธิ์ + จัดการผู้ใช้ + ดู System Log + เปลี่ยนแปลง Admin Password |

### 5.2 Authentication

| วิธี | รายละเอียด |
|------|-----------|
| **Admin Login** | Password-based authentication ผ่าน Streamlit session state (Default: `admin123` — ควรเปลี่ยนใน Production) |
| **Staff** | ไม่มี Login ในเวอร์ชันแรก (ใช้งานร่วมกันบนเครื่องเดียว ผ่าน Shared Session) |
| **อนาคต** | รองรับ Multi-user Login ผ่าน LDAP / SSO Integration |
| **Session Management** | Streamlit `st.session_state` เก็บสถานะ Authentication ระหว่าง Session |

### 5.3 Audit Log Schema

```json
{
  "id": "audit_20240415_001",
  "timestamp": "2024-04-15T10:30:00",
  "user": "สมชาย",
  "role": "Staff",
  "action": "APPROVE_INVOICE",
  "invoice_number": "INV-2024-001",
  "po_reference": "PO-2023-001",
  "amount": 10700.00,
  "before_state": "PENDING_APPROVAL",
  "after_state": "APPROVED",
  "ip_address": "192.168.1.10",
  "session_id": "sess_abc123",
  "remarks": "Invoice matched PO, within approval limit"
}
```

### 5.4 Audit Log Fields Specification

| Field | ประเภท | รายละเอียด |
|-------|--------|------------|
| `id` | string | รหัสเฉพาะของ Audit Record (รูปแบบ: `audit_YYYYMMDD_NNN`) |
| `timestamp` | datetime | วันเวลาที่เกิดเหตุการณ์ (ISO 8601 format) |
| `user` | string | ชื่อผู้ใช้ที่ดำเนินการ |
| `role` | string | บทบาทของผู้ใช้ ณ เวลาที่ดำเนินการ |
| `action` | string | ประเภทการกระทำ เช่น `UPLOAD`, `APPROVE_INVOICE`, `REJECT_INVOICE`, `EXPORT_CSV`, `UPDATE_PO`, `LOGIN`, `LOGOUT` |
| `invoice_number` | string | เลขที่ใบแจ้งหนี้ที่เกี่ยวข้อง (ถ้าเกี่ยวข้อง) |
| `po_reference` | string | เลขที่ใบสั่งซื้อที่เกี่ยวข้อง (ถ้าเกี่ยวข้อง) |
| `before_state` | string | สถานะก่อนการกระทำ |
| `after_state` | string | สถานะหลังการกระทำ |
| `ip_address` | string | IP Address ของผู้ใช้ ณ เวลาที่ดำเนินการ |
| `session_id` | string | Streamlit Session ID สำหรับติดตาม Session |

### 5.5 Data Retention Policy

| ประเภทข้อมูล | ระยะเวลาเก็บรักษา | เหตุผล |
|-------------|------------------|--------|
| Audit Logs | 5 ปี | ตามข้อกำหนด Compliance และ Financial Audit |
| Approved Invoices | ถาวร | หลักฐานทางบัญชีที่ต้องเก็บไว้ถาวร |
| Rejected Invoices | 2 ปี | กรณีมีการโต้แย้งในภายหลัง |
| OCR/Extraction Raw Data | 1 ปี | Debugging และ Model Improvement |

---

## 6. สรุปเทคโนโลยีที่ใช้ (Technology Stack Summary)

| ชั้น (Layer) | เทคโนโลยี | รายละเอียด |
|-------------|----------|------------|
| **Frontend (Presentation)** | Streamlit | Python Web Application Framework — ใช้สำหรับ UI, File Upload, Results Display |
| **OCR Engine** | Typhoon OCR (`scb10x/typhoon-ocr1.5-3b`) | OCR Model รองรับภาษาไทยและภาษาอังกฤษ รับ Input เป็น PDF/Image |
| **LLM (Extraction)** | Typhoon LLM (`typhoon-v2.5-30b-a3b-instruct`) | Large Language Model สำหรับสกัด Structured JSON จาก Raw OCR Text |
| **Orchestration** | Python (OrchestratorAgent) | Swarm Multi-Agent Pattern — ประสานงานทุก Agent ให้ทำงานต่อเนื่องกัน |
| **Error Handling** | Python (ErrorHandler) | Retry Logic, Fallback Strategy, Rate Limit Handling |
| **Data Storage** | JSON Files | 3 ไฟล์หลัก: `po_vendor_data.json` (PO Database), `paid_invoices.json` (Paid List), `audit_logs.json` (Audit Trail) |
| **Runtime Environment** | Local (Ollama) หรือ Cloud (Typhoon API) | ผู้ใช้เลือกได้ — LOCAL ใช้ Ollama ที่ localhost:11434; CLOUD ใช้ Typhoon Official API |
| **LINE Notification** | LINE Messaging API | แจ้งเตือนผลการอนุมัติ/ปฏิเสธ/Error ไปยัง LINE Group |
| **Deployment** | Local Machine หรือ Cloud Server | ไม่ต้องติดตั้งเพิ่มเติม — ใช้ได้ทั้งบนเครื่อง Local และ Server |
| **Python Version** | Python 3.11+ | รองรับโดย venv virtual environment |
