"""
Test 2-way PO matching using the REAL agent_po_matcher from swarm_invoice_agent.py.

Scenarios:
  1. exact match       - amounts equal (within tolerance) -> MATCHED
  2. amount mismatch   - amounts differ                    -> AMOUNT_MISMATCH
  3. PO not found      - PO does not exist                 -> NOT_FOUND
  4. case sensitivity  - PO ref case difference            -> should still match
  5. whitespace handling - extra whitespace in PO ref      -> should still match
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from swarm_invoice_agent import agent_po_matcher, DATABASE_PO


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_po_keys():
    """Return list of PO keys that exist in DATABASE_PO."""
    return list(DATABASE_PO.keys())


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_exact_match(sample_po_keys):
    """Scenario 1: Exact PO match with equal amounts -> MATCHED."""
    # Use the first real PO from the database
    po_key = sample_po_keys[0]
    po_record = DATABASE_PO[po_key]
    amount = po_record["approved_amount"]

    result = agent_po_matcher(
        invoice_number="INV-001",
        po_reference=po_key,
        total_amount=amount,
    )

    print(f"\n  PO={po_key}, amount={amount} -> status={result.status}")
    assert result.matched is True, f"Expected MATCHED, got {result.status}: {result.details}"
    assert result.status == "MATCHED"
    print(f"  PASS  exact match: {result}")


def test_amount_mismatch(sample_po_keys):
    """Scenario 2: Amount differs from PO approved amount -> AMOUNT_MISMATCH."""
    po_key = sample_po_keys[0]
    po_record = DATABASE_PO[po_key]
    correct_amount = po_record["approved_amount"]
    wrong_amount = correct_amount + 999.99  # Clearly different

    result = agent_po_matcher(
        invoice_number="INV-002",
        po_reference=po_key,
        total_amount=wrong_amount,
    )

    print(f"\n  PO={po_key}, invoice_amount={wrong_amount}, po_amount={correct_amount} -> status={result.status}")
    assert result.matched is False, f"Expected not matched, got matched"
    assert result.status == "AMOUNT_MISMATCH", f"Expected AMOUNT_MISMATCH, got {result.status}"
    assert result.invoice_amount == wrong_amount
    assert result.approved_amount == correct_amount
    assert result.amount_diff > 0
    print(f"  PASS  amount mismatch: {result}")


def test_po_not_found(sample_po_keys):
    """Scenario 3: PO reference does not exist in database -> NOT_FOUND."""
    non_existent_po = "PO-NONEXISTENT-999"

    result = agent_po_matcher(
        invoice_number="INV-003",
        po_reference=non_existent_po,
        total_amount=1000.00,
    )

    print(f"\n  PO={non_existent_po} -> status={result.status}")
    assert result.matched is False
    assert result.status == "NOT_FOUND", f"Expected NOT_FOUND, got {result.status}"
    assert "not found" in result.details.lower() or non_existent_po in result.details
    print(f"  PASS  not found: {result}")


def test_case_insensitivity(sample_po_keys):
    """Scenario 4: PO reference with different case should still match."""
    po_key = sample_po_keys[0]
    po_record = DATABASE_PO[po_key]
    amount = po_record["approved_amount"]

    # Flip the case of each character
    mixed_case_po = po_key.swapcase()  # e.g. po-2023-001 -> PO-2023-001

    result = agent_po_matcher(
        invoice_number="INV-004",
        po_reference=mixed_case_po,
        total_amount=amount,
    )

    print(f"\n  PO={mixed_case_po} (case-swapped from {po_key}) -> status={result.status}")
    assert result.status == "MATCHED", (
        f"agent_po_matcher should be case-insensitive. "
        f"Expected MATCHED for {mixed_case_po}, got {result.status}: {result.details}"
    )
    assert result.matched is True
    print(f"  PASS  case insensitivity: {result}")


def test_whitespace_handling(sample_po_keys):
    """Scenario 5: PO reference with leading/trailing whitespace should still match."""
    po_key = sample_po_keys[0]
    po_record = DATABASE_PO[po_key]
    amount = po_record["approved_amount"]

    # Add leading and trailing whitespace
    padded_po = f"  {po_key}  "

    result = agent_po_matcher(
        invoice_number="INV-005",
        po_reference=padded_po,
        total_amount=amount,
    )

    print(f"\n  PO={padded_po!r} (whitespace-padded from {po_key}) -> status={result.status}")
    assert result.status == "MATCHED", (
        f"agent_po_matcher should strip whitespace. "
        f"Expected MATCHED for {padded_po!r}, got {result.status}: {result.details}"
    )
    assert result.matched is True
    print(f"  PASS  whitespace handling: {result}")


def test_no_po_reference():
    """Scenario 6: No PO reference provided -> NOT_FOUND."""
    result = agent_po_matcher(
        invoice_number="INV-006",
        po_reference=None,
        total_amount=5000.00,
    )

    assert result.matched is False
    assert result.status == "NOT_FOUND"
    assert "no po reference" in result.details.lower() or "not found" in result.details.lower()
    print(f"\n  PASS  no PO reference: {result}")


def test_amount_within_tolerance(sample_po_keys):
    """Amount within ±0.01 should still match (floating point tolerance)."""
    po_key = sample_po_keys[0]
    po_record = DATABASE_PO[po_key]
    correct_amount = po_record["approved_amount"]

    # Test just below and just above the tolerance boundary
    for diff in [-0.005, 0.005]:
        amount_within_tolerance = round(correct_amount + diff, 2)
        result = agent_po_matcher(
            invoice_number="INV-TOL",
            po_reference=po_key,
            total_amount=amount_within_tolerance,
        )
        print(f"\n  diff={diff}, amount={amount_within_tolerance}, status={result.status}")
        assert result.status == "MATCHED", (
            f"Amount diff={diff} should be within tolerance. Got {result.status}"
        )

    # Just outside tolerance
    result_outside = agent_po_matcher(
        invoice_number="INV-TOL2",
        po_reference=po_key,
        total_amount=round(correct_amount + 0.02, 2),
    )
    assert result_outside.status == "AMOUNT_MISMATCH"
    print(f"  PASS  tolerance boundary: diff=0.02 -> {result_outside.status}")


# ─── Summary ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import subprocess, sys

    print(f"\n=== PO Matching Test Suite (real agent_po_matcher) ===")
    print(f"Database POs: {list(DATABASE_PO.keys())}")
    print()
    result = subprocess.run(["pytest", __file__, "-v", "--tb=short"], capture_output=False)
    sys.exit(result.returncode)
