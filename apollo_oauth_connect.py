"""
ONE-TIME SETUP, part 2 of 2 — run this after setup_agent.py (and after saving
its printed IDs into .env).

Apollo's MCP server requires OAuth 2.0 login (no API key) — this script:
  1. Discovers Apollo's OAuth authorization/token endpoints from the MCP
     server's metadata (per RFC 9728 / RFC 8414).
  2. Dynamically registers a small local OAuth client (RFC 7591) — no
     Apollo dashboard app registration needed, per Apollo's own docs
     ("Partners" registering an OAuth app is only for partnership
     integrations, not this case).
  3. Opens YOUR browser to Apollo's login/consent screen. YOU log in and
     click "Allow" — this script cannot and does not do that step for you.
  4. Catches the redirect on a local port, exchanges the code for tokens,
     and stores them in the vault created by setup_agent.py.

Anthropic auto-refreshes the token from there, so this is a one-time run
(re-run only if you ever need to reconnect, e.g. after revoking access).
"""

import base64
import hashlib
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import anthropic

import config

REDIRECT_PORT = int(os.environ.get("APOLLO_OAUTH_REDIRECT_PORT", "8765"))
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"

# Least-privilege: the read/search/enrich scopes this agent's tools use,
# plus account/contact write scopes so qualified leads can be saved into
# Apollo as Accounts/Contacts. Still deliberately excludes everything else
# Apollo's MCP server offers — emailer sends, domain/email purchases, task
# management, billing, etc. — none of which this agent needs.
REQUESTED_SCOPES = [
    "read_user_profile",
    "organizations_search",
    "organizations_job_posting",
    "organizations_enrich",
    "organizations_bulk_enrich",
    "mixed_people_api_search",
    "mixed_companies_search",
    "people_match",
    "people_bulk_match",
    "contacts_search",
    "contact_read",
    # People/bulk match can trigger Apollo's async "waterfall" email
    # enrichment, which queues a job and requires polling
    # apollo_webhook_result_show for the result — that polling tool needs
    # this scope specifically, separate from people_match/people_bulk_match.
    "webhook_result_read",
    "account_write",
    "account_update",
    "account_bulk_create",
    "contact_write",
    "contact_update",
    "contacts_bulk_create",
]

CREDENTIAL_DISPLAY_NAME = "Apollo OAuth (auto-connected)"


# Apollo's Cloudflare WAF returns 403 for Python's default urllib User-Agent
# ("Python-urllib/3.x") — a browser-like one is required for every request
# this script makes to Apollo, not just discovery.
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NamaSys-LeadGen-Setup/1.0)",
    "Accept": "application/json",
}


def _get_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        return None


def _discover(base_url: str, well_known_name: str) -> dict | None:
    parsed = urllib.parse.urlsplit(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")

    candidates = []
    if path:
        candidates.append(f"{origin}/.well-known/{well_known_name}{path}")
    candidates.append(f"{origin}/.well-known/{well_known_name}")

    for url in candidates:
        print(f"  trying {url} ...")
        result = _get_json(url)
        if result is not None:
            print(f"  found metadata at {url}")
            return result
    return None


def discover_apollo_oauth_config() -> dict:
    print("Discovering Apollo's protected-resource metadata...")
    resource_meta = _discover(config.APOLLO_MCP_URL, "oauth-protected-resource")

    issuers = []
    if resource_meta and resource_meta.get("authorization_servers"):
        issuers = resource_meta["authorization_servers"]
    else:
        origin = urllib.parse.urlsplit(config.APOLLO_MCP_URL)
        issuers = [f"{origin.scheme}://{origin.netloc}"]
        print(
            "  no authorization_servers found in resource metadata; "
            f"falling back to trying the MCP origin itself: {issuers[0]}"
        )

    for issuer in issuers:
        print(f"Discovering authorization-server metadata for {issuer} ...")
        as_meta = _discover(issuer, "oauth-authorization-server")
        if as_meta is None:
            as_meta = _discover(issuer, "openid-configuration")
        if as_meta and as_meta.get("authorization_endpoint") and as_meta.get("token_endpoint"):
            return as_meta

    raise SystemExit(
        "\nCouldn't auto-discover Apollo's OAuth endpoints.\n"
        "Check Apollo's MCP docs for the exact authorization_endpoint / "
        "token_endpoint / registration_endpoint, then either:\n"
        "  - tell me what they are so I can hardcode them, or\n"
        "  - set APOLLO_OAUTH_AUTHORIZATION_ENDPOINT, APOLLO_OAUTH_TOKEN_ENDPOINT,\n"
        "    and (if available) APOLLO_OAUTH_REGISTRATION_ENDPOINT in .env and\n"
        "    re-run this script (env overrides are checked first — see below)."
    )


def register_client(registration_endpoint: str) -> dict:
    print(f"Registering a local OAuth client at {registration_endpoint} ...")
    body = json.dumps(
        {
            "client_name": "NamaSys Lead Generation Agent (local setup)",
            "redirect_uris": [REDIRECT_URI],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",  # public client, PKCE only
            "scope": " ".join(REQUESTED_SCOPES),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        registration_endpoint,
        data=body,
        headers={**_HEADERS, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"Dynamic client registration failed ({e.code}): {e.read().decode('utf-8', 'replace')}\n"
            "Apollo may require a pre-registered OAuth app for this integration type. "
            "Set APOLLO_OAUTH_CLIENT_ID (and APOLLO_OAUTH_CLIENT_SECRET if given one) "
            "in .env and re-run."
        )


_callback_result: dict = {}


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server API)
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        _callback_result["code"] = params.get("code", [None])[0]
        _callback_result["state"] = params.get("state", [None])[0]
        _callback_result["error"] = params.get("error", [None])[0]
        _callback_result["error_description"] = params.get("error_description", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if _callback_result["error"]:
            self.wfile.write(b"<h1>Authorization failed.</h1><p>You can close this tab.</p>")
        else:
            self.wfile.write(b"<h1>Apollo connected.</h1><p>You can close this tab and return to the terminal.</p>")

    def log_message(self, fmt, *args):  # silence default request logging
        pass


def run_authorization_flow(as_meta: dict, client_id: str, client_secret: str | None) -> dict:
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode("ascii")
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    state = secrets.token_urlsafe(24)

    auth_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "resource": config.APOLLO_MCP_URL,
        "scope": " ".join(REQUESTED_SCOPES),
        # Standard OAuth extensions (Google popularized these; several other
        # providers honor them too) that hint the server should issue a
        # refresh_token and force a fresh consent screen rather than silently
        # reusing a prior grant that may not have included one. Harmless if
        # Apollo ignores unrecognized params — RFC 6749 doesn't require
        # rejecting them.
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = as_meta["authorization_endpoint"] + "?" + urllib.parse.urlencode(auth_params)

    print(f"\nOpening your browser to authorize Apollo access:\n  {auth_url}\n")
    print("Log into Apollo and click Allow. Waiting for the redirect...")
    webbrowser.open(auth_url)

    httpd = HTTPServer(("127.0.0.1", REDIRECT_PORT), _CallbackHandler)
    httpd.handle_request()  # blocks until the single /callback request arrives

    if _callback_result.get("error"):
        raise SystemExit(
            f"Apollo returned an authorization error: {_callback_result['error']} "
            f"({_callback_result.get('error_description')})"
        )
    if _callback_result.get("state") != state:
        raise SystemExit("State mismatch on OAuth callback — aborting for safety.")
    code = _callback_result.get("code")
    if not code:
        raise SystemExit("No authorization code received.")

    print("Got authorization code, exchanging it for tokens...")
    token_params = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "code_verifier": code_verifier,
        "resource": config.APOLLO_MCP_URL,
    }
    if client_secret:
        token_params["client_secret"] = client_secret

    req = urllib.request.Request(
        as_meta["token_endpoint"],
        data=urllib.parse.urlencode(token_params).encode("ascii"),
        headers={**_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"Token exchange failed ({e.code}): {e.read().decode('utf-8', 'replace')}"
        )


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY before running this.")
    if not config.VAULT_ID:
        raise SystemExit(
            "NAMASYS_VAULT_ID is not set in .env — run setup_agent.py first."
        )

    override_authz = os.environ.get("APOLLO_OAUTH_AUTHORIZATION_ENDPOINT")
    override_token = os.environ.get("APOLLO_OAUTH_TOKEN_ENDPOINT")
    if override_authz and override_token:
        as_meta = {"authorization_endpoint": override_authz, "token_endpoint": override_token}
        registration_endpoint = os.environ.get("APOLLO_OAUTH_REGISTRATION_ENDPOINT")
    else:
        as_meta = discover_apollo_oauth_config()
        registration_endpoint = as_meta.get("registration_endpoint")

    client_id = os.environ.get("APOLLO_OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("APOLLO_OAUTH_CLIENT_SECRET") or None

    if not client_id:
        if not registration_endpoint:
            raise SystemExit(
                "No registration_endpoint advertised and no APOLLO_OAUTH_CLIENT_ID set.\n"
                "Apollo likely requires a pre-registered OAuth client for this kind of "
                "integration — check their MCP docs for how to obtain a client_id, then "
                "set APOLLO_OAUTH_CLIENT_ID in .env and re-run."
            )
        registration = register_client(registration_endpoint)
        client_id = registration["client_id"]
        client_secret = registration.get("client_secret")
        print(f"  registered client_id = {client_id}")

    tokens = run_authorization_flow(as_meta, client_id, client_secret)

    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in", 3600)
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    print(f"\nToken response: expires_in={expires_in}s, refresh_token={'present' if refresh_token else 'MISSING'}")

    client = anthropic.Anthropic()

    # A vault credential is unique per mcp_server_url — creating a second one
    # for the same Apollo URL 409s. The update endpoint's schema is much
    # narrower than create's: no client_id/token_endpoint fields at all, and
    # token_endpoint_auth only accepts basic/post (not "none") — so a public
    # PKCE client like ours can't cleanly update in place. Worse, patching
    # only what update allows would leave a stored client_id that doesn't
    # match the refresh_token we just got (issued for THIS run's freshly
    # registered client), silently breaking future auto-refresh even if the
    # call itself succeeds. Simpler and correct: archive any existing
    # credential and create a fresh one — client_id, refresh_token, and
    # token_endpoint are always mutually consistent that way, using the
    # same fully-Required, fully-verified create schema every time.
    existing = None
    for cred in client.beta.vaults.credentials.list(config.VAULT_ID):
        if getattr(cred, "display_name", None) == CREDENTIAL_DISPLAY_NAME:
            existing = cred
            break

    auth_payload = {
        "type": "mcp_oauth",
        "mcp_server_url": config.APOLLO_MCP_URL,
        "access_token": access_token,
        "expires_at": expires_at,
    }

    if refresh_token:
        auth_payload["refresh"] = {
            "client_id": client_id,
            "refresh_token": refresh_token,
            "token_endpoint": as_meta["token_endpoint"],
            "token_endpoint_auth": (
                {"type": "client_secret_post", "client_secret": client_secret}
                if client_secret
                else {"type": "none"}
            ),
        }
    else:
        print(
            "\n"
            "=" * 70 + "\n"
            "WARNING: Apollo did NOT return a refresh_token.\n"
            f"This access token expires in {expires_in} seconds ({expires_in // 3600}h) "
            "and CANNOT auto-renew.\n"
            "Every scheduled run (daily/weekly) will start failing with an "
            "'authorization token is invalid or expired' error once that window "
            "passes, and you'll need to re-run apollo_oauth_connect.py manually "
            "each time until this is resolved.\n"
            + "=" * 70
        )

    if existing:
        print(f"Archiving old credential {existing.id} (re-authorizing with a fresh client + token)...")
        client.beta.vaults.credentials.archive(existing.id, vault_id=config.VAULT_ID)

    print("Storing the credential in your vault...")
    client.beta.vaults.credentials.create(
        config.VAULT_ID,
        display_name=CREDENTIAL_DISPLAY_NAME,
        auth=auth_payload,
    )

    print("\nDone — Apollo is connected. You can now run: python main.py --mode daily --no-email")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nCancelled.")
