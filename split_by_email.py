"""
Splits a lead CSV into two files based on whether an email was found —
nothing to do with score:
  - <name>_with_email.csv — has a real email; ready for hubspot_sync.py
  - <name>_no_email.csv   — no email found; goes to the SDR for review via
    send_no_email_for_review.py before it can go into HubSpot (HubSpot
    Contacts are deduped by email, so these can't go in as-is)

This is READ-ONLY against the source CSV — it never modifies, moves, or
touches the original file (including the one save_to_apollo.py uses for
Apollo). Only writes two new derived files alongside it.

Usage:
  python split_by_email.py                     # uses the most recent CSV in LEADS_OUTPUT_DIR
  python split_by_email.py path/to/leads.csv    # uses a specific CSV
"""

import argparse
from pathlib import Path

from csv_writer import COLUMNS, write_csv
from save_to_apollo import _latest_csv, _read_rows


def _has_email(row: dict) -> bool:
    email = (row.get("Email") or "").strip()
    return bool(email) and email != "-"


def split_by_email(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (with_email, without_email) for every row — no score filter."""
    with_email = [r for r in rows if _has_email(r)]
    without_email = [r for r in rows if not _has_email(r)]
    return with_email, without_email


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Split leads into with-email / without-email CSVs."
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        default=None,
        help="Path to the leads CSV. Defaults to the most recent one in the output dir.",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv_path) if args.csv_path else _latest_csv()
    if not csv_path.exists():
        raise SystemExit(f"File not found: {csv_path}")

    rows = _read_rows(csv_path)

    if rows and set(rows[0].keys()) != set(COLUMNS):
        raise SystemExit(
            f"{csv_path.name} doesn't match the current CSV schema — it looks "
            "like it was generated before the column redesign. Re-run main.py "
            "to generate a fresh CSV in the current format, then point this "
            "script at that one."
        )

    with_email, without_email = split_by_email(rows)

    print(f"Reading {csv_path} (read-only — this file is not modified)")
    print(f"{len(rows)} total leads")
    print(f"  {len(with_email)} with an email -> ready for hubspot_sync.py")
    print(f"  {len(without_email)} without an email -> needs SDR review first")

    with_email_path = csv_path.parent / f"{csv_path.stem}_with_email.csv"
    without_email_path = csv_path.parent / f"{csv_path.stem}_no_email.csv"

    write_csv(with_email, with_email_path)
    write_csv(without_email, without_email_path)

    print(f"\nWrote {with_email_path}")
    print(f"Wrote {without_email_path}")

    if without_email:
        print(f"\nNext: python send_no_email_for_review.py {without_email_path}")
    if with_email:
        print(f"Next: python hubspot_sync.py {with_email_path}")


if __name__ == "__main__":
    main()
