"""Parse the agent's markdown lead table and write it out as a CSV."""

import csv
import re
from pathlib import Path

COLUMNS = [
    "Company",
    "Domain",
    "Country",
    "Employees",
    "ICP",
    "Company Overview",       # ICP 1 only — what the company does, size/stage, revenue
    "NamaSys Fit",            # ICP 1 only — the specific pain point + which NamaSys capability solves it
    "Fit Reason",             # ICP 2 only — why the hiring signal matters
    "Hiring For",             # ICP 2 only — role(s) being hired
    "Posting Age",            # ICP 2 only
    "Decision-Maker Name",
    "Decision-Maker Title",
    "Email",
    "LinkedIn",
    "Score",
    "Score Breakdown",
    "Source",
]

_SEPARATOR_ROW = re.compile(r"^\|?[\s:|-]+\|?$")


def _split_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def extract_table_rows(agent_text: str) -> list[dict]:
    """Find the last markdown pipe-table in the agent's output and return it as rows.

    Uses the LAST table block in the text (the agent's final answer), so it's
    resilient to any narration or intermediate tables emitted earlier in the run.
    """
    lines = agent_text.splitlines()
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if "|" in line and line.strip():
            current.append(line)
        else:
            if current:
                blocks.append(current)
            current = []
    if current:
        blocks.append(current)

    if not blocks:
        return []

    table = blocks[-1]
    if len(table) < 2:
        return []

    data_lines = [line for line in table[1:] if not _SEPARATOR_ROW.match(line.strip())]

    rows = []
    for line in data_lines:
        cells = _split_row(line)
        row = {col: (cells[i] if i < len(cells) else "") for i, col in enumerate(COLUMNS)}
        rows.append(row)
    return rows


def score_of(row: dict) -> int:
    try:
        return int(re.sub(r"[^\d-]", "", row.get("Score", "")) or 0)
    except ValueError:
        return 0


def dedupe_rows(rows: list[dict]) -> list[dict]:
    """Dedupe across multiple sessions' results by domain, keeping the
    higher-scoring row for any domain that shows up more than once (e.g. a
    company that qualifies for both ICP 1 and ICP 2 when run as two sessions).
    """
    best_by_domain: dict[str, dict] = {}
    for row in rows:
        domain = (row.get("Domain") or "").strip().lower()
        key = domain or f"__no_domain_{id(row)}"
        existing = best_by_domain.get(key)
        if existing is None or score_of(row) > score_of(existing):
            best_by_domain[key] = row
    return list(best_by_domain.values())


def write_csv(rows: list[dict], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return output_path
