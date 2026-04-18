"""Tests for error_handler.py in Automated-Invoice-Verification.

Covers:
  (1) retry on OCR failure
  (2) fallback on LLM failure
  (3) dead letter handling (messages that exceed retries are marked failed)
"""

import sys
import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
AIV_ROOT = PROJECT_ROOT  # error_handler.py is directly in the project root

# error_handler.py lives in Automated-Invoice-Verification/ which has a hyphen
# and cannot be imported as a Python package normally. Use importlib directly.
_eh_spec = importlib.util.spec_from_file_location(
    "error_handler", AIV_ROOT / "error_handler.py"
)
_eh_mod = importlib.util.module_from_spec(_eh_spec)
_eh_spec.loader.exec_module(_eh_mod)  # populates _eh_mod.ErrorHandler etc.

ErrorHandler = _eh_mod.ErrorHandler
ErrorSeverity = _eh_mod.ErrorSeverity


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def eh():
    """Fresh ErrorHandler instance for each test."""
    return ErrorHandler(max_retries=3, retry_delay=0.01)


# ---------------------------------------------------------------------------
# (1) RETRY on OCR failure
# ---------------------------------------------------------------------------

class TestOCRRetry:
    """Verify retry logic when OCR fails."""

    def test_retry_on_ocr_failure_first_attempt(self, eh):
        """First failure should trigger a retry, not a final failure."""
        ctx = {"invoice": {"file_name": "test.pdf"}}
        result = eh.handle_ocr_error(ctx, "connection refused")
        # Should ask to retry
        assert result is not None
        assert result.get("retry_ocr") is True
        assert result.get("attempt") == 1

    def test_retry_count_increments_via_execute_with_retry(self, eh):
        """execute_with_retry increments the retry counter on each failure."""
        call_count = 0

        def failing_func():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("persistent failure")

        # execute_with_retry calls _increment_retry each time it catches an error
        eh.execute_with_retry(failing_func, "ocr_agent")

        # After exhausting retries, verify the counter was incremented each attempt
        assert eh._get_retry_count("ocr_agent") == eh.max_retries

    def test_execute_with_retry_retries_on_exception(self, eh):
        """execute_with_retry should retry when func raises."""
        call_count = 0

        def failing_func():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("OCR unavailable")

        result = eh.execute_with_retry(failing_func, "ocr_agent")
        # Should have retried max_retries times
        assert call_count == eh.max_retries
        assert result.get("error") is not None
        assert result.get("step") == "ocr_agent"

    def test_execute_with_retry_retries_on_error_dict(self, eh):
        """execute_with_retry retries when func returns an error dict."""
        call_count = 0

        def error_dict_func():
            nonlocal call_count
            call_count += 1
            return {"error": "LLM timeout"}

        result = eh.execute_with_retry(error_dict_func, "llm_agent")
        assert call_count == eh.max_retries
        assert "error" in result

    def test_execute_with_retry_succeeds_on_valid_result(self, eh):
        """execute_with_retry returns immediately on success."""
        call_count = 0

        def success_func():
            nonlocal call_count
            call_count += 1
            return {"data": "ok"}

        result = eh.execute_with_retry(success_func, "ocr_agent")
        assert call_count == 1
        assert result == {"data": "ok"}

    def test_execute_with_retry_backoff_delay(self, eh):
        """execute_with_retry applies retry_delay between attempts."""
        import time
        eh.retry_delay = 0.05
        call_count = 0

        def failing_func():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("fail")

        start = time.time()
        eh.execute_with_retry(failing_func, "ocr_agent")
        elapsed = time.time() - start
        # Should have waited at least (max_retries - 1) * retry_delay
        assert elapsed >= (eh.max_retries - 1) * eh.retry_delay


# ---------------------------------------------------------------------------
# (2) FALLBACK on LLM failure
# ---------------------------------------------------------------------------

class TestLLMFallback:
    """Verify fallback strategy when LLM extraction fails."""

    def test_extraction_fallback_to_partial_ocr(self, eh):
        """When extraction retries are exhausted and partial OCR text exists, use partial."""
        # Set retry count to max so the handler skips the retry branch
        # and goes straight to the fallback branch
        eh._increment_retry("extraction_agent")
        eh._increment_retry("extraction_agent")
        eh._increment_retry("extraction_agent")  # now at max_retries

        ctx = {
            "ocr_agent_output": {
                "text": "Invoice #123 Total: $500 Date: 2024-01-01 vendor: Acme Corp"
            }
        }
        result = eh.handle_extraction_error(ctx, "LLM parse error")
        assert result is not None
        assert result.get("partial_extraction") is True
        assert result.get("fallback_mode") is True
        # Should have preserved OCR text
        assert "Invoice" in result.get("ocr_text", "")

    def test_extraction_fails_gracefully_when_no_ocr_text(self, eh):
        """When extraction retries exhausted with no OCR fallback, mark as failed."""
        # Exhaust retries
        for _ in range(eh.max_retries):
            eh._increment_retry("extraction_agent")

        ctx = {"ocr_agent_output": {"text": ""}}
        result = eh.handle_extraction_error(ctx, "LLM unreachable")
        assert result is not None
        assert result.get("status") == "failed"
        assert result.get("failed_step") == "extraction_agent"

    def test_ocr_error_fallback_to_local_endpoint(self, eh):
        """OCR connection/timeout errors that exhaust retries trigger local OCR fallback."""
        # Exhaust retries so we skip the retry branch
        for _ in range(eh.max_retries):
            eh._increment_retry("ocr_agent")

        ctx = {"invoice": {"file_name": "test.pdf"}}
        result = eh.handle_ocr_error(ctx, "connection timeout")
        assert result is not None
        assert result.get("fallback_ocr") is True
        assert "localhost" in result.get("fallback_url", "")

    def test_verification_error_flags_manual_review(self, eh):
        """Verification retries exhausted with partial data flags for manual review."""
        # Exhaust retries
        for _ in range(eh.max_retries):
            eh._increment_retry("verification_agent")

        ctx = {
            "extraction_agent_output": {
                "data": {"invoice_number": "INV-001", "total": 100.0}
            }
        }
        result = eh.handle_verification_error(ctx, "model confidence too low")
        assert result is not None
        assert result.get("status") == "manual_review_required"
        assert result.get("verification_status") == "MANUAL_REVIEW"

    def test_ocr_error_non_connection_timeout_after_retries(self, eh):
        """OCR error for non-connection issues after retries exhausted marks as failed."""
        # Exhaust retries
        for _ in range(eh.max_retries):
            eh._increment_retry("ocr_agent")

        ctx = {"invoice": {"file_name": "test.pdf"}}
        # Non-connection, non-timeout error
        result = eh.handle_ocr_error(ctx, "corrupt image data")
        assert result is not None
        assert result.get("status") == "failed"
        assert result.get("failed_step") == "ocr_agent"
        assert result.get("action") == "mark_failed"


# ---------------------------------------------------------------------------
# (3) DEAD LETTER handling
# ---------------------------------------------------------------------------

class TestDeadLetterHandling:
    """Verify messages that exhaust retries are sent to dead-letter queue."""

    def test_ocr_error_all_retries_exhausted_marks_failed(self, eh):
        """After max_retries, OCR error is marked as dead/failed."""
        ctx = {"invoice": {"file_name": "test.pdf"}}
        # Simulate state after execute_with_retry has exhausted retries:
        # inject the counter state as if retries were already counted
        for _ in range(eh.max_retries):
            eh._increment_retry("ocr_agent")
        # Now any new failure should be dead-lettered
        result = eh.handle_ocr_error(ctx, "still failing after all retries")
        assert result is not None
        assert result.get("status") == "failed"
        assert result.get("action") == "mark_failed"

    def test_error_counts_tracked_per_step_via_increment(self, eh):
        """Each agent step maintains its own retry counter via _increment_retry."""
        # Manually increment counters to simulate past failures
        eh._increment_retry("ocr_agent")
        eh._increment_retry("ocr_agent")
        eh._increment_retry("extraction_agent")

        assert eh._get_retry_count("ocr_agent") == 2
        assert eh._get_retry_count("extraction_agent") == 1
        assert eh._get_retry_count("verification_agent") == 0

    def test_generic_error_logs_and_returns_degraded_status(self, eh):
        """handle_generic_error logs to error_log and returns degraded status."""
        ctx = {"invoice": {"file_name": "unknown.pdf"}}
        result = eh.handle_generic_error(ctx, "unknown error occurred")
        assert result is not None
        assert result.get("status") == "degraded"
        assert result.get("action") == "continue_with_caution"
        # generic error path should have logged it
        summary = eh.get_error_summary()
        assert summary.get("total_errors") > 0

    def test_error_log_after_generic_failure(self, eh):
        """After a generic error, error_log contains the entry."""
        ctx = {"invoice": {}}
        eh.handle_generic_error(ctx, "something went wrong")
        summary = eh.get_error_summary()
        assert summary.get("total_errors") == 1
        assert summary.get("error_counts", {}).get("generic") == 1

    def test_reset_clears_dead_letter_state(self, eh):
        """reset() clears error counts and log, simulating a new batch."""
        eh._increment_retry("ocr_agent")
        eh._increment_retry("ocr_agent")
        eh.handle_generic_error({"invoice": {}}, "dummy")
        eh.reset()
        summary = eh.get_error_summary()
        assert summary.get("total_errors") == 0
        assert summary.get("error_counts") == {}

    def test_rate_limit_error_returns_backoff(self, eh):
        """Rate limit errors return a wait-and-retry response."""
        ctx = {"invoice": {}}
        result = eh.handle_rate_limit_error(ctx, "429 Too Many Requests")
        assert result is not None
        assert result.get("status") == "rate_limited"
        assert result.get("action") == "wait_and_retry"
        assert result.get("wait_seconds") == 10

    def test_dead_letter_state_reflects_multiple_agent_failures(self, eh):
        """Dead letter queue state tracks multiple failed agents."""
        eh._increment_retry("ocr_agent")
        eh._increment_retry("ocr_agent")
        eh._increment_retry("extraction_agent")
        eh.handle_generic_error({"invoice": {}}, "multi-agent failure")

        summary = eh.get_error_summary()
        assert summary.get("error_counts", {}).get("ocr_agent") == 2
        assert summary.get("error_counts", {}).get("extraction_agent") == 1
        assert summary.get("error_counts", {}).get("generic") == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
