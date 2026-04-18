"""
Swarm Invoice Verification Agents
==================================
agent_duplicate  - 3-layer duplicate detection (exact, fingerprint, fuzzy)
agent_po_matcher - 2-way PO matching against DATABASE_PO

Built for the Typhoon Invoice AI verification swarm system.
"""

import hashlib
import re
from difflib import SequenceMatcher
from typing import Optional

# ============================================================
# DATABASE_PO - Purchase Order database for 2-way matching
# ============================================================
DATABASE_PO: dict[str, dict] = {
    "PO-2023-001": {
        "vendor": "บริษัท วัสดุก่อสร้าง จำกัด",
        "tax_id": "0105555555555",
        "approved_amount": 10700.00,
    },
    "PO-2023-002": {
        "vendor": "ร้านเหล็กไทย",
        "tax_id": "0104444444444",
        "approved_amount": 50000.00,
    },
    "IV1806-0002": {
        "vendor": "surebattstore",
        "tax_id": "0103333333333",
        "approved_amount": 410.00,
    },
    "xxx-xxxx": {
        "vendor": "surebattstore",
        "tax_id": "1234567890123",
        "approved_amount": 410.00,
    },
}

# ============================================================
# PAID_INVOICES - Set of already-paid invoice numbers
# ============================================================
PAID_INVOICES: set[str] = {"INV-0001", "INV-9999", "IV1806-0001"}


# ============================================================
# INVOICE FINGERPRINT CACHE (in-memory)
# ============================================================
_INVOICE_FINGERPRINTS: dict[str, dict] = {}


# ============================================================
# Result dataclasses
# ============================================================
class DuplicateResult:
    def __init__(
        self,
        is_duplicate: bool,
        layer: str,  # "exact" | "fingerprint" | "fuzzy" | "none"
        matched_invoice: Optional[str] = None,
        confidence: float = 0.0,
        details: str = "",
    ):
        self.is_duplicate = is_duplicate
        self.layer = layer
        self.matched_invoice = matched_invoice
        self.confidence = confidence
        self.details = details

    def __repr__(self):
        return (
            f"DuplicateResult(duplicate={self.is_duplicate}, "
            f"layer={self.layer}, matched={self.matched_invoice}, "
            f"confidence={self.confidence:.2f}, details={self.details!r})"
        )

    def to_dict(self) -> dict:
        return {
            "is_duplicate": self.is_duplicate,
            "layer": self.layer,
            "matched_invoice": self.matched_invoice,
            "confidence": self.confidence,
            "details": self.details,
        }


class POMatchResult:
    def __init__(
        self,
        matched: bool,
        po_number: Optional[str] = None,
        status: str = "NOT_FOUND",  # MATCHED | AMOUNT_MISMATCH | NOT_FOUND
        approved_amount: float = 0.0,
        invoice_amount: float = 0.0,
        amount_diff: float = 0.0,
        vendor_match: bool = False,
        tax_id_match: bool = False,
        details: str = "",
    ):
        self.matched = matched
        self.po_number = po_number
        self.status = status
        self.approved_amount = approved_amount
        self.invoice_amount = invoice_amount
        self.amount_diff = amount_diff
        self.vendor_match = vendor_match
        self.tax_id_match = tax_id_match
        self.details = details

    def __repr__(self):
        return (
            f"POMatchResult(matched={self.matched}, po={self.po_number}, "
            f"status={self.status}, diff={self.amount_diff:.2f})"
        )

    def to_dict(self) -> dict:
        return {
            "matched": self.matched,
            "po_number": self.po_number,
            "status": self.status,
            "approved_amount": self.approved_amount,
            "invoice_amount": self.invoice_amount,
            "amount_diff": self.amount_diff,
            "vendor_match": self.vendor_match,
            "tax_id_match": self.tax_id_match,
            "details": self.details,
        }


# ============================================================
# agent_duplicate - 3-Layer Duplicate Detection
# ============================================================
def agent_duplicate(
    invoice_number: str,
    vendor_name: Optional[str] = None,
    tax_id: Optional[str] = None,
    total_amount: float = 0.0,
    invoice_date: str = "",
    subtotal: float = 0.0,
    vat_amount: float = 0.0,
) -> DuplicateResult:
    """
    3-layer duplicate detection for invoice verification.

    Layers:
      1. Exact Match    - invoice_number directly in PAID_INVOICES
      2. Fingerprint    - hash of (vendor + tax_id + amount + date) vs cached
      3. Fuzzy Match     - Levenshtein-like similarity on invoice_number strings

    Parameters
    ----------
    invoice_number : str
        The invoice number extracted from the invoice.
    vendor_name : str, optional
        Vendor name for fingerprinting.
    tax_id : str, optional
        Tax ID for fingerprinting.
    total_amount : float
        Total invoice amount for fingerprinting.
    invoice_date : str
        Invoice date (YYYY-MM-DD) for fingerprinting.
    subtotal : float, optional
        Subtotal for additional fingerprinting.
    vat_amount : float, optional
        VAT amount for additional fingerprinting.

    Returns
    -------
    DuplicateResult
        is_duplicate, layer, matched_invoice, confidence (0.0-1.0), details
    """
    # ---- Layer 1: Exact Match ----
    if invoice_number and invoice_number in PAID_INVOICES:
        return DuplicateResult(
            is_duplicate=True,
            layer="exact",
            matched_invoice=invoice_number,
            confidence=1.0,
            details=f"Invoice number '{invoice_number}' found in paid invoices database",
        )

    # ---- Layer 2: Fingerprint Match ----
    fingerprint_key = _build_fingerprint(
        vendor_name, tax_id, total_amount, invoice_date, subtotal, vat_amount
    )
    if fingerprint_key:
        fp_hash = _sha256_hex(fingerprint_key)
        for cached_inv, cached_fp in _INVOICE_FINGERPRINTS.items():
            if cached_fp["hash"] == fp_hash:
                return DuplicateResult(
                    is_duplicate=True,
                    layer="fingerprint",
                    matched_invoice=cached_inv,
                    confidence=0.95,
                    details=f"Fingerprint match: identical content signature "
                    f"(vendor/amount/date). Candidate: {cached_inv}",
                )
        # Cache this invoice's fingerprint for future checks
        _INVOICE_FINGERPRINTS[invoice_number] = {
            "hash": fp_hash,
            "vendor": vendor_name,
            "tax_id": tax_id,
            "amount": total_amount,
            "date": invoice_date,
        }

    # ---- Layer 3: Fuzzy Match ----
    if invoice_number:
        fuzzy_match = _fuzzy_search(invoice_number, PAID_INVOICES, threshold=0.85)
        if fuzzy_match:
            return DuplicateResult(
                is_duplicate=True,
                layer="fuzzy",
                matched_invoice=fuzzy_match,
                confidence=0.78,
                details=f"Similar invoice number '{invoice_number}' "
                f"found near paid invoice '{fuzzy_match}'",
            )

    # No duplicate found across all layers
    return DuplicateResult(
        is_duplicate=False,
        layer="none",
        matched_invoice=None,
        confidence=0.0,
        details="No duplicate detected across all verification layers",
    )


# ============================================================
# agent_po_matcher - 2-Way PO Matching
# ============================================================
def agent_po_matcher(
    invoice_number: str,
    po_reference: Optional[str],
    vendor_name: Optional[str] = None,
    tax_id: Optional[str] = None,
    total_amount: float = 0.0,
) -> POMatchResult:
    """
    2-way PO matching for invoice verification.

    2-Way Matching Logic:
      1. PO Existence  - po_reference must exist in DATABASE_PO
      2. Amount Match  - invoice total_amount must match PO approved_amount (±0.01)

    Additionally performs soft checks:
      - Vendor name similarity (warning only)
      - Tax ID exact match (warning if mismatch)

    Parameters
    ----------
    invoice_number : str
        Invoice number for reference.
    po_reference : str, optional
        PO number extracted from the invoice.
    vendor_name : str, optional
        Vendor name for soft matching.
    tax_id : str, optional
        Tax ID for soft matching.
    total_amount : float
        Invoice total amount to compare against PO.

    Returns
    -------
    POMatchResult
        matched, po_number, status, approved_amount, invoice_amount,
        amount_diff, vendor_match, tax_id_match, details
    """
    if not po_reference:
        return POMatchResult(
            matched=False,
            po_number=None,
            status="NOT_FOUND",
            approved_amount=0.0,
            invoice_amount=total_amount,
            amount_diff=total_amount,
            vendor_match=False,
            tax_id_match=False,
            details="No PO reference provided on the invoice",
        )

    # Normalize PO reference for case-insensitive, whitespace-safe lookup
    normalized_po = po_reference.upper().strip()

    # ---- Check 1: PO exists in DATABASE_PO ----
    if normalized_po not in DATABASE_PO:
        return POMatchResult(
            matched=False,
            po_number=po_reference,
            status="NOT_FOUND",
            approved_amount=0.0,
            invoice_amount=total_amount,
            amount_diff=total_amount,
            vendor_match=False,
            tax_id_match=False,
            details=f"PO '{po_reference}' not found in database",
        )

    po_record = DATABASE_PO[normalized_po]
    approved_amount = po_record["approved_amount"]
    db_vendor = po_record.get("vendor", "")
    db_tax_id = po_record.get("tax_id", "")

    # ---- Check 2: Amount Match (2-way: invoice vs PO approved) ----
    amount_diff = abs(total_amount - approved_amount)
    amount_match = amount_diff < 0.01

    # ---- Soft checks ----
    vendor_match = False
    if vendor_name and db_vendor:
        # Normalize and compare
        norm_vendor = re.sub(r"\s+", "", vendor_name.lower())
        norm_db_vendor = re.sub(r"\s+", "", db_vendor.lower())
        vendor_match = norm_vendor == norm_db_vendor or SequenceMatcher(
            None, norm_vendor, norm_db_vendor
        ).ratio() >= 0.85

    tax_id_match = False
    if tax_id and db_tax_id:
        tax_id_match = tax_id == db_tax_id

    # ---- Determine final status ----
    if amount_match:
        status = "MATCHED"
        details = (
            f"PO '{po_reference}' matched. "
            f"Amount verified: {total_amount:.2f} == {approved_amount:.2f}. "
            f"(Vendor: {'✓' if vendor_match else '⚠ diff'}, TaxID: {'✓' if tax_id_match else '⚠ diff'})"
        )
    else:
        status = "AMOUNT_MISMATCH"
        details = (
            f"PO '{po_reference}' found but amount mismatch. "
            f"Invoice: {total_amount:.2f}, PO approved: {approved_amount:.2f}, "
            f"diff: {amount_diff:.2f}. "
            f"(Vendor: {'✓' if vendor_match else '⚠ diff'}, TaxID: {'✓' if tax_id_match else '⚠ diff'})"
        )

    return POMatchResult(
        matched=(status == "MATCHED"),
        po_number=po_reference,
        status=status,
        approved_amount=approved_amount,
        invoice_amount=total_amount,
        amount_diff=amount_diff,
        vendor_match=vendor_match,
        tax_id_match=tax_id_match,
        details=details,
    )


# ============================================================
# Combined Invoice Verification Agent
# ============================================================
def verify_invoice(
    invoice_number: str,
    po_reference: Optional[str] = None,
    vendor_name: Optional[str] = None,
    tax_id: Optional[str] = None,
    total_amount: float = 0.0,
    invoice_date: str = "",
    subtotal: float = 0.0,
    vat_amount: float = 0.0,
) -> dict:
    """
    Full invoice verification combining duplicate detection and PO matching.

    Returns a consolidated dict with both results and a recommended action.
    """
    dup_result = agent_duplicate(
        invoice_number=invoice_number,
        vendor_name=vendor_name,
        tax_id=tax_id,
        total_amount=total_amount,
        invoice_date=invoice_date,
        subtotal=subtotal,
        vat_amount=vat_amount,
    )

    po_result = agent_po_matcher(
        invoice_number=invoice_number,
        po_reference=po_reference,
        vendor_name=vendor_name,
        tax_id=tax_id,
        total_amount=total_amount,
    )

    # Determine recommended action
    if dup_result.is_duplicate:
        action = "Reject"
        status = f"DUPLICATE ({dup_result.layer} match)"
    elif po_result.status == "MATCHED":
        action = "Approve"
        status = "PO MATCHED"
    elif po_result.status == "AMOUNT_MISMATCH":
        action = "Hold"
        status = f"AMOUNT MISMATCH (diff: {po_result.amount_diff:.2f})"
    else:
        action = "Hold"
        status = f"PO NOT FOUND: {po_reference}"

    return {
        "invoice_number": invoice_number,
        "po_reference": po_reference,
        "vendor_name": vendor_name,
        "tax_id": tax_id,
        "total_amount": total_amount,
        "invoice_date": invoice_date,
        "subtotal": subtotal,
        "vat_amount": vat_amount,
        "duplicate": dup_result.to_dict(),
        "po_match": po_result.to_dict(),
        "recommended_action": action,
        "verification_status": status,
        "remarks": f"{dup_result.details} | {po_result.details}",
    }


# ============================================================
# Internal helpers
# ============================================================
def _build_fingerprint(
    vendor: Optional[str],
    tax_id: Optional[str],
    amount: float,
    date: str,
    subtotal: float,
    vat: float,
) -> str:
    """Build a normalized fingerprint string from invoice fields."""
    parts = [
        (vendor or "").strip().lower(),
        (tax_id or "").strip(),
        f"{amount:.2f}",
        date.strip(),
        f"{subtotal:.2f}",
        f"{vat:.2f}",
    ]
    return "|".join(parts)


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fuzzy_search(query: str, candidates: set[str], threshold: float = 0.85) -> Optional[str]:
    """
    Find the best fuzzy match for query in candidates.
    Uses SequenceMatcher ratio against threshold.
    Returns the best match string or None.
    """
    query_normalized = re.sub(r"[^a-zA-Z0-9]", "", query).lower()
    best_match: Optional[str] = None
    best_ratio = 0.0

    for candidate in candidates:
        cand_normalized = re.sub(r"[^a-zA-Z0-9]", "", candidate).lower()
        ratio = SequenceMatcher(None, query_normalized, cand_normalized).ratio()
        if ratio >= threshold and ratio > best_ratio:
            best_ratio = ratio
            best_match = candidate

    return best_match


# ============================================================
# Demo / test
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print(" agent_duplicate — 3-Layer Duplicate Detection")
    print("=" * 60)

    # Layer 1: Exact
    r1 = agent_duplicate("INV-0001")
    print(f"[exact]    {r1}")

    # Layer 2: Fingerprint (first time = new, second time = dup)
    r2a = agent_duplicate(
        "INV-NEW",
        vendor_name="surebattstore",
        tax_id="0103333333333",
        total_amount=410.00,
        invoice_date="2024-01-15",
    )
    print(f"[fp new]   {r2a}")

    r2b = agent_duplicate(
        "INV-DUP",
        vendor_name="surebattstore",
        tax_id="0103333333333",
        total_amount=410.00,
        invoice_date="2024-01-15",
    )
    print(f"[fp dup]   {r2b}")

    # Layer 3: Fuzzy
    r3 = agent_duplicate("IV1806-0001")  # similar to IV1806-0002
    print(f"[fuzzy]    {r3}")

    # No duplicate
    r4 = agent_duplicate(
        "INV-BRANDNEW",
        vendor_name="New Vendor",
        tax_id="9999999999999",
        total_amount=12345.00,
        invoice_date="2024-06-01",
    )
    print(f"[none]     {r4}")

    print()
    print("=" * 60)
    print(" agent_po_matcher — 2-Way PO Matching")
    print("=" * 60)

    # Match
    r5 = agent_po_matcher(
        invoice_number="INV-001",
        po_reference="PO-2023-001",
        vendor_name="บริษัท วัสดุก่อสร้าง จำกัด",
        tax_id="0105555555555",
        total_amount=10700.00,
    )
    print(f"[matched]  {r5}")

    # Amount mismatch
    r6 = agent_po_matcher(
        invoice_number="INV-002",
        po_reference="PO-2023-001",
        vendor_name="บริษัท วัสดุก่อสร้าง จำกัด",
        tax_id="0105555555555",
        total_amount=5000.00,
    )
    print(f"[mismatch] {r6}")

    # PO not found
    r7 = agent_po_matcher(
        invoice_number="INV-003",
        po_reference="PO-9999",
        vendor_name="Unknown",
        tax_id="0000000000000",
        total_amount=100.00,
    )
    print(f"[notfound] {r7}")

    print()
    print("=" * 60)
    print(" verify_invoice — Combined Result")
    print("=" * 60)
    result = verify_invoice(
        invoice_number="INV-FULL-TEST",
        po_reference="PO-2023-001",
        vendor_name="บริษัท วัสดุก่อสร้าง จำกัด",
        tax_id="0105555555555",
        total_amount=10700.00,
        invoice_date="2024-01-15",
        subtotal=10000.00,
        vat_amount=700.00,
    )
    for k, v in result.items():
        print(f"  {k}: {v}")
