"""
Streamlit UI for the Biolab Invoice Reconciler.
Wraps the existing invoice_pipeline.py and create_bill.py logic —
no changes to the core extraction/reconciliation/Xero logic itself.

Requirements:
    pip install streamlit

Usage:
    streamlit run app.py
"""

import json
import tempfile
import streamlit as st

from invoice_pipeline import extract_text, extract_structured_data, check_duplicate_lines, check_tariff_variance, check_missing_po

st.set_page_config(page_title="Biolab Invoice Reconciler", page_icon="🧪", layout="centered")

st.title("🧪 Biolab Invoice Reconciler")
st.caption("Upload a supplier invoice. It gets checked before anything is filed in Xero.")

uploaded_file = st.file_uploader("Upload invoice PDF", type=["pdf"])

if uploaded_file is not None:
    # Save the uploaded file to a temp path so pdfplumber can read it
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded_file.read())
        tmp_path = tmp.name

    with st.spinner("Extracting invoice data..."):
        text = extract_text(tmp_path)
        try:
            invoice = extract_structured_data(text)
        except Exception as e:
            st.error(f"Extraction failed: {e}")
            st.stop()

    st.subheader("Extracted data")
    col1, col2, col3 = st.columns(3)
    col1.metric("Vendor", invoice["vendor"])
    col2.metric("Invoice #", invoice["invoice_number"])
    col3.metric("Total Due", f"£{invoice['total_due']:.2f}")

    st.table(invoice["line_items"])

    flags = []
    flags += check_duplicate_lines(invoice)
    flags += check_tariff_variance(invoice)
    flags += check_missing_po(invoice)

    st.subheader("Reconciliation result")

    if flags:
        for f in flags:
            st.warning(f)
        st.error("🚫 FLAGGED FOR REVIEW — not auto-filed to Xero")
    else:
        st.success("✅ No issues found — safe to create as a Xero Bill")

        if st.button("Create Bill in Xero"):
            with st.spinner("Creating bill in Xero..."):
                try:
                    from create_bill import load_tokens, refresh_access_token, create_bill as create_xero_bill
                    tokens = load_tokens()
                    tokens = refresh_access_token(tokens)
                    result = create_xero_bill(tokens, invoice)
                    created = result["Invoices"][0]
                    st.success(f"✅ Bill created — status: {created['Status']}")
                    st.code(f"InvoiceID: {created['InvoiceID']}")
                except FileNotFoundError:
                    st.error("xero_tokens.json not found — run xero_login.py first to connect to Xero.")
                except Exception as e:
                    st.error(f"Failed to create bill: {e}")
