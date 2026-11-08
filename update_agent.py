"""
Run this after editing namasys_leadgen.agent.yaml (system prompt, tools, or
MCP config) to push the change as a new version of the SAME agent — without
creating a new agent or losing the agent_id already saved in .env.
"""

from pathlib import Path

import anthropic
import yaml

import config

AGENT_YAML = Path(__file__).parent / "namasys_leadgen.agent.yaml"


def main() -> None:
    config.require_runtime_config()
    agent_config = yaml.safe_load(AGENT_YAML.read_text(encoding="utf-8"))
    agent_config.pop("name", None)  # name isn't updatable; drop it rather than 400

    client = anthropic.Anthropic()

    # Fetch the CURRENT live version rather than trusting .env — if a prior
    # run of this script succeeded but its printed version number was never
    # pasted back into .env, updating against a stale version 409s
    # ("Concurrent modification detected").
    current = client.beta.agents.retrieve(config.AGENT_ID)
    print(f"Current live version: {current.version}")

    updated = client.beta.agents.update(
        config.AGENT_ID,
        version=current.version,
        **agent_config,
    )
    print(f"Updated agent {updated.id} -> version {updated.version}")
    print(f"Update .env: NAMASYS_AGENT_VERSION={updated.version}")


if __name__ == "__main__":
    main()
