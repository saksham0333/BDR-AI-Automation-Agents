"""Shared configuration loaded from environment / .env for the NamaSys lead-gen pipeline."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


# Anthropic
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Managed Agent resources (populated by setup_agent.py)
AGENT_ID = os.environ.get("NAMASYS_AGENT_ID", "")
AGENT_VERSION = os.environ.get("NAMASYS_AGENT_VERSION", "")
ENVIRONMENT_ID = os.environ.get("NAMASYS_ENVIRONMENT_ID", "")
VAULT_ID = os.environ.get("NAMASYS_VAULT_ID", "")
MEMORY_STORE_ID = os.environ.get("NAMASYS_MEMORY_STORE_ID", "")

# Apollo MCP (OAuth-based — no API key; see apollo_oauth_connect.py)
APOLLO_MCP_URL = os.environ.get("APOLLO_MCP_URL", "https://mcp.apollo.io/mcp")

# Output
LEADS_OUTPUT_DIR = Path(os.environ.get("LEADS_OUTPUT_DIR", "./output"))

# Email
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USERNAME)
SDR_EMAIL = os.environ.get("SDR_EMAIL", "")

# HubSpot (Private App access token — Settings -> Integrations -> Private Apps)
HUBSPOT_ACCESS_TOKEN = os.environ.get("HUBSPOT_ACCESS_TOKEN", "")


def require_runtime_config() -> None:
    """Fail fast with a clear message if anything run_leadgen.py needs is missing."""
    for name in (
        "ANTHROPIC_API_KEY",
        "NAMASYS_AGENT_ID",
        "NAMASYS_ENVIRONMENT_ID",
        "NAMASYS_VAULT_ID",
    ):
        _require(name)


def require_email_config() -> None:
    for name in ("SMTP_USERNAME", "SMTP_PASSWORD", "SDR_EMAIL"):
        _require(name)


def require_hubspot_config() -> None:
    _require("HUBSPOT_ACCESS_TOKEN")
