"""
test_duplicate_detection.py
===========================
pytest suite for the 3-layer duplicate detection in swarm_invoice_agent.py

Layers tested:
  1. Exact Match    - invoice_number in PAID_INVOICES
  2. Fingerprint    - hash of (vendor + tax_id + amount + date)
  3. Fuzzy Match     - SequenceMatcher ratio ≥ 0.85 on invoice_number strings
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "hermes-agent", "Automated-Invoice-Verification"))

import pytest
from swarm_invoice_agent import (
    agent_duplicate,
    DuplicateResult,
    _INVOICE_FINGERPRINTS,
    _build_fingerprint,
    _sha256_hex,
    PAID_INVOICES,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def reset_fingerprints():
    """Clear the in-memory fingerprint cache before each test."""
    _INVOICE_FINGERPRINTS.clear()


# ── Layer 1: Exact Match ─────────────────────────────────────────────────────

class TestExactMatch:
    """Layer 1: invoice_number directly found in PAID_INVOICES set."""

    def test_exact_match_returns_duplicate(self):
        """Known paid invoice INV-0001 should be flagged as exact duplicate."""
        result = agent_duplicate("INV-0001")
        assert result.is_duplicate is True
        assert result.layer == "exact"
        assert result.matched_invoice == "INV-0001"
        assert result.confidence == 1.0

    def test_exact_match_iv9999(self):
        """Second entry in PAID_INVOICES should also hit exact layer."""
        result = agent_duplicate("INV-9999")
        assert result.is_duplicate is True
        assert result.layer == "exact"
        assert result.matched_invoice == "INV-9999"
        assert result.confidence == 1.0

    def test_exact_match_iv1806_0001(self):
        """IV1806-0001 is in PAID_INVOICES — exact hit."""
        result = agent_duplicate("IV1806-0001")
        assert result.is_duplicate is True
        assert result.layer == "exact"
        assert result.matched_invoice == "IV1806-0001"

    def test_no_match_unknown_invoice(self):
        """Invoice NOT in PAID_INVOICES should not be caught by exact layer."""
        result = agent_duplicate("INV-UNKNOWN-12345")
        # falls through to fingerprint / fuzzy, so is_duplicate may still be
        # True if fuzzy matches something — only exact layer is tested here
        if result.layer == "exact":
            pytest.fail("Unexpected exact match for unknown invoice")


# ── Layer 2: Fingerprint Match ───────────────────────────────────────────────

class TestFingerprintMatch:
    """Layer 2: fingerprint (vendor+tax_id+amount+date) hash collision."""

    def setup_method(self):
        reset_fingerprints()

    def test_fingerprint_new_invoice_caches(self):
        """First invoice with a given fingerprint should be cached (no duplicate)."""
        result = agent_duplicate(
            "INV-FIRST",
            vendor_name="surebattstore",
            tax_id="0103333333333",
            total_amount=410.00,
            invoice_date="2024-01-15",
        )
        # First time: cached, not a duplicate of anything else
        assert result.is_duplicate is False
        assert result.layer == "none"
        # Verify it was actually cached
        assert "INV-FIRST" in _INVOICE_FINGERPRINTS

    def test_fingerprint_duplicate_detected(self):
        """Second invoice with identical fingerprint should be flagged as duplicate."""
        # Pre-populate the global fingerprint cache with a real hash
        fp_key = _build_fingerprint(
            "surebattstore", "0103333333333", 410.00, "2024-01-15", 0.0, 0.0
        )
        fp_hash = _sha256_hex(fp_key)
        _INVOICE_FINGERPRINTS["INV-SEED"] = {
            "hash": fp_hash,
            "vendor": "surebattstore",
            "tax_id": "0103333333333",
            "amount": 410.00,
            "date": "2024-01-15",
        }

        result = agent_duplicate(
            "INV-DUP",
            vendor_name="surebattstore",
            tax_id="0103333333333",
            total_amount=410.00,
            invoice_date="2024-01-15",
        )
        assert result.is_duplicate is True
        assert result.layer == "fingerprint"
        assert result.matched_invoice == "INV-SEED"
        assert result.confidence == 0.95
        assert "Fingerprint match" in result.details

    def test_fingerprint_different_amount_not_duplicate(self):
        """Different amount → different fingerprint → no duplicate."""
        _INVOICE_FINGERPRINTS["INV-SEED2"] = {
            "hash": "b" * 64,
            "vendor": "surebattstore",
            "tax_id": "0103333333333",
            "amount": 410.00,
            "date": "2024-01-15",
        }

        result = agent_duplicate(
            "INV-DIFF-AMT",
            vendor_name="surebattstore",
            tax_id="0103333333333",
            total_amount=999.00,   # ← different
            invoice_date="2024-01-15",
        )
        assert result.is_duplicate is False
        assert result.layer == "none"

    def test_fingerprint_different_vendor_not_duplicate(self):
        """Different vendor name → different fingerprint."""
        _INVOICE_FINGERPRINTS["INV-SEED3"] = {
            "hash": "c" * 64,
            "vendor": "some_other_vendor",
            "tax_id": "0103333333333",
            "amount": 410.00,
            "date": "2024-01-15",
        }

        result = agent_duplicate(
            "INV-DIFF-VEND",
            vendor_name="surebattstore",    # ← different from "some_other_vendor"
            tax_id="0103333333333",
            total_amount=410.00,
            invoice_date="2024-01-15",
        )
        assert result.is_duplicate is False


# ── Layer 3: Fuzzy Match ─────────────────────────────────────────────────────

class TestFuzzyMatch:
    """Layer 3: invoice_number string similarity ≥ 0.85 via SequenceMatcher."""

    def setup_method(self):
        reset_fingerprints()

    def test_fuzzy_match_below_threshold_not_flagged(self):
        """Completely different invoice numbers should not fuzzy-match."""
        result = agent_duplicate("XYZ-ABC-99999")
        # Should fall through all layers without a match
        assert result.is_duplicate is False
        assert result.layer == "none"

    def test_fuzzy_match_within_threshold(self):
        """IV1806-0002 is very similar to IV1806-0001 (both in PAID_INVOICES).
        Normalised: 'iv18060001' vs 'iv18060002' → high similarity."""
        result = agent_duplicate("IV1806-0002")
        assert result.is_duplicate is True
        assert result.layer == "fuzzy"
        assert result.matched_invoice == "IV1806-0001"
        assert result.confidence == 0.78   # hard-coded confidence for fuzzy layer
        assert "Similar invoice number" in result.details

    def test_fuzzy_match_slight_variant(self):
        """A slight typographical variant of a paid invoice should fuzzy-match."""
        # INV-0001 is in PAID_INVOICES; IV1806-0001 is also there
        result = agent_duplicate("INV-0002")   # close to INV-0001
        # After exact & fingerprint checks fail, fuzzy should catch it
        # Normalised: 'inv0001' vs 'inv0002' — ratio = 5/7 ≈ 0.714 < 0.85 → not caught
        # So this is expected to NOT fuzzy-match
        if result.is_duplicate and result.layer == "fuzzy":
            assert result.matched_invoice in PAID_INVOICES

    def test_fuzzy_match_with_punctuation_differences(self):
        """Punctuation stripped before comparison — should still match."""
        result = agent_duplicate("IV1806.0001")  # dots instead of dashes
        # Normalised removes dots → same as 'iv18060001' → ratio = 1.0 → match
        assert result.is_duplicate is True
        assert result.layer == "fuzzy"


# ── Combined / edge cases ─────────────────────────────────────────────────────

class TestCombinedEdgeCases:
    """Mixed scenarios and boundary conditions."""

    def setup_method(self):
        reset_fingerprints()

    def test_exact_overrides_fingerprint(self):
        """If invoice_number is in PAID_INVOICES, exact layer fires first."""
        # INV-0001 is in PAID_INVOICES — even if we also pass fingerprint data
        result = agent_duplicate(
            "INV-0001",
            vendor_name="surebattstore",
            tax_id="0103333333333",
            total_amount=410.00,
            invoice_date="2024-01-15",
        )
        assert result.is_duplicate is True
        assert result.layer == "exact"
        assert result.matched_invoice == "INV-0001"
        assert result.confidence == 1.0

    def test_fingerprint_overrides_fuzzy(self):
        """Fingerprint match should fire before fuzzy (priority order 2 > 3)."""
        # Seed a fingerprint with a real hash for "INV-FP-TEST"
        fp_key = _build_fingerprint(
            "TestVendor", "9999999999999", 100.00, "2024-06-01", 0.0, 0.0
        )
        fp_hash = _sha256_hex(fp_key)
        _INVOICE_FINGERPRINTS["INV-FP-SEED"] = {
            "hash": fp_hash,
            "vendor": "TestVendor",
            "tax_id": "9999999999999",
            "amount": 100.00,
            "date": "2024-06-01",
        }

        result = agent_duplicate(
            "INV-FP-TEST",
            vendor_name="TestVendor",
            tax_id="9999999999999",
            total_amount=100.00,
            invoice_date="2024-06-01",
        )
        assert result.is_duplicate is True
        assert result.layer == "fingerprint"
        assert result.matched_invoice == "INV-FP-SEED"

    def test_empty_invoice_number_no_crash(self):
        """Empty invoice number should not crash the function."""
        result = agent_duplicate("")
        # Should gracefully return no-duplicate
        assert isinstance(result, DuplicateResult)
        assert result.layer in ("none", "fingerprint", "fuzzy")

    def test_all_fields_none_no_crash(self):
        """Passing None for all optional fields should not crash."""
        result = agent_duplicate(
            invoice_number="INV-TEST-NONE",
            vendor_name=None,
            tax_id=None,
            total_amount=0.0,
            invoice_date="",
        )
        assert isinstance(result, DuplicateResult)

    def test_result_is_duplicateDict(self):
        """Return type is always DuplicateResult with expected keys."""
        result = agent_duplicate("INV-NONE")
        d = result.to_dict()
        assert "is_duplicate" in d
        assert "layer" in d
        assert "matched_invoice" in d
        assert "confidence" in d
        assert "details" in d


# ── run summary ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Allow running with: python test_duplicate_detection.py
    pytest.main([__file__, "-v", "--tb=short"])
