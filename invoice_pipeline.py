"""
Invoice reconciliation pipeline — Step 1: Extraction
------------------------------------------------------
Reads a messy supplier invoice PDF, extracts structured data using Claude,
and runs basic reconciliation checks (duplicate detection, tariff variance)
before anything gets written to Xero.

Requirements:
    pip install pdfplumber

Usage:
    python invoice_pipeline.py invoice_1_fisher_scientific.pdf
"""

import sys
import json
import pdfplumber

EXTRACTION_PROMPT = """You are extracting structured data from a supplier invoice.
Read the raw text below and return ONLY a JSON object (no markdown, no commentary)
with this exact shape:

{{
  "vendor": "string",
  "invoice_number": "string",
  "invoice_date": "YYYY-MM-DD",
  "po_number": "string or null",
  "line_items": [
    {{"catalog_no": "string or null", "description": "string", "qty": number, "unit_price": number, "line_total": number}}
  ],
  "subtotal": number,
  "tax": number,
  "total_due": number
}}

Convert all dates to YYYY-MM-DD format regardless of how they appear in the source.
If a field is genuinely missing from the invoice, use null.

RAW INVOICE TEXT:
---
{invoice_text}
---
"""

KNOWN_TARIFFS = {
    "ffpe block processing": {"rate": 6.00, "unit": "per block", "source": "KCL CCC tariff (consumables + labour)"},
}


def extract_text(pdf_path: str) -> str:
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text += (page.extract_text() or "") + "\n"
    return text


def extract_structured_data(invoice_text: str) -> dict:
    import subprocess
    prompt = EXTRACTION_PROMPT.format(invoice_text=invoice_text)
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude -p failed: {result.stderr}")
    raw = result.stdout.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


def check_tariff_variance(invoice: dict) -> list:
    flags = []
    for item in invoice["line_items"]:
        desc = item["description"].lower()
        for key, tariff in KNOWN_TARIFFS.items():
            if key in desc:
                if item["unit_price"] > tariff["rate"]:
                    flags.append(
                        f"PRICE VARIANCE: '{item['description']}' billed at "
                        f"£{item['unit_price']:.2f} {tariff['unit']}, but agreed "
                        f"tariff is £{tariff['rate']:.2f} ({tariff['source']})"
                    )
    return flags


def check_duplicate_lines(invoice: dict) -> list:
    flags = []
    seen = {}
    for item in invoice["line_items"]:
        key = item.get("catalog_no") or item["description"]
        if key in seen:
            flags.append(
                f"POSSIBLE DUPLICATE: '{item['description']}' appears more than "
                f"once (catalog no: {item.get('catalog_no')}) — check before filing."
            )
        seen[key] = True
    return flags


def check_missing_po(invoice: dict) -> list:
    flags = []
    if not invoice.get("po_number"):
        flags.append("MISSING PO NUMBER — cannot auto-match against a purchase order.")
    return flags


def process_invoice(pdf_path: str):
    print(f"\n{'='*60}\nProcessing: {pdf_path}\n{'='*60}")
    text = extract_text(pdf_path)
    invoice = extract_structured_data(text)

    print("\nExtracted data:")
    print(json.dumps(invoice, indent=2))

    flags = []
    flags += check_duplicate_lines(invoice)
    flags += check_tariff_variance(invoice)
    flags += check_missing_po(invoice)

    print("\nReconciliation result:")
    if flags:
        for f in flags:
            print(f"  ⚠️  {f}")
        print("  STATUS: FLAGGED FOR REVIEW (not auto-filed to Xero)")
    else:
        print("  ✅ No issues found — safe to auto-create as a Xero Bill (ACCPAY)")

    return invoice, flags


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python invoice_pipeline.py <path_to_invoice.pdf>")
        sys.exit(1)
    process_invoice(sys.argv[1])