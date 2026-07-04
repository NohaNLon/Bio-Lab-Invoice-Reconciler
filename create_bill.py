"""
Creates a Bill (ACCPAY invoice) in Xero from an extracted invoice dict.
Run xero_login.py first to generate xero_tokens.json.

Requirements:
    pip install requests

Usage:
    python create_bill.py invoice_1_fisher_scientific.pdf
"""

import sys
import json
import requests
from invoice_pipeline import extract_text, extract_structured_data, process_invoice


def load_tokens():
    with open("xero_tokens.json") as f:
        return json.load(f)


def refresh_access_token(tokens):
    """Access tokens expire after 30 min — refresh if needed."""
    response = requests.post(
        "https://identity.xero.com/connect/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
        },
        auth=(tokens["client_id"], tokens["client_secret"]),
    )
    if response.status_code != 200:
        raise RuntimeError(f"Token refresh failed: {response.text}")
    new_tokens = response.json()
    tokens["access_token"] = new_tokens["access_token"]
    tokens["refresh_token"] = new_tokens["refresh_token"]
    with open("xero_tokens.json", "w") as f:
        json.dump(tokens, f, indent=2)
    return tokens


def xero_headers(tokens):
    return {
        "Authorization": f"Bearer {tokens['access_token']}",
        "Xero-tenant-id": tokens["tenant_id"],
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def find_or_create_contact(tokens, vendor_name):
    """Look up the vendor by name; create it if it doesn't exist yet."""
    resp = requests.get(
        "https://api.xero.com/api.xro/2.0/Contacts",
        headers=xero_headers(tokens),
        params={"where": f'Name=="{vendor_name}"'},
    )
    resp.raise_for_status()
    contacts = resp.json().get("Contacts", [])
    if contacts:
        return contacts[0]["ContactID"]

    create_resp = requests.post(
        "https://api.xero.com/api.xro/2.0/Contacts",
        headers=xero_headers(tokens),
        json={"Contacts": [{"Name": vendor_name}]},
    )
    create_resp.raise_for_status()
    return create_resp.json()["Contacts"][0]["ContactID"]


def check_already_filed(tokens, invoice: dict) -> list:
    """Query Xero directly: has this exact invoice (by vendor + invoice number)
    already been filed as a bill? Prevents re-filing the same invoice twice."""
    flags = []
    resp = requests.get(
        "https://api.xero.com/api.xro/2.0/Invoices",
        headers=xero_headers(tokens),
        params={"where": f'Reference=="{invoice["invoice_number"]}" AND Status!="DELETED"'},
    )
    resp.raise_for_status()
    existing = resp.json().get("Invoices", [])
    if existing:
        flags.append(
            f"ALREADY FILED: A bill with reference '{invoice['invoice_number']}' "
            f"already exists in Xero (InvoiceID: {existing[0]['InvoiceID']}) — "
            f"skipping to avoid duplicate payment."
        )
    return flags


def create_bill(tokens, invoice: dict):
    contact_id = find_or_create_contact(tokens, invoice["vendor"])

    line_items = [
        {
            "Description": item["description"],
            "Quantity": item["qty"],
            "UnitAmount": item["unit_price"],
            "AccountCode": "429",  # "General Expenses" in default Xero chart of accounts
        }
        for item in invoice["line_items"]
    ]

    bill_payload = {
        "Invoices": [{
            "Type": "ACCPAY",
            "Contact": {"ContactID": contact_id},
            "Date": invoice["invoice_date"],
            "DueDate": invoice["invoice_date"],
            "LineItems": line_items,
            "Reference": invoice["invoice_number"],
            "Status": "DRAFT",
        }]
    }

    resp = requests.post(
        "https://api.xero.com/api.xro/2.0/Invoices",
        headers=xero_headers(tokens),
        json=bill_payload,
    )
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python create_bill.py <path_to_invoice.pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    invoice, flags = process_invoice(pdf_path)

    if flags:
        print("\n⚠️  This invoice was flagged — not auto-creating a bill.")
        print("Review manually before filing.")
        sys.exit(0)

    tokens = load_tokens()
    tokens = refresh_access_token(tokens)

    already_filed_flags = check_already_filed(tokens, invoice)
    if already_filed_flags:
        for f in already_filed_flags:
            print(f"\n⚠️  {f}")
        print("STATUS: SKIPPED — not creating a duplicate bill.")
        sys.exit(0)

    print("\nCreating Bill in Xero...")
    result = create_bill(tokens, invoice)
    created_invoice = result["Invoices"][0]
    print(f"✅ Created Bill — status: {created_invoice['Status']}")
    print(f"   InvoiceID: {created_invoice['InvoiceID']}")
    print(f"   Reference: {created_invoice.get('Reference', 'N/A')}")
