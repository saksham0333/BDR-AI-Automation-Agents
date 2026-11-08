"""
Step 2 of the pipeline — human-approved CRM save.

main.py only ever produces a CSV; it never touches Apollo. Once you've
reviewed that CSV (and optionally deleted/edited any rows you don't want
saved), run this script to actually push the qualified leads (Score >= 50)
into Apollo as Accounts + linked Contacts.

Usage:
  python save_to_apollo.py                     # uses the most recent CSV in LEADS_OUTPUT_DIR
  python save_to_apollo.py path/to/leads.csv    # uses a specific CSV
  python save_to_apollo.py --yes                # skip the interactive confirmation prompt
"""

import argparse
import csv
from pathlib import Path

import config
from csv_writer import COLUMNS, score_of
from run_leadgen import run_session

SCORE_THRESHOLD = 50


def _latest_csv() -> Path:
    candidates = sorted(
        config.LEADS_OUTPUT_DIR.glob("namasys_leads_*.csv"), key=lambda p: p.stat().st_mtime
    )
    if not candidates:
        raise SystemExit(f"No CSV files found in {config.LEADS_OUTPUT_DIR} — run main.py first.")
    return candidates[-1]


def _read_rows(csv_path: Path) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _format_kickoff(rows: list[dict]) -> str:
    header = "| " + " | ".join(COLUMNS) + " |"
    separator = "|" + "|".join(["---"] * len(COLUMNS)) + "|"
    table_lines = [header, separator]
    for row in rows:
        table_lines.append("| " + " | ".join(row.get(c, "") for c in COLUMNS) + " |")
    table = "\n".join(table_lines)

    return (
        'Save the following pre-approved leads to Apollo now, per the '
        '"Saving to Apollo" section of your system instructions. A human '
        "has already reviewed and approved this exact list — do not "
        "search, enrich, or look up anything new; just save these exact "
        "records as Accounts and linked Contacts.\n\n" + table
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Save approved leads from a CSV into Apollo as Accounts/Contacts."
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        default=None,
        help="Path to the leads CSV. Defaults to the most recent one in the output dir.",
    )
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    args = parser.parse_args()

    csv_path = Path(args.csv_path) if args.csv_path else _latest_csv()
    if not csv_path.exists():
        raise SystemExit(f"File not found: {csv_path}")

    all_rows = _read_rows(csv_path)
    qualified = [row for row in all_rows if score_of(row) >= SCORE_THRESHOLD]
    skipped = len(all_rows) - len(qualified)

    print(f"Reading {csv_path}")
    print(
        f"{len(all_rows)} total leads, {len(qualified)} qualified "
        f"(Score >= {SCORE_THRESHOLD}), {skipped} skipped (low priority)\n"
    )

    if not qualified:
        print("Nothing to save — no leads meet the Score >= 50 bar.")
        return

    for row in qualified:
        dm_name = row.get("Decision-Maker Name", "-")
        dm_title = row.get("Decision-Maker Title", "-")
        dm = f"{dm_name}, {dm_title}" if dm_title and dm_title != "-" else dm_name
        print(f"  [{row.get('Score')}] {row.get('Company')} ({row.get('Domain')}) — {dm}")

    if not args.yes:
        answer = input(
            f"\nSave these {len(qualified)} leads to Apollo as Accounts/Contacts? [y/N] "
        ).strip().lower()
        if answer != "y":
            print("Cancelled — nothing was saved.")
            return

    kickoff = _format_kickoff(qualified)
    result_text = run_session(kickoff, "NamaSys lead gen — save to Apollo")

    print("\n--- Apollo save results ---\n")
    print(result_text)


if __name__ == "__main__":
    main()
