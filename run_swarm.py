#!/usr/bin/env python3
"""
Invoice Verification Swarm - Main Run Script
Orchestrates the full invoice verification pipeline with error handling.

Usage:
    python run_swarm.py                    # Run with demo invoices
    python run_swarm.py --input ./invoices  # Run with custom folder
    python run_swarm.py --help             # Show help

Workflow:
    1. OCR Agent      - Extract text from invoice images
    2. Extraction Agent - Parse structured data from OCR text
    3. Verification Agent - Match against PO database, detect duplicates
    4. Reporting Agent - Generate final verification reports
"""

import argparse
import json
import os
import sys
import time
import tempfile
from pathlib import Path
from datetime import datetime

# Add project directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from orchestrator import OrchestratorAgent
from error_handler import ErrorHandler


def setup_config():
    """Initialize configuration from environment and defaults."""
    return {
        # OCR Settings
        "ocr_base_url": os.getenv("OCR_BASE_URL", "https://api.opentyphoon.ai/v1"),
        "ocr_model": os.getenv("OCR_MODEL", "typhoon-ocr"),
        
        # LLM Settings
        "llm_base_url": os.getenv("LLM_BASE_URL", "https://api.opentyphoon.ai/v1"),
        "llm_model": os.getenv("LLM_MODEL", "typhoon-v2.5-30b-a3b-instruct"),
        
        # Retry Settings
        "max_retries": int(os.getenv("MAX_RETRIES", "3")),
        "retry_delay": float(os.getenv("RETRY_DELAY", "5.0")),
        
        # Rate Limiting
        "rate_limit_delay": float(os.getenv("RATE_LIMIT_DELAY", "3.1")),
        
        # Mock Database (replace with real ERP connection in production)
        "database_po": {
            "PO-2023-001": {"vendor": "บริษัท วัสดุก่อสร้าง จำกัด", "tax_id": "0105555555555", "approved_amount": 10700.00},
            "PO-2023-002": {"vendor": "ร้านเหล็กไทย", "tax_id": "0104444444444", "approved_amount": 50000.00},
            "IV1806-0002": {"vendor": "surebattstore", "tax_id": "0103333333333", "approved_amount": 410.00},
            "xxx-xxxx": {"vendor": "surebattstore", "tax_id": "1234567890123", "approved_amount": 410.00}
        },
        
        # Paid invoice history (duplicate detection)
        "paid_invoices": {"INV-0001", "INV-9999", "IV1806-0001"},
    }


def scan_invoices_folder(folder_path: str) -> list:
    """Scan folder for invoice files."""
    supported_extensions = {".png", ".jpg", ".jpeg", ".pdf", ".tiff", ".bmp"}
    invoices = []
    
    path = Path(folder_path)
    if not path.exists():
        print(f"[Error] Folder not found: {folder_path}")
        return []
    
    for file_path in path.iterdir():
        if file_path.suffix.lower() in supported_extensions:
            invoices.append({
                "file_path": str(file_path.absolute()),
                "file_name": file_path.name,
                "file_size": file_path.stat().st_size
            })
    
    return sorted(invoices, key=lambda x: x["file_name"])


def create_demo_invoices() -> list:
    """Create demo invoice entries for testing."""
    return [
        {"file_name": "invoice_001.jpg", "file_path": None, "demo": True},
        {"file_name": "invoice_002.pdf", "file_path": None, "demo": True},
    ]


def print_separator():
    """Print visual separator."""
    print("\n" + "=" * 60 + "\n")


def print_results_summary(results: dict):
    """Print formatted results summary."""
    summary = results.get("workflow_summary", {})
    success_rate = results.get("success_rate", 0)
    
    print_separator()
    print("INVOICE VERIFICATION SWARM - RESULTS SUMMARY")
    print_separator()
    
    print(f"Total Invoices Processed: {summary.get('invoices_processed', 0)}")
    print(f"  ✅ Succeeded: {summary.get('invoices_succeeded', 0)}")
    print(f"  ❌ Failed: {summary.get('invoices_failed', 0)}")
    print(f"  Success Rate: {success_rate:.1f}%")
    print()
    
    # Detailed results
    print("DETAILED RESULTS:")
    print("-" * 60)
    
    for idx, result in enumerate(results.get("results", []), 1):
        status_icon = "✅" if result.get("status") == "success" else "❌"
        print(f"\n{idx}. {status_icon} {result.get('file_name', 'unknown')}")
        
        if result.get("status") == "success":
            verification = result.get("verification_result", {})
            print(f"   Status: {verification.get('verification_status', 'UNKNOWN')}")
            print(f"   Action: {verification.get('action', 'Pending')}")
            if verification.get("remarks"):
                print(f"   Remarks: {verification.get('remarks')}")
        else:
            print(f"   Error: {result.get('error', 'Unknown error')}")
    
    print()


def run_demo_mode():
    """Run in demo mode without actual files."""
    print_separator()
    print("DEMO MODE - Invoice Verification Swarm")
    print_separator()
    print("\nThis demo simulates the invoice verification workflow.")
    print("In production mode, provide actual invoice files with --input flag.\n")
    
    config = setup_config()
    orchestrator = OrchestratorAgent(config)
    error_handler = ErrorHandler(
        max_retries=config["max_retries"],
        retry_delay=config["retry_delay"]
    )
    
    # Demo invoices (no actual files)
    demo_invoices = create_demo_invoices()
    
    print(f"Processing {len(demo_invoices)} demo invoice(s)...")
    print("-" * 40)
    
    # Simulate processing
    for idx, demo in enumerate(demo_invoices, 1):
        print(f"\n[Demo] Processing invoice {idx}/{len(demo_invoices)}: {demo['file_name']}")
        print("  [Pipeline] OCR Agent... simulated")
        print("  [Pipeline] Extraction Agent... simulated")
        print("  [Pipeline] Verification Agent... simulated")
        print("  [Pipeline] Reporting Agent... simulated")
        time.sleep(0.5)
    
    # Generate simulated results
    simulated_results = {
        "workflow_summary": {
            "invoices_processed": 2,
            "invoices_succeeded": 2,
            "invoices_failed": 0,
            "total_invoices": 2
        },
        "results": [
            {
                "file_name": "invoice_001.jpg",
                "status": "success",
                "verification_result": {
                    "verification_status": "MATCHED",
                    "action": "Approve",
                    "remarks": ""
                }
            },
            {
                "file_name": "invoice_002.pdf",
                "status": "success",
                "verification_result": {
                    "verification_status": "PO_NOT_FOUND",
                    "action": "Hold",
                    "remarks": "PO reference not found in system"
                }
            }
        ],
        "success_rate": 100.0
    }
    
    print_results_summary(simulated_results)
    print("Demo mode completed. Run with --input <folder> for real processing.")


def run_production_mode(input_folder: str):
    """Run with actual invoice files."""
    print_separator()
    print("INVOICE VERIFICATION SWARM - Production Mode")
    print_separator()
    print(f"Input folder: {input_folder}")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Scan for invoices
    invoices = scan_invoices_folder(input_folder)
    
    if not invoices:
        print("[Error] No invoice files found in specified folder.")
        print(f"Supported formats: .png, .jpg, .jpeg, .pdf, .tiff, .bmp")
        return
    
    print(f"Found {len(invoices)} invoice(s) to process.")
    print("-" * 60)
    
    # Initialize
    config = setup_config()
    orchestrator = OrchestratorAgent(config)
    
    start_time = time.time()
    
    # Run workflow
    results = orchestrator.run_workflow(invoices)
    
    elapsed = time.time() - start_time
    
    # Print summary
    print_results_summary(results)
    print(f"Total processing time: {elapsed:.2f} seconds")


def main():
    parser = argparse.ArgumentParser(
        description="Invoice Verification Swarm - Automated 2-Way Matching & Duplicate Detection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --demo                      Run demonstration mode
  %(prog)s --input ./invoices           Process all invoices in folder
  %(prog)s --input ./invoices --verbose Show detailed processing output
  
Environment Variables:
  OCR_BASE_URL    Base URL for OCR service (default: Typhoon Cloud)
  LLM_BASE_URL    Base URL for LLM service (default: Typhoon Cloud)
  OCR_MODEL       OCR model name
  LLM_MODEL       LLM model name
  MAX_RETRIES     Max retry attempts per step (default: 3)
  RETRY_DELAY     Delay between retries in seconds (default: 5.0)
        """
    )
    
    parser.add_argument(
        "--demo", 
        action="store_true",
        help="Run in demo mode (no actual files)"
    )
    
    parser.add_argument(
        "--input", 
        type=str,
        default=None,
        help="Path to folder containing invoice files"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )
    
    args = parser.parse_args()
    
    # Configure verbose logging
    if args.verbose:
        print("[Config] Verbose mode enabled")
    
    # Run appropriate mode
    if args.demo:
        run_demo_mode()
    elif args.input:
        run_production_mode(args.input)
    else:
        # Default: show help or run demo
        parser.print_help()
        print("\n[Hint] Use --demo to run simulation or --input <folder> for real processing")


if __name__ == "__main__":
    main()