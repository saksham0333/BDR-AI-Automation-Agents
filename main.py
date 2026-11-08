"""
End-to-end NamaSys lead-gen run:
  1. Run the Managed Agent session(s) (Apollo MCP search + scoring)
  2. Parse the final markdown table(s) into one deduplicated list
  3. Filter out leads already surfaced in a previous run (see lead_ledger.py)
  4. Write the NEW leads to CSV and email them to the lead SDR

This script never touches Apollo's CRM — it only searches and reads. Saving
qualified leads into Apollo as Accounts/Contacts is a separate, human-approved
step: after reviewing the CSV, run save_to_apollo.py.

Usage:
  python main.py --mode daily          # ICP 2 only — run this one every day
  python main.py --mode icp1           # ICP 1 only — run this one weekly
  python main.py --mode full           # ICP 2 + ICP 1 (two sessions) — run this if you want both at once
  python main.py --mode daily --no-email   # skip the email step (for testing)
"""

import argparse
from datetime import datetime

import config
from csv_writer import dedupe_rows, extract_table_rows, write_csv
from email_sender import send_lead_csv
from lead_ledger import record_run, split_new_vs_seen
from run_leadgen import run_icp1_session, run_icp2_session


def _rows_from_session(agent_text: str, label: str) -> list[dict]:
    rows = extract_table_rows(agent_text)
    if not rows:
        print(f"WARNING: no lead table found in the {label} session's output.")
        print("Raw output was:\n" + agent_text)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the NamaSys lead-gen pipeline.")
    parser.add_argument("--mode", choices=["daily", "icp1", "full"], default="daily")
    parser.add_argument(
        "--no-email", action="store_true", help="Write the CSV but skip sending it."
    )
    args = parser.parse_args()

    print(f"Starting NamaSys lead-gen run — mode={args.mode}")

    rows = []
    if args.mode in ("daily", "full"):
        rows += _rows_from_session(run_icp2_session(), "ICP 2")
    if args.mode in ("icp1", "full"):
        rows += _rows_from_session(run_icp1_session(), "ICP 1")

    rows = dedupe_rows(rows)

    if not rows:
        raise SystemExit("No leads found across all sessions — nothing to email.")

    new_rows, seen_rows = split_new_vs_seen(rows)
    record_run(rows)  # persist everything found this run (new + repeat) either way

    print(
        f"{len(rows)} leads found this run: {len(new_rows)} new, "
        f"{len(seen_rows)} already surfaced in a previous run (excluded below)."
    )

    if not new_rows:
        print("Nothing new to report — every lead found was already surfaced previously.")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    csv_path = config.LEADS_OUTPUT_DIR / f"namasys_leads_{args.mode}_{timestamp}.csv"
    write_csv(new_rows, csv_path)
    print(f"Wrote {len(new_rows)} new leads to {csv_path}")

    if not args.no_email:
        send_lead_csv(csv_path, lead_count=len(new_rows), run_label=args.mode)
    else:
        print("--no-email set, skipping send.")

    print(
        f"\nNothing was saved to Apollo. Review {csv_path.name}, then run:\n"
        f"  python save_to_apollo.py {csv_path}"
    )


if __name__ == "__main__":
    main()
