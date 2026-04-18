"""
Invoice Verification Swarm - Orchestrator Agent
Coordinates all agent handoffs and workflow execution.
"""

import time
import json
import logging
from typing import Dict, List, Any, Optional
from enum import Enum

from line_notification import send_line_notification, format_invoice_message

logger = logging.getLogger(__name__)


def compute_thai_vat(subtotal: float, total_amount: float) -> Optional[float]:
    """
    Compute Thai VAT (7%) when LLM returns vat_amount=0.
    
    VAT = round(subtotal / 1.07 * 0.07, 2)
    Only returns VAT if total_amount matches subtotal + computed_vat.
    
    Args:
        subtotal: The subtotal amount from invoice
        total_amount: The total amount from invoice
        
    Returns:
        Computed VAT amount if valid, None otherwise
    """
    if subtotal <= 0:
        return None
    
    computed_vat = round(subtotal / 1.07 * 0.07, 2)
    expected_total = round(subtotal + computed_vat, 2)
    
    # Allow small floating point tolerance (0.02)
    if abs(expected_total - total_amount) <= 0.02:
        return computed_vat
    
    return None


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRY = "retry"


class OrchestratorAgent:
    """
    Main orchestrator for the Invoice Verification Swarm.
    Coordinates workflow between OCR, Extraction, Verification, and Reporting agents.
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.max_retries = self.config.get("max_retries", 3)
        self.retry_delay = self.config.get("retry_delay", 5)
        
        # Workflow state
        self.workflow_state = {
            "invoices_processed": 0,
            "invoices_succeeded": 0,
            "invoices_failed": 0,
            "total_invoices": 0,
        }
        
        # Agent registry
        self.agents = {}
        self._register_default_agents()

    def _register_default_agents(self):
        """Register default agent handlers."""
        self.agents = {
            "ocr_agent": self._handle_ocr,
            "extraction_agent": self._handle_extraction,
            "verification_agent": self._handle_verification,
            "reporting_agent": self._handle_reporting,
        }

    def register_agent(self, name: str, handler):
        """Register a custom agent handler."""
        self.agents[name] = handler

    def run_workflow(self, invoices: List[Dict]) -> Dict[str, Any]:
        """
        Execute the full invoice verification workflow.
        
        Args:
            invoices: List of invoice data dicts with 'file_path' and 'file_name'
            
        Returns:
            Dict with workflow results summary
        """
        self.workflow_state["total_invoices"] = len(invoices)
        results = []
        
        for idx, invoice in enumerate(invoices):
            print(f"\n[Orchestrator] Processing invoice {idx + 1}/{len(invoices)}: {invoice.get('file_name', 'unknown')}")
            
            try:
                result = self._process_invoice_pipeline(invoice)
                results.append(result)

                if result.get("status") == "success":
                    self.workflow_state["invoices_succeeded"] += 1
                else:
                    self.workflow_state["invoices_failed"] += 1

                # --- LINE Group Notifications (non-blocking) ---
                try:
                    status = result.get("status")
                    action = result.get("action", "")
                    verification_status = result.get("verification_status", "")

                    if status == "success" and action == "Approve":
                        send_line_notification(format_invoice_message(result, "approval"), "approval")
                    elif verification_status in ("PO_NOT_FOUND", "AMOUNT_MISMATCH"):
                        send_line_notification(format_invoice_message(result, "escalation"), "escalation")
                    elif verification_status == "DUPLICATE_INVOICE" or action == "Reject":
                        send_line_notification(format_invoice_message(result, "rejection"), "rejection")
                except Exception as e:
                    logger.warning(f"[Orchestrator] LINE notification error: {e}")

            except Exception as e:
                print(f"[Orchestrator] Pipeline error for {invoice.get('file_name')}: {e}")
                # --- LINE error notification (non-blocking) ---
                try:
                    send_line_notification(
                        format_invoice_message(
                            {"invoice_number": "OCR/LLM", "module": "orchestrator", "message": str(e)},
                            "error"
                        ),
                        "error"
                    )
                except Exception as line_err:
                    logger.warning(f"[Orchestrator] LINE error notification failed: {line_err}")

                results.append({
                    "file_name": invoice.get("file_name"),
                    "status": "failed",
                    "error": str(e)
                })
                self.workflow_state["invoices_failed"] += 1
                
            self.workflow_state["invoices_processed"] += 1
        
        return {
            "workflow_summary": self.workflow_state.copy(),
            "results": results,
            "success_rate": (
                self.workflow_state["invoices_succeeded"] / 
                max(self.workflow_state["invoices_processed"], 1)
            ) * 100
        }

    def _process_invoice_pipeline(self, invoice: Dict) -> Dict[str, Any]:
        """
        Execute the full pipeline for a single invoice.
        Pipeline: OCR → Extraction → Verification → Reporting
        """
        pipeline_steps = [
            ("ocr_agent", invoice),
            ("extraction_agent", None),  # Depends on OCR output
            ("verification_agent", None),  # Depends on Extraction output
            ("reporting_agent", None),  # Depends on Verification output
        ]
        
        context = {"invoice": invoice, "errors": []}
        
        for step_name, input_data in pipeline_steps:
            agent_handler = self.agents.get(step_name)
            if not agent_handler:
                raise ValueError(f"Unknown agent: {step_name}")
            
            print(f"  [Pipeline] Executing {step_name}...")
            
            try:
                step_output = agent_handler(context)
                context[f"{step_name}_output"] = step_output
                
                # Check for step-level errors
                if step_output.get("error"):
                    context["errors"].append({
                        "step": step_name,
                        "error": step_output["error"]
                    })
                    
            except Exception as e:
                print(f"  [Pipeline] {step_name} failed: {e}")
                context["errors"].append({
                    "step": step_name,
                    "error": str(e)
                })
                # Continue to error handler for recovery attempt
                error_result = self._handle_error(context.copy())
                if error_result:
                    return error_result
                raise
        
        return {
            "file_name": invoice.get("file_name"),
            "status": "success",
            "action": verification.get("action"),
            "verification_status": verification.get("verification_status"),
            "extracted_data": context.get("extraction_agent_output", {}),
            "verification_result": context.get("verification_agent_output", {}),
            "report": context.get("reporting_agent_output", {}),
            "errors": context.get("errors", []),
            # Flattened fields for LINE notification convenience
            "invoice_number": data.get("invoice_number"),
            "total_amount": data.get("total_amount"),
            "vendor_name": data.get("vendor_name"),
            "po_reference": data.get("po_reference"),
            "reason": verification.get("remarks"),
        }

    def _handle_ocr(self, context: Dict) -> Dict:
        """OCR Agent - Extract text from invoice image."""
        invoice = context.get("invoice", {})
        file_path = invoice.get("file_path")
        
        if not file_path:
            return {"error": "No file_path provided for OCR", "text": None}
        
        # Call OCR function from typhoon_ocr
        try:
            from typhoon_ocr import ocr_document
            import os
            
            api_key = os.getenv("TYHOON_API_KEY", "")
            ocr_text = ocr_document(
                file_path,
                base_url=self.config.get("ocr_base_url", "https://api.opentyphoon.ai/v1"),
                api_key=api_key,
                model=self.config.get("ocr_model", "typhoon-ocr"),
                page_num=1
            )
            
            return {"text": ocr_text, "error": None}
            
        except Exception as e:
            return {"text": None, "error": str(e)}

    def _handle_extraction(self, context: Dict) -> Dict:
        """Extraction Agent - Parse OCR text into structured data."""
        ocr_output = context.get("ocr_agent_output", {})
        ocr_text = ocr_output.get("text", "")
        
        if not ocr_text:
            return {"data": None, "error": "No OCR text to extract from"}
        
        try:
            from openai import OpenAI
            import os
            
            client = OpenAI(
                api_key=os.getenv("TYHOON_API_KEY", ""),
                base_url=self.config.get("llm_base_url", "https://api.opentyphoon.ai/v1")
            )
            
            prompt = f"""Return JSON only with exact keys: 'invoice_number', 'invoice_date' (YYYY-MM-DD format), 
'po_reference', 'tax_id', 'vendor_name', 'subtotal' (number), 'vat_amount' (number), 'total_amount' (number). 
Text: {ocr_text}"""
            
            response = client.chat.completions.create(
                model=self.config.get("llm_model", "typhoon-v2.5-30b-a3b-instruct"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=4096
            )
            
            raw_json = response.choices[0].message.content
            # Clean markdown code blocks
            raw_json = raw_json.replace("```json", "").replace("```", "").strip()
            data = json.loads(raw_json)
            
            # Post-process: fix VAT if LLM returned 0 but subtotal > 0 (Thai VAT 7%)
            if data.get("vat_amount", 0) == 0 and data.get("subtotal", 0) > 0:
                computed_vat = compute_thai_vat(
                    float(data.get("subtotal", 0)),
                    float(data.get("total_amount", 0))
                )
                if computed_vat is not None:
                    data["vat_amount"] = computed_vat
            
            return {"data": data, "error": None}
            
        except Exception as e:
            return {"data": None, "error": f"Extraction failed: {str(e)}"}

    def _handle_verification(self, context: Dict) -> Dict:
        """Verification Agent - Check against PO database and detect duplicates."""
        extraction_output = context.get("extraction_agent_output", {})
        data = extraction_output.get("data", {})
        
        if not data:
            return {"verification_status": "failed", "error": "No data to verify"}
        
        # Get config
        database_po = self.config.get("database_po", {})
        paid_invoices = self.config.get("paid_invoices", set())
        
        inv_no = data.get("invoice_number", "")
        po_ref = data.get("po_reference")
        inv_amt = self._safe_float(data.get("total_amount", 0))
        
        status = "FAILED"
        action = "Pending"
        remarks = ""
        
        # Duplicate check
        if inv_no in paid_invoices:
            status = "DUPLICATE_INVOICE"
            action = "Reject"
            remarks = "Invoice already paid previously"
        # PO Matching check
        elif po_ref in database_po:
            db_po = database_po[po_ref]
            if abs(inv_amt - db_po.get("approved_amount", 0)) < 0.01:
                status = "MATCHED"
                action = "Approve"
            else:
                status = f"AMOUNT_MISMATCH (PO: {db_po['approved_amount']})"
                action = "Hold"
                remarks = "Invoice amount does not match PO"
        else:
            status = "PO_NOT_FOUND"
            action = "Hold"
            remarks = "PO reference not found in system"
        
        return {
            "verification_status": status,
            "action": action,
            "remarks": remarks,
            "invoice_data": data,
            "error": None
        }

    def _handle_reporting(self, context: Dict) -> Dict:
        """Reporting Agent - Generate final verification report."""
        verification = context.get("verification_agent_output", {})
        
        return {
            "final_status": verification.get("verification_status", "UNKNOWN"),
            "action_recommended": verification.get("action", "Hold"),
            "remarks": verification.get("remarks", ""),
            "processed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "error": None
        }

    def _handle_error(self, context: Dict) -> Optional[Dict]:
        """Error handler - attempt recovery or graceful failure."""
        from error_handler import ErrorHandler
        
        error_handler = ErrorHandler(
            max_retries=self.max_retries,
            retry_delay=self.retry_delay
        )
        
        errors = context.get("errors", [])
        if not errors:
            return None
        
        last_error = errors[-1]
        step = last_error.get("step")
        error_msg = last_error.get("error")
        
        print(f"[Orchestrator] Handling error at {step}: {error_msg}")
        
        # Attempt recovery based on which step failed
        if step == "ocr_agent":
            recovery = error_handler.handle_ocr_error(context, error_msg)
        elif step == "extraction_agent":
            recovery = error_handler.handle_extraction_error(context, error_msg)
        elif step == "verification_agent":
            recovery = error_handler.handle_verification_error(context, error_msg)
        else:
            recovery = error_handler.handle_generic_error(context, error_msg)
        
        if recovery:
            return recovery
        
        return None

    def _safe_float(self, value) -> float:
        """Safely convert value to float."""
        try:
            if isinstance(value, str):
                value = value.replace(",", "").strip()
            return float(value)
        except:
            return 0.0

    def get_workflow_status(self) -> Dict:
        """Return current workflow state."""
        return self.workflow_state.copy()

    def reset(self):
        """Reset workflow state for new batch."""
        self.workflow_state = {
            "invoices_processed": 0,
            "invoices_succeeded": 0,
            "invoices_failed": 0,
            "total_invoices": 0,
        }