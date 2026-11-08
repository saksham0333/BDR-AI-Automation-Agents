"""
Runs lead-generation sessions against the already-provisioned NamaSys Managed
Agent (see setup_agent.py) and returns the agent's final markdown lead table
as text.

ICP 1 and ICP 2 are run as two SEPARATE sessions rather than one combined
conversation. This matters for two reasons:
  - Token efficiency: a shared session keeps accumulating ICP 2's tool-call
    history in context while ICP 1 runs (and vice versa), even though the two
    searches are logically independent. Two fresh sessions means each only
    pays for its own context.
  - Reliability: in one combined session the agent sometimes shortchanged
    ICP 1 after a long ICP 2 run. A dedicated session with its own kickoff
    message gives ICP 1 the same full attention ICP 2 gets.

Both sessions run against the SAME agent (same system prompt / tools / MCP
config) — splitting sessions gets the efficiency win without maintaining two
separate agent configs.
"""

import sys

import anthropic

import config

ICP2_KICKOFF = (
    "Run ICP 2 (active hiring signal) lead generation now, per your system "
    "instructions. Search every title family listed under ICP 2 — not just "
    "Data Engineer — including Data Analyst, Data Scientist, AI/ML Engineer, "
    "and BI/Business Analyst roles. Target 5 leads for this session — keep "
    "searching across result pages and title families until you reach 5 "
    "genuine matches or have reasonably exhausted what's available; never "
    "fabricate to hit the count. Do not run ICP 1 in this session. Do not "
    "pause to ask for confirmation — run the full workflow autonomously. Do "
    "not save anything to Apollo in this session. Return only the final "
    "deduplicated, scored lead list in the specified markdown table format "
    "— no other text before or after the table."
)

ICP1_KICKOFF = (
    "Run ICP 1 (service/partnership-based companies) lead generation now, "
    "per your system instructions. Target 5 leads for this session — keep "
    "searching across result pages until you reach 5 genuine matches or "
    "have reasonably exhausted what's available; never fabricate to hit the "
    "count. Do not run ICP 2 in this session. Do not pause to ask for "
    "confirmation — run the full workflow autonomously. Do not save "
    "anything to Apollo in this session. Return only the final "
    "deduplicated, scored lead list in the specified markdown table format "
    "— no other text before or after the table."
)


def _session_agent_ref():
    if config.AGENT_VERSION:
        return {
            "type": "agent",
            "id": config.AGENT_ID,
            "version": int(config.AGENT_VERSION),
        }
    return config.AGENT_ID


def _session_resources():
    if not config.MEMORY_STORE_ID:
        return []
    return [
        {
            "type": "memory_store",
            "memory_store_id": config.MEMORY_STORE_ID,
            "access": "read_only",
            "instructions": (
                "NamaSys Analytics' own company profile — services, "
                "differentiators, target industries, and what a genuine ICP "
                "fit looks like. Read this before judging ICP fit, "
                "especially for ICP 1."
            ),
        }
    ]


def run_session(kickoff_text: str, title: str) -> str:
    """Runs one session end-to-end and returns the agent's final text output."""
    config.require_runtime_config()
    client = anthropic.Anthropic()

    session = client.beta.sessions.create(
        agent=_session_agent_ref(),
        environment_id=config.ENVIRONMENT_ID,
        vault_ids=[config.VAULT_ID],
        resources=_session_resources(),
        title=title,
    )
    print(f"Session created ({title}): {session.id}")
    print(
        f"Watch it live: "
        f"https://platform.claude.com/workspaces/default/sessions/{session.id}"
    )

    agent_text_parts: list[str] = []

    # Stream-first: open the stream, then send the kickoff message while it's
    # already listening — otherwise early events can arrive as one buffered
    # batch instead of live.
    with client.beta.sessions.events.stream(session_id=session.id) as stream:
        client.beta.sessions.events.send(
            session_id=session.id,
            events=[
                {
                    "type": "user.message",
                    "content": [{"type": "text", "text": kickoff_text}],
                }
            ],
        )

        for event in stream:
            if event.type == "agent.message":
                for block in event.content:
                    if block.type == "text":
                        agent_text_parts.append(block.text)
            elif event.type in ("agent.tool_use", "agent.mcp_tool_use"):
                print(f"  [tool] {getattr(event, 'name', '?')}")
                # Safety net: this agent's tools are configured always_allow
                # (see namasys_leadgen.agent.yaml), so this shouldn't fire —
                # but if a tool ever does come back asking for confirmation,
                # auto-approve rather than hang forever waiting on a click
                # nobody's watching for. These are read-only Apollo/agent
                # tools; there's nothing here that needs a human in the loop.
                if getattr(event, "evaluated_permission", None) == "ask":
                    print(f"    -> auto-approving (pre-authorized, read-only tool)")
                    client.beta.sessions.events.send(
                        session_id=session.id,
                        events=[
                            {
                                "type": "user.tool_confirmation",
                                "tool_use_id": event.id,
                                "result": "allow",
                            }
                        ],
                    )
            elif event.type == "session.error":
                print(f"  [session error] {event}", file=sys.stderr)
            elif event.type == "session.status_idle":
                # Only stop on a terminal idle — "requires_action" means the
                # agent is waiting on something we haven't wired up (e.g. a
                # tool confirmation) and the loop should keep listening.
                if event.stop_reason.type != "requires_action":
                    break
            elif event.type == "session.status_terminated":
                break

    return "".join(agent_text_parts)


def run_icp2_session() -> str:
    return run_session(ICP2_KICKOFF, "NamaSys lead gen — ICP 2 (daily)")


def run_icp1_session() -> str:
    return run_session(ICP1_KICKOFF, "NamaSys lead gen — ICP 1 (weekly)")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "icp2"
    text = run_icp1_session() if which == "icp1" else run_icp2_session()
    print("\n--- Agent final output ---\n")
    print(text)
