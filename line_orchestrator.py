"""
LINE Bot Orchestrator for Automated Invoice Verification.

Wraps the OCR+LLM invoice processing pipeline with queue management,
duplicate detection, PO matching, and LINE notification integration.
"""

import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI
from typhoon_ocr import ocr_document

from line_notification import send_line_notification

load_dotenv()

logger = logging.getLogger(__name__)

# ==========================================
# Mode Configuration
# ==========================================

PROCESSING_MODE = os.getenv("PROCESSING_MODE", "API").upper()

if PROCESSING_MODE == "LOCAL":
    OCR_BASE_URL = "http://localhost:11434/v1"
    OCR_MODEL = "scb10x/typhoon-ocr1.5-3b"
    LLM_BASE_URL = "http://localhost:11434/v1"
    LLM_MODEL = "scb10x/typhoon2.5-qwen3-4b"
    API_KEY = "ollama"
else:
    OCR_BASE_URL = "https://api.opentyphoon.ai/v1"
    OCR_MODEL = "typhoon-ocr"
    LLM_BASE_URL = "https://api.opentyphoon.ai/v1"
    LLM_MODEL = "typhoon-v2.5-30b-a3b-instruct"
    API_KEY = os.getenv("TYHOON_API_KEY", "")

# Rate limit delay for API mode (seconds)
API_RATE_LIMIT_DELAY = 3.1

# ==========================================
# Data File Paths
# ==========================================

_BASE_DIR = Path(__file__).parent.resolve()
PO_VENDOR_DATA_PATH = _BASE_DIR / "po_vendor_data.json"
PAID_INVOICES_PATH = _BASE_DIR / "paid_invoices.json"
PENDING_REVIEW_PATH = _BASE_DIR / "pending_review.json"

# ==========================================
# Global Client (lazily initialized)
# ==========================================

_openai_client: Optional[OpenAI] = None


def _get_openai_client() -> OpenAI:
    """Get or create the global OpenAI client."""
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=API_KEY, base_url=LLM_BASE_URL)
    return _openai_client


# ==========================================
# Data Loading
# ==========================================


def _load_po_data() -> Dict[str, Dict[str, Any]]:
    """
    Load PO/vendor data from JSON file.

    Returns:
        Dictionary mapping PO number to vendor info dict.
    """
    try:
        with open(PO_VENDOR_DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"PO vendor data file not found at {PO_VENDOR_DATA_PATH}. Returning empty dict.")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse PO vendor data JSON: {e}")
        return {}


def _load_paid_invoices() -> set:
    """
    Load paid invoice numbers from JSON file.

    Returns:
        Set of paid invoice number strings.
    """
    try:
        with open(PAID_INVOICES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return set(data)
            elif isinstance(data, dict) and "invoices" in data:
                return set(data["invoices"])
            else:
                logger.warning(f"Unexpected paid_invoices.json structure: {type(data)}. Expected list or {{'invoices': [...]}}.")
                return set()
    except FileNotFoundError:
        logger.warning(f"Paid invoices file not found at {PAID_INVOICES_PATH}. Returning empty set.")
        return set()
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse paid invoices JSON: {e}")
        return set()


def _load_pending_review() -> List[Dict[str, Any]]:
    """
    Load pending review queue from JSON file.

    Returns:
        List of pending review item dicts.
    """
    try:
        with open(PENDING_REVIEW_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and "items" in data:
                return data["items"]
            else:
                logger.warning(f"Unexpected pending_review.json structure: {type(data)}. Expected list or {{'items': [...]}}.")
                return []
    except FileNotFoundError:
        logger.info(f"Pending review file not found at {PENDING_REVIEW_PATH}. Will initialize new file on first save.")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse pending review JSON: {e}")
        return []


def _save_pending_review(items: List[Dict[str, Any]]) -> None:
    """
    Persist pending review queue to JSON file.

    Args:
        items: List of pending review item dicts to save.
    """
    try:
        with open(PENDING_REVIEW_PATH, "w", encoding="utf-8") as f:
            json.dump({"items": items}, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"Failed to write pending review file: {e}")
        raise


# ==========================================
# Utility Functions
# ==========================================


def _clean_json_response(text: str) -> str:
    """Strip markdown code fences from a JSON string."""
    text = re.sub(r'```json', '', text)
    text = re.sub(r'```', '', text)
    return text.strip()


def _safe_float_convert(value: Any) -> float:
    """
    Safely convert a value to float.

    Args:
        value: Value to convert (string, number, or other).

    Returns:
        Float value, or 0.0 if conversion fails.
    """
    try:
        if isinstance(value, str):
            value = value.replace(',', '').strip()
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _initialize_pending_review_file() -> None:
    """Create the pending_review.json file if it does not exist."""
    if not PENDING_REVIEW_PATH.exists():
        try:
            PENDING_REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(PENDING_REVIEW_PATH, "w", encoding="utf-8") as f:
                json.dump({"items": []}, f, ensure_ascii=False, indent=2)
            logger.info(f"Initialized pending_review.json at {PENDING_REVIEW_PATH}")
        except OSError as e:
            logger.error(f"Failed to initialize pending_review.json: {e}")


# ==========================================
# Core Invoice Processing
# ==========================================


def process_invoice_from_file(file_path: str, original_filename: str) -> Dict[str, Any]:
    """
    Process a single invoice image/PDF file through the OCR+LLM pipeline.

    Args:
        file_path: Absolute path to the invoice file on disk.
        original_filename: Original filename to use in result dict.

    Returns:
        Result dictionary with the same fields as process_single_invoice:
            - filename, action, invoice_date, invoice_number, po_reference,
            - vendor_name, tax_id, subtotal, vat_amount, total_amount,
            - verification_status, remarks
        On error, returns a dict with verification_status describing the error
        and action set to "Reject".
    """
    # Load reference data
    database_po: Dict[str, Dict[str, Any]] = _load_po_data()
    paid_invoices: set = _load_paid_invoices()

    try:
        # Step 1: OCR
        logger.info(f"Running OCR on {file_path}")
        markdown_text = ocr_document(
            file_path,
            base_url=OCR_BASE_URL,
            api_key=API_KEY,
            model=OCR_MODEL,
            page_num=1,
        )

        # Step 2: LLM Extraction
        prompt = (
            "Return JSON only with exact keys: 'invoice_number', 'invoice_date' (YYYY-MM-DD format), "
            "'po_reference', 'tax_id', 'vendor_name', 'subtotal' (number), 'vat_amount' (number), "
            "'total_amount' (number). Text: " + markdown_text
        )

        client = _get_openai_client()
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=4096,
        )

        raw_json = _clean_json_response(response.choices[0].message.content)
        data = json.loads(raw_json)

        # Step 3: Verification (duplicate check + PO matching)
        inv_no = data.get("invoice_number", "")
        po_ref = data.get("po_reference")
        inv_amt = _safe_float_convert(data.get("total_amount", 0))

        status = "FAILED"
        default_action = "Hold"
        remarks = ""

        if inv_no in paid_invoices:
            status = "DUPLICATE_INVOICE"
            default_action = "Reject"
            remarks = "พบประวัติการจ่ายเงินบิลนี้แล้ว"
        elif po_ref in database_po:
            db_po = database_po[po_ref]
            if abs(inv_amt - _safe_float_convert(db_po.get("approved_amount", 0))) < 0.01:
                status = "MATCHED"
                default_action = "Approve"
            else:
                status = f"AMT_MISMATCH (PO approved: {db_po.get('approved_amount')})"
                default_action = "Hold"
                remarks = "ยอดเงินไม่ตรงกับ PO"
        else:
            status = "PO_NOT_FOUND"
            default_action = "Hold"
            remarks = "ไม่พบเลข PO ในระบบ"

        return {
            "filename": original_filename,
            "action": default_action,
            "invoice_date": data.get("invoice_date", ""),
            "invoice_number": inv_no,
            "po_reference": po_ref or "",
            "vendor_name": data.get("vendor_name", ""),
            "tax_id": data.get("tax_id", ""),
            "subtotal": _safe_float_convert(data.get("subtotal", 0)),
            "vat_amount": _safe_float_convert(data.get("vat_amount", 0)),
            "total_amount": inv_amt,
            "verification_status": status,
            "remarks": remarks,
        }

    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error during invoice processing: {e}")
        return {
            "filename": original_filename,
            "verification_status": f"JSON_PARSE_ERROR: {e}",
            "action": "Reject",
            "invoice_date": "",
            "invoice_number": "",
            "po_reference": "",
            "vendor_name": "",
            "tax_id": "",
            "subtotal": 0.0,
            "vat_amount": 0.0,
            "total_amount": 0.0,
            "remarks": "AI Processing Error",
        }

    except Exception as e:
        err_msg = str(e)
        logger.error(f"Invoice processing error for {file_path}: {err_msg}")
        if "429" in err_msg:
            return {
                "filename": original_filename,
                "verification_status": "RATE_LIMIT_ERROR",
                "action": "Reject",
                "invoice_date": "",
                "invoice_number": "",
                "po_reference": "",
                "vendor_name": "",
                "tax_id": "",
                "subtotal": 0.0,
                "vat_amount": 0.0,
                "total_amount": 0.0,
                "remarks": "Rate limit exceeded",
            }
        return {
            "filename": original_filename,
            "verification_status": f"PROCESSING_ERROR: {err_msg}",
            "action": "Reject",
            "invoice_date": "",
            "invoice_number": "",
            "po_reference": "",
            "vendor_name": "",
            "tax_id": "",
            "subtotal": 0.0,
            "vat_amount": 0.0,
            "total_amount": 0.0,
            "remarks": "AI Processing Error",
        }


# ==========================================
# Queue Operations
# ==========================================


def save_to_pending_review(result: Dict[str, Any], file_path: str) -> str:
    """
    Save an invoice processing result to the pending review queue.

    Args:
        result: The invoice processing result dict.
        file_path: Path to the invoice file.

    Returns:
        The generated item_id (UUID string) for the saved item.
    """
    items: List[Dict[str, Any]] = _load_pending_review()

    item_id = str(uuid.uuid4())

    item = {
        "item_id": item_id,
        "file_path": str(file_path),
        "filename": result.get("filename", ""),
        "action": result.get("action", "Hold"),
        "invoice_date": result.get("invoice_date", ""),
        "invoice_number": result.get("invoice_number", ""),
        "po_reference": result.get("po_reference", ""),
        "vendor_name": result.get("vendor_name", ""),
        "tax_id": result.get("tax_id", ""),
        "subtotal": result.get("subtotal", 0.0),
        "vat_amount": result.get("vat_amount", 0.0),
        "total_amount": result.get("total_amount", 0.0),
        "verification_status": result.get("verification_status", ""),
        "remarks": result.get("remarks", ""),
        "reviewed_by": "",
        "reviewed_at": "",
    }

    items.append(item)
    _save_pending_review(items)

    logger.info(f"Saved invoice to pending review: item_id={item_id}, invoice={item.get('invoice_number')}")
    return item_id


def move_to_approved(item_id: str, reviewed_by: str, remarks: str) -> bool:
    """
    Move an item from pending review to approved.

    Args:
        item_id: The UUID of the pending review item.
        reviewed_by: Name/ID of the reviewer approving.
        remarks: Optional reviewer remarks.

    Returns:
        True if item was found and updated, False otherwise.
    """
    items: List[Dict[str, Any]] = _load_pending_review()
    updated = False

    for item in items:
        if item.get("item_id") == item_id:
            item["action"] = "Approve"
            item["reviewed_by"] = reviewed_by
            item["remarks"] = remarks
            item["reviewed_at"] = ""
            updated = True
            break

    if not updated:
        logger.warning(f"move_to_approved: item_id {item_id} not found in pending review.")
        return False

    _save_pending_review(items)
    logger.info(f"Approved item: item_id={item_id}, by={reviewed_by}")
    return True


def move_to_rejected(item_id: str, reviewed_by: str, remarks: str) -> bool:
    """
    Move an item from pending review to rejected.

    Args:
        item_id: The UUID of the pending review item.
        reviewed_by: Name/ID of the reviewer rejecting.
        remarks: Reason for rejection.

    Returns:
        True if item was found and updated, False otherwise.
    """
    items: List[Dict[str, Any]] = _load_pending_review()
    updated = False

    for item in items:
        if item.get("item_id") == item_id:
            item["action"] = "Reject"
            item["reviewed_by"] = reviewed_by
            item["remarks"] = remarks
            item["reviewed_at"] = ""
            updated = True
            break

    if not updated:
        logger.warning(f"move_to_rejected: item_id {item_id} not found in pending review.")
        return False

    _save_pending_review(items)
    logger.info(f"Rejected item: item_id={item_id}, by={reviewed_by}")
    return True


def get_pending_count() -> int:
    """
    Get the number of items currently in the pending review queue.

    Returns:
        Count of pending review items.
    """
    items: List[Dict[str, Any]] = _load_pending_review()
    return len(items)


# ==========================================
# LINE Notifications
# ==========================================


def send_status_notification(result: Dict[str, Any]) -> bool:
    """
    Send a LINE notification based on the invoice processing result.

    Determines the appropriate message category from the result's
    verification_status and action fields, then sends via LINE.

    Args:
        result: Invoice processing result dict.

    Returns:
        True if notification was sent successfully, False otherwise.
    """
    status = result.get("verification_status", "")
    action = result.get("action", "Hold")
    invoice_number = result.get("invoice_number", "N/A")
    total_amount = result.get("total_amount", 0.0)
    vendor_name = result.get("vendor_name", "N/A")
    remarks = result.get("remarks", "")
    po_ref = result.get("po_reference", "")

    if status == "MATCHED" and action == "Approve":
        message = f"[APPROVED] Invoice {invoice_number} - {total_amount} THB - Vendor: {vendor_name}"
        category = "approval"
    elif status == "DUPLICATE_INVOICE" or action == "Reject":
        message = f"[REJECTED] Invoice {invoice_number} - {remarks or status}"
        category = "rejection"
    elif status in ("PO_NOT_FOUND", "AMT_MISMATCH") or action == "Hold":
        message = f"[ESCALATION] Invoice {invoice_number} - {remarks or status} - PO: {po_ref}"
        category = "escalation"
    elif "ERROR" in status or status == "RATE_LIMIT_ERROR":
        message = f"[SYSTEM ERROR] Invoice processing: {status} - {remarks}"
        category = "error"
    else:
        message = f"[UNKNOWN] Invoice {invoice_number} - {status}"
        category = "escalation"

    return send_line_notification(message, category)


# ==========================================
# LineOrchestrator Class
# ==========================================

class LineOrchestrator:
    """
    Orchestrator for processing invoice files received via LINE messages.
    Wraps the process_invoice_from_file function and adds LINE content download.
    """

    LINE_DATA_API_URL = "https://api-data.line.me/v2/bot/message/{message_id}/content"

    def __init__(self) -> None:
        """Initialize the LineOrchestrator."""
        pass

    def download_content(self, message_id: str, timeout: int = 30) -> bytes:
        """
        Download message content from LINE Data API.

        Args:
            message_id: LINE message ID
            timeout: Request timeout in seconds

        Returns:
            Raw bytes of the content

        Raises:
            requests.exceptions.RequestException: If download fails
            ValueError: If LINE_CHANNEL_ACCESS_TOKEN is not configured
        """
        import requests as req

        token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
        if not token:
            raise ValueError("LINE_CHANNEL_ACCESS_TOKEN not configured")

        url = self.LINE_DATA_API_URL.format(message_id=message_id)
        headers = {"Authorization": f"Bearer {token}"}

        response = req.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.content

    def process_invoice_from_line(
        self,
        message_id: str,
        original_filename: str,
        content_type: str,
    ) -> Dict[str, Any]:
        """
        Download LINE message content and process as an invoice.

        Args:
            message_id: LINE message ID
            original_filename: Original filename to use in result
            content_type: MIME type of the content (image/jpeg, image/png, application/pdf)

        Returns:
            Result dictionary from process_invoice_from_file
        """
        import tempfile
        import requests as req

        # Download content from LINE
        content = self.download_content(message_id)

        # Determine file extension from content type
        ext_map = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "application/pdf": ".pdf",
            "image/heic": ".heic",
        }
        ext = ext_map.get(content_type, ".bin")

        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            result = process_invoice_from_file(tmp_path, original_filename)
            send_status_notification(result)
            return result
        finally:
            # Clean up temp file
            try:
                os.remove(tmp_path)
            except OSError:
                pass


# ==========================================
# Module Initialization
# ==========================================

_initialize_pending_review_file()
