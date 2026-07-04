"""
Xero login — run this ONCE to connect your Web app to your trial org.

Before running, edit the two values below with your Web app credentials
(the "Biolab Invoice Reconciler" app, not the Custom Connection one).

Requirements:
    pip install requests

Usage:
    python xero_login.py
"""

import http.server
import json
import urllib.parse
import webbrowser
import requests

# ---- EDIT THESE TWO LINES ----
CLIENT_ID = "F2CB0FBB25B94FCBB27E7D1B3534220F"
CLIENT_SECRET = "Ho-pCPUbvsOjvUYmehR0QhtpA8a3pgPT24pcqovpxyqLJozB"
# --------------------------------

REDIRECT_URI = "http://localhost:5000/callback"
SCOPES = "openid profile email accounting.invoices accounting.contacts accounting.settings accounting.attachments offline_access"

auth_code_holder = {}


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            auth_code_holder["code"] = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Connected! You can close this tab and go back to the terminal.</h2>")
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # silence default request logging


def main():
    auth_url = (
        "https://login.xero.com/identity/connect/authorize?"
        + urllib.parse.urlencode({
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "state": "hackathon123",
        })
    )

    print("Opening browser for Xero login...")
    print("If it doesn't open automatically, paste this URL into your browser:")
    print(auth_url)
    webbrowser.open(auth_url)

    server = http.server.HTTPServer(("localhost", 5000), CallbackHandler)
    print("\nWaiting for you to log in and approve access...")
    server.timeout = 120  # give up after 2 minutes of no requests at all
    while "code" not in auth_code_holder:
        server.handle_request()
        if "code" not in auth_code_holder:
            print("(Ignored a stray request, still waiting for the real callback...)")

    code = auth_code_holder.get("code")
    if not code:
        print("Did not receive an authorization code. Something went wrong.")
        return

    print("Got authorization code, exchanging for tokens...")
    token_response = requests.post(
        "https://identity.xero.com/connect/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
        auth=(CLIENT_ID, CLIENT_SECRET),
    )

    if token_response.status_code != 200:
        print(f"Token exchange failed: {token_response.status_code}")
        print(token_response.text)
        return

    tokens = token_response.json()

    # Get the tenant (organisation) ID
    conn_response = requests.get(
        "https://api.xero.com/connections",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    connections = conn_response.json()
    if not connections:
        print("No connected organisations found. Did you select 'Bio Lab Test Org' during login?")
        return

    tenant_id = connections[0]["tenantId"]
    tenant_name = connections[0]["tenantName"]

    tokens["tenant_id"] = tenant_id
    tokens["client_id"] = CLIENT_ID
    tokens["client_secret"] = CLIENT_SECRET

    with open("xero_tokens.json", "w") as f:
        json.dump(tokens, f, indent=2)

    print(f"\n✅ Connected to '{tenant_name}'")
    print("Tokens saved to xero_tokens.json")
    print("You're ready to run create_bill.py")


if __name__ == "__main__":
    main()
