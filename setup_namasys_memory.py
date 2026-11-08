"""
Creates (or reuses) a Managed Agents Memory Store holding NamaSys Analytics'
own company profile, and seeds it with namasys_company_profile.md.

Matches the "check before crawling" pattern: if the profile memory already
exists, this SKIPS writing it again (safe to re-run). Pass --force to
overwrite the existing memory with the current file content instead.

Run this once, then run attach_memory.py is not needed separately — run_leadgen.py
already attaches the store to every session once NAMASYS_MEMORY_STORE_ID is set
in .env. Re-run this script (with --force) whenever you refresh
namasys_company_profile.md.
"""

import argparse
from pathlib import Path

import anthropic

import config

HERE = Path(__file__).parent
PROFILE_FILE = HERE / "namasys_company_profile.md"
PROFILE_PATH = "/namasys_company_profile.md"


def _find_existing_memory(client: anthropic.Anthropic, store_id: str):
    for item in client.beta.memory_stores.memories.list(store_id, path_prefix="/"):
        if getattr(item, "type", None) == "memory" and item.path == PROFILE_PATH:
            return item
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the NamaSys company-profile memory store.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the existing profile memory with the current file content.",
    )
    args = parser.parse_args()

    content = PROFILE_FILE.read_text(encoding="utf-8")
    client = anthropic.Anthropic()

    if config.MEMORY_STORE_ID:
        store_id = config.MEMORY_STORE_ID
        print(f"Reusing existing memory store {store_id}")
    else:
        store = client.beta.memory_stores.create(
            name="NamaSys Company Knowledge",
            description=(
                "NamaSys Analytics' own services, differentiators, target "
                "industries, and ICP guidance. Read this before judging lead "
                "fit, especially for ICP 1."
            ),
        )
        store_id = store.id
        print(f"Created memory store {store_id}")

    existing = _find_existing_memory(client, store_id)

    if existing and not args.force:
        print(
            f"{PROFILE_PATH} already exists in the store — skipping "
            "(per the check-before-crawling rule). Re-run with --force to overwrite."
        )
    elif existing and args.force:
        client.beta.memory_stores.memories.update(
            existing.id, memory_store_id=store_id, content=content
        )
        print(f"Overwrote {PROFILE_PATH} with the latest file content.")
    else:
        client.beta.memory_stores.memories.create(store_id, path=PROFILE_PATH, content=content)
        print(f"Wrote {PROFILE_PATH}")

    if not config.MEMORY_STORE_ID:
        print(f"\nAdd to .env: NAMASYS_MEMORY_STORE_ID={store_id}")


if __name__ == "__main__":
    main()
