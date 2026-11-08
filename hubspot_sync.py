"""
Pushes leads from a CSV into HubSpot, with all the NamaSys-specific context
(ICP, score, fit reasoning, hiring signal, LinkedIn, source) attached as a
Note.

  - Row HAS an email  -> Company + Contact, associated, Note on both.
  - Row has NO email   -> Company only (Contacts need a stable dedupe key,
    and email is it — creating one without email risks a duplicate Contact
    every time this script re-runs). The decision-maker's name/title still
    isn't lost: it's written into the Note, attached to the Company alone.

This is a plain REST integration against HubSpot's CRM API — no Managed
Agent, no LLM involved, since it's a deterministic CSV-to-API mapping. Built
against HubSpot's documented v3/v4 CRM API but NOT live-tested against a real
HubSpot portal (unlike the Apollo scripts, which were verified live) — run
with --dry-run first, and test on a small batch before trusting it fully.

Requires a HubSpot Private App access token in .env (HUBSPOT_ACCESS_TOKEN).
Create one at: HubSpot -> Settings -> Integrations -> Private Apps -> Create.
Scopes needed: crm.objects.contacts.read, crm.objects.contacts.write,
crm.objects.companies.read, crm.objects.companies.write,
crm.objects.notes.write.

Companies are upserted by domain, Contacts by email — safe to re-run, it
updates existing records rather than duplicating them.

Point this at any of:
  - the *_with_email.csv from split_by_email.py
  - an SDR-reviewed *_no_email.csv (see send_no_email_for_review.py) — rows
    the SDR approved (with or without having found an email) sync as
    Company+Contact or Company-only respectively; delete any row the SDR
    did NOT approve before running this
  - a CSV mixing both — each row is handled based on whether IT has an email

Usage:
  python hubspot_sync.py                          # most recent *_with_email.csv
  python hubspot_sync.py path/to/leads.csv         # a specific CSV
  python hubspot_sync.py --dry-run                 # show what would be sent, make no API calls
  python hubspot_sync.py --yes                      # skip the confirmation prompt
"""

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import config
from save_to_apollo import _read_rows

HUBSPOT_API_BASE = "https://api.hubapi.com"


def _latest_with_email_csv() -> Path:
    candidates = sorted(
        config.LEADS_OUTPUT_DIR.glob("*_with_email.csv"),
        key=lambda p: p.stat().st_mtime,
    )
    if not candidates:
        raise SystemExit(
            f"No *_with_email.csv files found in {config.LEADS_OUTPUT_DIR} — "
            "run split_by_email.py first (or pass a specific CSV path)."
        )
    return candidates[-1]


def _hubspot_request(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        HUBSPOT_API_BASE + path,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={
            "Authorization": f"Bearer {config.HUBSPOT_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"HubSpot API error {e.code} on {method} {path}: {detail}")


def _first_or_none(name: str, row: dict) -> str | None:
    value = (row.get(name) or "").strip()
    return None if not value or value == "-" else value


def _find_company_by_domain(domain: str) -> str | None:
    result = _hubspot_request(
        "POST",
        "/crm/v3/objects/companies/search",
        {
            "filterGroups": [
                {"filters": [{"propertyName": "domain", "operator": "EQ", "value": domain}]}
            ],
            "properties": ["domain"],
            "limit": 1,
        },
    )
    results = result.get("results") or []
    return results[0]["id"] if results else None


def upsert_company(row: dict) -> str:
    # Companies can't upsert by "domain" via the batch/upsert endpoint — that
    # endpoint requires the idProperty to have unique-value enforcement
    # turned on, and HubSpot's built-in "domain" property doesn't allow that
    # to be enabled from the property editor (confirmed live: the checkbox
    # is disabled since it's a HubSpot-provided property). So we search by
    # domain first, then PATCH the existing record or POST a new one —
    # equivalent behavior, just not routed through the upsert endpoint.
    domain = row["Domain"].strip()
    properties = {"name": row.get("Company", "").strip(), "domain": domain}
    country = _first_or_none("Country", row)
    if country:
        properties["country"] = country

    existing_id = _find_company_by_domain(domain)
    if existing_id:
        _hubspot_request(
            "PATCH", f"/crm/v3/objects/companies/{existing_id}", {"properties": properties}
        )
        return existing_id

    result = _hubspot_request(
        "POST", "/crm/v3/objects/companies", {"properties": properties}
    )
    return result["id"]


def upsert_contact(row: dict) -> str:
    email = row["Email"].strip()
    full_name = (row.get("Decision-Maker Name") or "").strip()
    if " " in full_name:
        firstname, lastname = full_name.split(" ", 1)
    else:
        firstname, lastname = full_name, ""

    properties = {"email": email, "firstname": firstname, "lastname": lastname}
    title = _first_or_none("Decision-Maker Title", row)
    if title:
        properties["jobtitle"] = title

    result = _hubspot_request(
        "POST",
        "/crm/v3/objects/contacts/batch/upsert",
        {"inputs": [{"idProperty": "email", "id": email, "properties": properties}]},
    )
    return result["results"][0]["id"]


def associate_default(from_object: str, from_id: str, to_object: str, to_id: str) -> None:
    _hubspot_request(
        "PUT",
        f"/crm/v4/objects/{from_object}/{from_id}/associations/default/{to_object}/{to_id}",
    )


def _build_note_body(row: dict, has_email: bool) -> str:
    lines = [f"NamaSys Lead Generation Agent — {row.get('ICP', '')} — Score {row.get('Score', '')}"]

    if not has_email:
        # No Contact record exists for this row, so the decision-maker's
        # identity would otherwise be lost — carry it in the note instead.
        name = _first_or_none("Decision-Maker Name", row)
        title = _first_or_none("Decision-Maker Title", row)
        if name or title:
            who = " — ".join(p for p in (name, title) if p)
            lines.append(f"Decision-maker (no email found): {who}")

    overview = _first_or_none("Company Overview", row)
    if overview:
        lines.append(f"Company Overview: {overview}")
    namasys_fit = _first_or_none("NamaSys Fit", row)
    if namasys_fit:
        lines.append(f"NamaSys Fit: {namasys_fit}")
    fit_reason = _first_or_none("Fit Reason", row)
    if fit_reason:
        lines.append(f"Fit Reason: {fit_reason}")
    hiring_for = _first_or_none("Hiring For", row)
    if hiring_for:
        lines.append(f"Hiring For: {hiring_for}")
    posting_age = _first_or_none("Posting Age", row)
    if posting_age:
        lines.append(f"Posting Age: {posting_age}")

    lines.append(f"Score Breakdown: {row.get('Score Breakdown', '')}")

    linkedin = _first_or_none("LinkedIn", row)
    if linkedin:
        lines.append(f"LinkedIn: {linkedin}")

    lines.append(f"Source: {row.get('Source', '')}")
    return "\n".join(lines)


def create_note(body_text: str, company_id: str, contact_id: str | None) -> str:
    result = _hubspot_request(
        "POST",
        "/crm/v3/objects/notes",
        {
            "properties": {
                "hs_note_body": body_text,
                "hs_timestamp": str(int(time.time() * 1000)),
            }
        },
    )
    note_id = result["id"]
    associate_default("notes", note_id, "companies", company_id)
    if contact_id:
        associate_default("notes", note_id, "contacts", contact_id)
    return note_id


def sync_row(row: dict, dry_run: bool) -> None:
    has_email = bool(_first_or_none("Email", row))
    label = f"{row.get('Company')} ({row.get('Domain')})"
    if has_email:
        label += f" — {row.get('Decision-Maker Name')} <{row.get('Email')}>"
    else:
        label += " — no email, Company-only"

    if dry_run:
        kind = "Company + Contact + Note" if has_email else "Company + Note (no Contact)"
        print(f"  [dry-run] would upsert {kind} for: {label}")
        return

    company_id = upsert_company(row)
    contact_id = None
    if has_email:
        contact_id = upsert_contact(row)
        associate_default("contacts", contact_id, "companies", company_id)
    create_note(_build_note_body(row, has_email), company_id, contact_id)

    if has_email:
        print(f"  synced: {label} (company={company_id}, contact={contact_id})")
    else:
        print(f"  synced (company-only): {label} (company={company_id})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync leads from a CSV into HubSpot.")
    parser.add_argument(
        "csv_path",
        nargs="?",
        default=None,
        help="Path to a leads CSV. Defaults to the most recent *_with_email.csv.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print what would be sent, make no API calls."
    )
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    args = parser.parse_args()

    csv_path = Path(args.csv_path) if args.csv_path else _latest_with_email_csv()
    if not csv_path.exists():
        raise SystemExit(f"File not found: {csv_path}")

    rows = _read_rows(csv_path)
    rows = [r for r in rows if _first_or_none("Domain", r)]
    with_email = [r for r in rows if _first_or_none("Email", r)]
    without_email = [r for r in rows if not _first_or_none("Email", r)]

    print(f"Reading {csv_path}")
    print(
        f"{len(rows)} leads to sync: {len(with_email)} with email "
        f"(Company + Contact), {len(without_email)} without (Company only)\n"
    )

    if not rows:
        print("Nothing to sync.")
        return

    for row in rows:
        tag = row.get("Email") if _first_or_none("Email", row) else "no email"
        print(f"  {row.get('Company')} ({row.get('Domain')}) — {tag}")

    if not args.dry_run:
        config.require_hubspot_config()
        if not args.yes:
            answer = input(f"\nSync these {len(rows)} leads to HubSpot? [y/N] ").strip().lower()
            if answer != "y":
                print("Cancelled — nothing was synced.")
                return

    print()
    failures = []
    for row in rows:
        try:
            sync_row(row, args.dry_run)
        except Exception as e:
            print(f"  FAILED: {row.get('Company')} — {e}")
            failures.append(row.get("Company"))

    print(f"\nDone. {len(rows) - len(failures)}/{len(rows)} succeeded.")
    if failures:
        print(f"Failed: {', '.join(failures)}")


if __name__ == "__main__":
    main()
