"""
Invoice Verification Swarm - Error Handler Agent
Manages failures, retries, and graceful error recovery.
"""

import time
import traceback
from typing import Dict, List, Any, Optional, Callable
from enum import Enum


class ErrorSeverity(Enum):
    LOW = "low"           # Minor issues, can continue
    MEDIUM = "medium"     # Significant issue, may retry
    HIGH = "high"         # Major failure, needs intervention
    CRITICAL = "critical"  # System-level failure, stop workflow


class ErrorHandler:
    """
    Centralized error handling for the Invoice Verification Swarm.
    Handles retries, fallback strategies, and error recovery.
    """

    def __init__(self, max_retries: int = 3, retry_delay: float = 5.0):
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        # Error tracking
        self.error_log = []
        self.error_counts = {}
        
        # Recovery strategies
        self._recovery_strategies = {
            "ocr_agent": self._ocr_recovery,
            "extraction_agent": self._extraction_recovery,
            "verification_agent": self._verification_recovery,
            "reporting_agent": self._reporting_recovery,
        }

    def handle_ocr_error(self, context: Dict, error_msg: str) -> Optional[Dict]:
        """Handle OCR-specific errors with recovery strategies."""
        invoice = context.get("invoice", {})
        
        # Strategy 1: Retry with adjusted parameters
        retry_count = self._get_retry_count("ocr_agent")
        if retry_count < self.max_retries:
            print(f"[ErrorHandler] Retrying OCR (attempt {retry_count + 1}/{self.max_retries})")
            time.sleep(self.retry_delay * (retry_count + 1))
            return {"retry_ocr": True, "attempt": retry_count + 1}
        
        # Strategy 2: Fallback to alternative OCR endpoint
        if "connection" in error_msg.lower() or "timeout" in error_msg.lower():
            print("[ErrorHandler] Falling back to local OCR endpoint")
            return {
                "fallback_ocr": True,
                "fallback_url": "http://localhost:11434/v1"
            }
        
        # Strategy 3: Skip and mark as failed
        print("[ErrorHandler] OCR failed after all retries")
        return {
            "status": "failed",
            "failed_step": "ocr_agent",
            "error": error_msg,
            "action": "mark_failed"
        }

    def handle_extraction_error(self, context: Dict, error_msg: str) -> Optional[Dict]:
        """Handle extraction-specific errors."""
        ocr_output = context.get("ocr_agent_output", {})
        ocr_text = ocr_output.get("text", "")
        
        # Strategy 1: Retry extraction
        retry_count = self._get_retry_count("extraction_agent")
        if retry_count < self.max_retries:
            print(f"[ErrorHandler] Retrying extraction (attempt {retry_count + 1}/{self.max_retries})")
            return {"retry_extraction": True, "attempt": retry_count + 1}
        
        # Strategy 2: Use partial OCR text if available
        if ocr_text and len(ocr_text) > 50:
            print("[ErrorHandler] Attempting partial extraction from OCR text")
            return {
                "partial_extraction": True,
                "ocr_text": ocr_text[:1000],  # Limit text
                "fallback_mode": True
            }
        
        return {
            "status": "failed",
            "failed_step": "extraction_agent",
            "error": error_msg,
            "action": "mark_failed"
        }

    def handle_verification_error(self, context: Dict, error_msg: str) -> Optional[Dict]:
        """Handle verification-specific errors."""
        extraction_output = context.get("extraction_agent_output", {})
        data = extraction_output.get("data", {})
        
        # Strategy 1: Retry with manual review flag
        retry_count = self._get_retry_count("verification_agent")
        if retry_count < self.max_retries:
            print(f"[ErrorHandler] Retrying verification (attempt {retry_count + 1}/{self.max_retries})")
            return {"retry_verification": True, "attempt": retry_count + 1}
        
        # Strategy 2: Flag for manual review instead of failing
        if data:
            print("[ErrorHandler] Flagging for manual review")
            return {
                "status": "manual_review_required",
                "verification_status": "MANUAL_REVIEW",
                "action": "Hold",
                "remarks": f"Auto-verification failed: {error_msg}",
                "original_data": data
            }
        
        return {
            "status": "failed",
            "failed_step": "verification_agent",
            "error": error_msg,
            "action": "mark_failed"
        }

    def handle_generic_error(self, context: Dict, error_msg: str) -> Optional[Dict]:
        """Handle any unrecognized errors."""
        print(f"[ErrorHandler] Generic error handler invoked: {error_msg}")
        
        # Log error and attempt graceful degradation
        self._log_error("generic", error_msg, context)
        
        return {
            "status": "degraded",
            "error": error_msg,
            "action": "continue_with_caution",
            "context_preserved": True
        }

    def handle_rate_limit_error(self, context: Dict, error_msg: str) -> Dict:
        """Special handler for rate limit (429) errors."""
        print("[ErrorHandler] Rate limit detected, implementing backoff strategy")
        
        return {
            "status": "rate_limited",
            "action": "wait_and_retry",
            "wait_seconds": 10,
            "error": error_msg
        }

    def _ocr_recovery(self, context: Dict) -> Optional[Dict]:
        """Recovery strategy for OCR failures."""
        return self.handle_ocr_error(context, "Recovery triggered")

    def _extraction_recovery(self, context: Dict) -> Optional[Dict]:
        """Recovery strategy for extraction failures."""
        return self.handle_extraction_error(context, "Recovery triggered")

    def _verification_recovery(self, context: Dict) -> Optional[Dict]:
        """Recovery strategy for verification failures."""
        return self.handle_verification_error(context, "Recovery triggered")

    def _reporting_recovery(self, context: Dict) -> Optional[Dict]:
        """Recovery strategy for reporting failures."""
        return {
            "status": "partial",
            "remarks": "Reporting failed but processing completed",
            "action": "generate_minimal_report"
        }

    def _get_retry_count(self, step: str) -> int:
        """Get current retry count for a step."""
        return self.error_counts.get(step, 0)

    def _increment_retry(self, step: str):
        """Increment retry count for a step."""
        self.error_counts[step] = self.error_counts.get(step, 0) + 1

    def _log_error(self, step: str, error_msg: str, context: Dict = None):
        """Log error to error tracking."""
        error_entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "step": step,
            "error": error_msg,
            "context_file": context.get("invoice", {}).get("file_name") if context else None
        }
        self.error_log.append(error_entry)
        self.error_counts[step] = self.error_counts.get(step, 0) + 1
        print(f"[ErrorHandler] Logged error: {step} - {error_msg}")

    def get_error_summary(self) -> Dict:
        """Return summary of all logged errors."""
        return {
            "total_errors": len(self.error_log),
            "error_counts": self.error_counts.copy(),
            "recent_errors": self.error_log[-5:] if len(self.error_log) > 5 else self.error_log
        }

    def reset(self):
        """Reset error tracking for new batch."""
        self.error_log = []
        self.error_counts = {}

    def execute_with_retry(self, func: Callable, step: str, *args, **kwargs) -> Any:
        """
        Execute a function with automatic retry logic.
        
        Args:
            func: Function to execute
            step: Step name for error tracking
            *args, **kwargs: Arguments to pass to function
            
        Returns:
            Function result or error dict
        """
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                result = func(*args, **kwargs)
                
                # Check if result indicates an error
                if isinstance(result, dict) and result.get("error"):
                    last_error = result["error"]
                    self._increment_retry(step)
                    print(f"[ErrorHandler] {step} attempt {attempt + 1} returned error: {last_error}")
                    time.sleep(self.retry_delay)
                    continue
                
                # Success
                return result
                
            except Exception as e:
                last_error = str(e)
                self._increment_retry(step)
                print(f"[ErrorHandler] {step} attempt {attempt + 1} raised exception: {last_error}")
                traceback.print_exc()
                
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                    continue
                else:
                    return {"error": last_error, "step": step}
        
        # All retries exhausted
        return {
            "error": f"All {self.max_retries} retries exhausted",
            "last_error": last_error,
            "step": step
        }