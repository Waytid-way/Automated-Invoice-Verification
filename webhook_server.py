"""
LINE Webhook Server for Automated Invoice Verification.
Receives LINE Messaging API webhook events and processes invoice images/PDFs.

Run with: python3 webhook_server.py
"""

import json
import logging
import os
import tempfile
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv
from flask import Flask, request

from line_notification import send_line_notification
from line_orchestrator import LineOrchestrator

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# LINE Group ID to filter messages
ALLOWED_GROUP_ID = "C68080abc2a2d63f1ae8a797c961cfd51"

# LINE API endpoints
LINE_REPLY_API_URL = "https://api.line.me/v2/bot/message/reply"
LINE_PUSH_API_URL = "https://api.line.me/v2/bot/message/push"

# Content type to file extension mapping
CONTENT_TYPE_TO_EXT: Dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
    "image/heic": ".heic",
}


def get_line_token() -> str:
    """Get LINE channel access token from environment."""
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        logger.error("LINE_CHANNEL_ACCESS_TOKEN not configured in .env")
    return token


def build_reply_headers() -> Dict[str, str]:
    """Build headers for LINE API calls."""
    return {
        "Authorization": f"Bearer {get_line_token()}",
        "Content-Type": "application/json",
    }


def send_reply(reply_token: str, messages: list, timeout: int = 30) -> bool:
    """
    Send a reply message via LINE Reply API.

    Args:
        reply_token: The reply token from the webhook event
        messages: List of message objects to send
        timeout: Request timeout in seconds

    Returns:
        True if reply sent successfully, False otherwise
    """
    payload = {"replyToken": reply_token, "messages": messages}
    try:
        response = requests.post(
            LINE_REPLY_API_URL,
            headers=build_reply_headers(),
            json=payload,
            timeout=timeout,
        )
        if response.status_code == 200:
            logger.info("Reply sent successfully")
            return True
        else:
            logger.warning(f"Reply failed with status {response.status_code}: {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Reply request failed: {e}")
        return False


def send_push(group_id: str, messages: list, timeout: int = 30) -> bool:
    """
    Send a push message to a LINE group via LINE Push API.

    Args:
        group_id: The group ID to send to
        messages: List of message objects to send
        timeout: Request timeout in seconds

    Returns:
        True if push sent successfully, False otherwise
    """
    payload = {"to": group_id, "messages": messages}
    try:
        response = requests.post(
            LINE_PUSH_API_URL,
            headers=build_reply_headers(),
            json=payload,
            timeout=timeout,
        )
        if response.status_code == 200:
            logger.info(f"Push sent successfully to group {group_id}")
            return True
        else:
            logger.warning(f"Push failed with status {response.status_code}: {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Push request failed: {e}")
        return False


def download_line_content(message_id: str, timeout: int = 30) -> bytes:
    """
    Download message content from LINE Data API.

    Args:
        message_id: LINE message ID
        timeout: Request timeout in seconds

    Returns:
        Raw bytes of the content

    Raises:
        ValueError: If LINE_CHANNEL_ACCESS_TOKEN is not configured
        requests.exceptions.RequestException: If download fails
    """
    token = get_line_token()
    if not token:
        raise ValueError("LINE_CHANNEL_ACCESS_TOKEN not configured")

    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.content


def save_temp_file(content: bytes, content_type: str) -> tuple:
    """
    Save content to a temporary file and return (path, original_filename).

    Args:
        content: Raw bytes of the file
        content_type: MIME type of the content

    Returns:
        Tuple of (file_path, original_filename)
    """
    ext = CONTENT_TYPE_TO_EXT.get(content_type, ".bin")
    timestamp = tempfile.mktemp(suffix="")[-(8):]
    original_filename = f"invoice_{timestamp}{ext}"

    fd, tmp_path = tempfile.mkstemp(suffix=ext)
    try:
        os.write(fd, content)
    finally:
        os.close(fd)

    return tmp_path, original_filename


def cleanup_temp_file(file_path: str) -> None:
    """
    Remove a temporary file if it exists.

    Args:
        file_path: Path to the temporary file
    """
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
    except OSError as e:
        logger.warning(f"Failed to remove temp file {file_path}: {e}")


def handle_image_message(event: Dict[str, Any], orchestrator: LineOrchestrator) -> None:
    """
    Handle an image message event from LINE.

    Downloads the image, processes it through the orchestrator, and sends
    a notification to the group.

    Args:
        event: The LINE webhook event dictionary
        orchestrator: The LineOrchestrator instance
    """
    message_id = event.get("message", {}).get("id", "")
    reply_token = event.get("replyToken", "")

    if not message_id:
        logger.error("Image message has no message ID")
        return

    logger.info(f"Processing image message: {message_id}")
    send_reply(reply_token, [{"type": "text", "text": "Processing your invoice image..."}])

    try:
        content_type = "image/jpeg"  # Default, LINE Data API returns content type in headers
        content = download_line_content(message_id)

        tmp_path, original_filename = save_temp_file(content, content_type)

        try:
            result = orchestrator.process_invoice_from_line(
                message_id=message_id,
                original_filename=original_filename,
                content_type=content_type,
            )
            logger.info(f"Image processing result: {result.get('verification_status')}")
        finally:
            cleanup_temp_file(tmp_path)

    except Exception as e:
        logger.error(f"Failed to process image message: {e}")
        send_reply(reply_token, [{"type": "text", "text": f"Error processing image: {str(e)}"}])


def handle_file_message(event: Dict[str, Any], orchestrator: LineOrchestrator) -> None:
    """
    Handle a file message event from LINE.

    Downloads the file, processes it through the orchestrator, and sends
    a notification to the group.

    Args:
        event: The LINE webhook event dictionary
        orchestrator: The LineOrchestrator instance
    """
    message_id = event.get("message", {}).get("id", "")
    reply_token = event.get("replyToken", "")
    file_name = event.get("message", {}).get("fileName", "unknown.file")

    if not message_id:
        logger.error("File message has no message ID")
        return

    logger.info(f"Processing file message: {file_name} ({message_id})")
    send_reply(reply_token, [{"type": "text", "text": f"Processing your file: {file_name}..."}])

    try:
        content = download_line_content(message_id)

        # Determine content type from file extension
        ext = os.path.splitext(file_name)[1].lower()
        content_type_map = {
            ".pdf": "application/pdf",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
        }
        content_type = content_type_map.get(ext, "application/octet-stream")

        tmp_path, original_filename = save_temp_file(content, content_type)

        try:
            result = orchestrator.process_invoice_from_line(
                message_id=message_id,
                original_filename=original_filename,
                content_type=content_type,
            )
            logger.info(f"File processing result: {result.get('verification_status')}")
        finally:
            cleanup_temp_file(tmp_path)

    except Exception as e:
        logger.error(f"Failed to process file message: {e}")
        send_reply(reply_token, [{"type": "text", "text": f"Error processing file: {str(e)}"}])


def handle_text_message(event: Dict[str, Any]) -> None:
    """
    Handle a text message event from LINE.

    Processes commands (/status, /help) or echoes the message.

    Args:
        event: The LINE webhook event dictionary
    """
    message_text = event.get("message", {}).get("text", "").strip()
    reply_token = event.get("replyToken", "")
    user_id = event.get("source", {}).get("userId", "unknown")

    logger.info(f"Text message from {user_id}: {message_text}")

    if message_text.startswith("/status"):
        reply_text = "Invoice Verification System is running. Send an image or PDF to process."
        send_reply(reply_token, [{"type": "text", "text": reply_text}])

    elif message_text.startswith("/help"):
        help_text = (
            "Invoice Verification Bot Commands:\n"
            "/status - Check system status\n"
            "/help - Show this help message\n"
            "Send an image (JPG/PNG) or PDF of an invoice to process."
        )
        send_reply(reply_token, [{"type": "text", "text": help_text}])

    else:
        # Echo the message
        echo_text = f"You said: {message_text}"
        send_reply(reply_token, [{"type": "text", "text": echo_text}])


def process_event(event: Dict[str, Any], orchestrator: LineOrchestrator) -> None:
    """
    Process a single LINE webhook event.

    Args:
        event: The LINE webhook event dictionary
        orchestrator: The LineOrchestrator instance
    """
    event_type = event.get("type", "")
    source = event.get("source", {})
    source_type = source.get("type", "")

    # Filter: only process group messages
    if source_type != "group":
        logger.debug(f"Ignoring non-group message type: {source_type}")
        return

    group_id = source.get("groupId", "")
    if group_id != ALLOWED_GROUP_ID:
        logger.warning(f"Ignoring message from unauthorized group: {group_id}")
        return

    logger.info(f"Processing {event_type} event from group {group_id}")

    if event_type == "message":
        message = event.get("message", {})
        message_type = message.get("type", "")

        if message_type == "image":
            handle_image_message(event, orchestrator)
        elif message_type == "file":
            handle_file_message(event, orchestrator)
        elif message_type == "text":
            handle_text_message(event)
        else:
            logger.info(f"Ignoring unsupported message type: {message_type}")

    elif event_type == "postback":
        logger.info("Postback event received (not currently handled)")
    elif event_type == "join":
        logger.info("Bot joined a group")
        send_push(
            group_id,
            [{"type": "text", "text": "Invoice Verification Bot is now connected!"}],
        )
    elif event_type == "leave":
        logger.info("Bot left a group")
    else:
        logger.debug(f"Ignoring unhandled event type: {event_type}")


@app.route("/webhook", methods=["POST"])
def webhook() -> tuple:
    """
    Main webhook endpoint for LINE Messaging API.

    Receives webhook events, processes them, and always returns 200
    to prevent LINE from sending retry requests.
    """
    try:
        body = request.json
        logger.info(f"Webhook received: {json.dumps(body, ensure_ascii=False, indent=2)}")
    except Exception as e:
        logger.error(f"Failed to parse webhook body: {e}")
        return "OK", 200

    if not body or "events" not in body:
        logger.info("No events in webhook body")
        return "OK", 200

    orchestrator = LineOrchestrator()
    events = body.get("events", [])

    logger.info(f"Processing {len(events)} event(s)")

    for event in events:
        try:
            process_event(event, orchestrator)
        except Exception as e:
            logger.error(f"Error processing event: {e}")

    # Always return 200 to LINE to prevent retry storms
    return "OK", 200


@app.route("/", methods=["GET"])
def verify() -> tuple:
    """
    Verification endpoint for LINE webhook setup.

    Returns a success message if LINE_CHANNEL_ACCESS_TOKEN is configured.
    """
    token = get_line_token()
    if not token:
        return "LINE_CHANNEL_ACCESS_TOKEN not configured", 400
    return f"Webhook server is running. Token: {token[:10]}...", 200


if __name__ == "__main__":
    print("Starting LINE Webhook Server on port 5000...")
    print(f"Configured to filter group ID: {ALLOWED_GROUP_ID}")
    print("Configure this URL in LINE Developers Console:")
    print("  https://YOUR_NGROK_URL/")
    app.run(host="0.0.0.0", port=5000, debug=False)
