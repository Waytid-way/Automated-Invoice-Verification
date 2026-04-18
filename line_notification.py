"""
LINE Group Push Notification for Automated Invoice Verification Agent.
Sends formatted notifications to LINE Group via Messaging API.
"""

import os
import time
import logging
from typing import Dict, Optional

import requests

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

LINE_API_URL = "https://api.line.me/v2/bot/message/push"
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_GROUP_ID = os.getenv("LINE_GROUP_ID", "")

# Message templates
MESSAGE_TEMPLATES = {
    "approval": "✅ [APPROVED] Invoice {invoice_number} — {total_amount} THB — Vendor: {vendor}",
    "escalation": "⚠️ [ESCALATION] Invoice {invoice_number} — {reason} — PO: {po_reference}",
    "rejection": "❌ [REJECTED] Invoice {invoice_number} — {reason}",
    "error": "🔴 [SYSTEM ERROR] {module}: {message}",
    "summary": "📊 [DAILY SUMMARY] Processed: {processed} — Approved: {approved} — Escalated: {escalated} — Rejected: {rejected}",
}


def format_invoice_message(result: Dict, category: str) -> str:
    """
    Format an invoice result dict into a human-readable LINE message.

    Args:
        result: Dict containing invoice processing result fields
        category: One of 'approval', 'escalation', 'rejection', 'error', 'summary'

    Returns:
        Formatted message string
    """
    template = MESSAGE_TEMPLATES.get(category, "{invoice_number}")

    if category == "approval":
        return template.format(
            invoice_number=result.get("invoice_number", "N/A"),
            total_amount=result.get("total_amount", "N/A"),
            vendor=result.get("vendor_name", result.get("vendor", "N/A")),
        )

    elif category == "escalation":
        return template.format(
            invoice_number=result.get("invoice_number", "N/A"),
            reason=result.get("reason", result.get("remarks", result.get("verification_status", "N/A"))),
            po_reference=result.get("po_reference", "N/A"),
        )

    elif category == "rejection":
        return template.format(
            invoice_number=result.get("invoice_number", "N/A"),
            reason=result.get("reason", result.get("remarks", result.get("verification_status", "N/A"))),
        )

    elif category == "error":
        return template.format(
            module=result.get("module", "unknown"),
            message=result.get("message", str(result.get("error", "Unknown error"))),
        )

    elif category == "summary":
        return template.format(
            processed=result.get("processed", 0),
            approved=result.get("approved", 0),
            escalated=result.get("escalated", 0),
            rejected=result.get("rejected", 0),
        )

    return str(result)


def send_line_notification(message: str, category: str) -> bool:
    """
    Send a notification message to the LINE Group.

    Args:
        message: The formatted message text to send
        category: Category label for logging purposes

    Returns:
        True if notification sent successfully, False otherwise
    """
    token = LINE_CHANNEL_ACCESS_TOKEN
    group_id = LINE_GROUP_ID

    if not token or not group_id:
        logger.warning(f"[LINE] Credentials missing (token={'set' if token else 'missing'}, group_id={'set' if group_id else 'missing'}). Skipping {category} notification.")
        return False

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = {
        "to": group_id,
        "messages": [
            {
                "type": "text",
                "text": message,
            }
        ],
    }

    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                LINE_API_URL,
                headers=headers,
                json=payload,
                timeout=30,
            )

            if response.status_code == 200:
                logger.info(f"[LINE] {category} notification sent successfully.")
                return True

            elif response.status_code == 429:
                # Rate limited — exponential backoff
                wait_time = 2 ** attempt
                logger.warning(f"[LINE] Rate limited (429). Attempt {attempt}/{max_attempts}. Waiting {wait_time}s before retry.")
                time.sleep(wait_time)
                continue

            elif 500 <= response.status_code < 600:
                # Server error — exponential backoff
                wait_time = 2 ** attempt
                logger.warning(f"[LINE] Server error ({response.status_code}). Attempt {attempt}/{max_attempts}. Waiting {wait_time}s before retry.")
                time.sleep(wait_time)
                continue

            else:
                # Other errors — log and fail
                logger.error(f"[LINE] API error {response.status_code}: {response.text}")
                return False

        except requests.exceptions.Timeout:
            logger.warning(f"[LINE] Request timeout. Attempt {attempt}/{max_attempts}.")
            if attempt < max_attempts:
                time.sleep(2 ** attempt)
                continue
            return False

        except requests.exceptions.RequestException as e:
            logger.error(f"[LINE] Request failed: {e}")
            return False

    logger.error(f"[LINE] Failed after {max_attempts} attempts.")
    return False
