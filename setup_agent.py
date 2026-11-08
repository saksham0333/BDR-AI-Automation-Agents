"""
ONE-TIME SETUP, part 1 of 2 — run this first, then save the printed IDs into
your .env file, then run apollo_oauth_connect.py to finish connecting Apollo.

Applies namasys_leadgen.environment.yaml and namasys_leadgen.agent.yaml (the
same way `ant beta:environments create < file.yaml` / `ant beta:agents create
< file.yaml` would) and creates an empty credential vault. It does NOT connect
Apollo yet — Apollo's MCP server requires an interactive OAuth login (see
apollo_oauth_connect.py), which only you can complete in a browser.

Re-running this script creates NEW resources each time — don't run it on every
lead-gen job. If you edit the YAML files later, run update_agent.py instead to
push the change as a new version of the SAME agent.
"""

import os
from pathlib import Path

import anthropic
import yaml
from dotenv import load_dotenv

load_dotenv()

HERE = Path(__file__).parent
ENVIRONMENT_YAML = HERE / "namasys_leadgen.environment.yaml"
AGENT_YAML = HERE / "namasys_leadgen.agent.yaml"


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY before running setup.")

    environment_config = yaml.safe_load(ENVIRONMENT_YAML.read_text(encoding="utf-8"))
    agent_config = yaml.safe_load(AGENT_YAML.read_text(encoding="utf-8"))

    client = anthropic.Anthropic()

    print(f"Creating environment from {ENVIRONMENT_YAML.name}...")
    environment = client.beta.environments.create(**environment_config)
    print(f"  environment_id = {environment.id}")

    print("Creating (empty) vault for the Apollo OAuth credential...")
    vault = client.beta.vaults.create(
        display_name="NamaSys Apollo MCP credentials",
    )
    print(f"  vault_id = {vault.id}")

    print(f"Creating the agent from {AGENT_YAML.name}...")
    agent = client.beta.agents.create(**agent_config)
    print(f"  agent_id = {agent.id}")
    print(f"  agent_version = {agent.version}")

    print("\nDone. Add these to your .env file:\n")
    print(f"NAMASYS_AGENT_ID={agent.id}")
    print(f"NAMASYS_AGENT_VERSION={agent.version}")
    print(f"NAMASYS_ENVIRONMENT_ID={environment.id}")
    print(f"NAMASYS_VAULT_ID={vault.id}")
    print(
        "\nNext: after saving those into .env, run apollo_oauth_connect.py to "
        "authorize Apollo access (opens your browser)."
    )


if __name__ == "__main__":
    main()
