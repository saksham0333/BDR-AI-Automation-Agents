"""
Tracks which leads (by domain) have already been surfaced by a previous run,
so main.py can exclude them from a fresh CSV/email instead of re-showing the
same companies every day/week.

This is a permanent, append-only local ledger — once a domain is seen, it's
excluded from future output by default (it never expires). The underlying
Apollo search will keep finding it every run since Apollo itself doesn't know
about our CSVs; this ledger is what actually prevents you from seeing (and
emailing) the same lead over and over.

Note this is separate from Apollo-side deduplication: Apollo already treats
"Account/Contact already exists" as a no-op success when save_to_apollo.py
runs (see the agent's "Saving to Apollo" instructions) — that protects the
CRM. This ledger protects the CSV/email output from repeating itself.
"""

import csv
from datetime import date
from pathlib import Path

LEDGER_PATH = Path(__file__).parent / "state" / "seen_leads.csv"
LEDGER_COLUMNS = [
    "Domain",
    "Company",
    "First Seen",
    "Last Seen",
    "Times Seen",
    "Latest Score",
    "Latest ICP",
]


def _load_ledger() -> dict[str, dict]:
    if not LEDGER_PATH.exists():
        return {}
    with open(LEDGER_PATH, newline="", encoding="utf-8") as f:
        return {
            row["Domain"].strip().lower(): row
            for row in csv.DictReader(f)
            if row.get("Domain")
        }


def _write_ledger(entries: dict[str, dict]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LEDGER_COLUMNS)
        writer.writeheader()
        for entry in entries.values():
            writer.writerow(entry)


def split_new_vs_seen(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (new_rows, already_seen_rows) based on the persistent ledger."""
    ledger = _load_ledger()
    new_rows, seen_rows = [], []
    for row in rows:
        domain = (row.get("Domain") or "").strip().lower()
        if domain and domain in ledger:
            seen_rows.append(row)
        else:
            new_rows.append(row)
    return new_rows, seen_rows


def record_run(rows: list[dict]) -> None:
    """Updates the ledger with every lead found this run — new or repeat —
    so Last Seen / Times Seen / Latest Score stay current."""
    ledger = _load_ledger()
    today = date.today().isoformat()
    for row in rows:
        domain = (row.get("Domain") or "").strip().lower()
        if not domain:
            continue
        existing = ledger.get(domain)
        if existing:
            existing["Last Seen"] = today
            existing["Times Seen"] = str(int(existing.get("Times Seen") or 1) + 1)
            existing["Latest Score"] = row.get("Score", existing.get("Latest Score", ""))
            existing["Latest ICP"] = row.get("ICP", existing.get("Latest ICP", ""))
        else:
            ledger[domain] = {
                "Domain": row.get("Domain", ""),
                "Company": row.get("Company", ""),
                "First Seen": today,
                "Last Seen": today,
                "Times Seen": "1",
                "Latest Score": row.get("Score", ""),
                "Latest ICP": row.get("ICP", ""),
            }
    _write_ledger(ledger)
