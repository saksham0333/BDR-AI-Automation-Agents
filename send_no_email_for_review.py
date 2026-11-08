"""
Sends the leads missing a contact email to the lead SDR for review/approval.

These can't go into HubSpot as Contacts yet (HubSpot dedupes Contacts by
email). The SDR reviews the attached CSV, fills in an email where they can
find one (or approves/edits rows as they see fit), and sends it back. Once
you have that reviewed file, run:

  python hubspot_sync.py <reviewed_file.csv>

— any row that now has an email will sync to HubSpot; rows still missing one
are skipped automatically.

Usage:
  python send_no_email_for_review.py                     # most recent *_no_email.csv
  python send_no_email_for_review.py path/to/leads.csv    # a specific CSV
  python send_no_email_for_review.py --dry-run            # show what would be sent, send nothing
  python send_no_email_for_review.py --yes                # skip the confirmation prompt
"""

import argparse
from pathlib import Path

import config
from email_sender import send_no_email_leads_for_review
from save_to_apollo import _read_rows


def _latest_no_email_csv() -> Path:
    candidates = sorted(
        config.LEADS_OUTPUT_DIR.glob("*_no_email.csv"), key=lambda p: p.stat().st_mtime
    )
    if not candidates:
        raise SystemExit(
            f"No *_no_email.csv files found in {config.LEADS_OUTPUT_DIR} — "
            "run split_by_email.py first."
        )
    return candidates[-1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Email the no-email leads to the SDR for review before HubSpot."
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        default=None,
        help="Path to a *_no_email.csv. Defaults to the most recent one.",
    )
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be sent, send nothing."
    )
    args = parser.parse_args()

    csv_path = Path(args.csv_path) if args.csv_path else _latest_no_email_csv()
    if not csv_path.exists():
        raise SystemExit(f"File not found: {csv_path}")

    rows = _read_rows(csv_path)
    print(f"Reading {csv_path}")
    print(f"{len(rows)} leads missing an email\n")

    if not rows:
        print("Nothing to send.")
        return

    for row in rows:
        print(f"  {row.get('Company')} ({row.get('Domain')}) — {row.get('Decision-Maker Name')}")

    if args.dry_run:
        print(f"\n[dry-run] would email {len(rows)} leads to {config.SDR_EMAIL} — nothing sent.")
        return

    if not args.yes:
        answer = input(
            f"\nEmail these {len(rows)} leads to {config.SDR_EMAIL} for review? [y/N] "
        ).strip().lower()
        if answer != "y":
            print("Cancelled — nothing was sent.")
            return

    send_no_email_leads_for_review(csv_path, lead_count=len(rows))


if __name__ == "__main__":
    main()
