# NamaSys Lead Generation Pipeline — Project Handoff Document

**Prepared for:** a fresh AI assistant (or human) with zero memory of the build conversation.
**Ground truth verified against:** actual files on disk as of **2026-08-07**, not just recollection.
**Working directory:** `C:\Users\saksh\OneDrive\Desktop\lead  agent` (note: two spaces between "lead" and "agent" in the folder name — this is real, not a typo, and matters for any path you construct).
**Not a git repository** — there is no version control on this project. Treat file edits as directly mutating the only copy that exists.

---

# Project Overview

This is a Python automation pipeline for **NamaSys Analytics** (an AI-driven GTM/automation service provider) that:

1. Uses a **Claude Managed Agent** (Anthropic's server-hosted agent product) connected to **Apollo.io's MCP server** to search for and qualify B2B sales leads against two Ideal Customer Profiles (ICPs).
2. Produces a structured CSV of leads, deduplicated against everything found in previous runs.
3. Emails that CSV to a lead SDR (Sales Development Rep).
4. Splits leads by whether a contact email was found, so leads without an email can be routed to the SDR for manual review before being pushed anywhere.
5. Can push qualified leads into **Apollo's own CRM** (as Accounts/Contacts) — a separate, human-approved step, never automatic.
6. Can push leads into **HubSpot CRM** (as Companies/Contacts/Notes) — a separate script, built but **not yet live-tested** against a real HubSpot account.

The user (Saksham, `saksham.p@namasys.ai`, personal Gmail `sakshampundeer333@gmail.com` used for SMTP sending) is building this as an internal NamaSys tool, iterating live in a single long conversation, testing against real Apollo/Anthropic accounts throughout.

---

# Objectives

- Automate discovery of two categories of leads for NamaSys, using Apollo.io as the data source:
  - **ICP 1**: companies that are potential **direct customers** of NamaSys — they have an internal operational pain point (no in-house data/AI/automation capability) that NamaSys's own services solve for them. (This definition was **corrected mid-project** — it originally meant "channel/reseller partners." See Design Decisions.)
  - **ICP 2**: companies with an **active hiring signal** — an open job posting for a data/AI-adjacent role — pitched with a "service instead of hire" angle.
- Enrich each lead with a named decision-maker and, critically, their **verified email** (this required a specific fix — see Debugging History).
- Produce a clean, deduplicated, human-readable CSV — not a wall of prose.
- Never silently repeat leads across runs (daily/weekly cadence).
- Keep every write to an external system (Apollo CRM, HubSpot CRM, SDR's inbox) **human-approved**, never automatic — the agent searches and reports; humans decide what gets pushed where.
- Eventually route everything into HubSpot as the system of record, while leaving Apollo CRM writes as a separate, independently-triggered option (not part of the main flow).

---

# Current Status

**Functional and verified (live-tested against real APIs, not just unit-tested):**
- Managed Agent creation/versioning via YAML (`setup_agent.py`, `update_agent.py`) — agent is at **version 12** as of last check.
- Apollo OAuth connection via Dynamic Client Registration + PKCE (`apollo_oauth_connect.py`) — confirmed working end-to-end including refresh-token persistence, after two rounds of real bugs (see Debugging History).
- Core search pipeline (`main.py` → `run_leadgen.py`) — has produced multiple real lead CSVs with real Apollo data (see `output/` — 5 CSVs from Aug 5–6).
- Lead ledger cross-run dedup (`lead_ledger.py`) — has 10 real leads tracked in `state/seen_leads.csv`.
- CSV schema v2 (17 columns, see Database Schema) — verified via multiple live runs and a full schema-consistency audit (last user request in this conversation).
- Email splitting (`split_by_email.py`) — verified.
- Apollo CRM write-back (`save_to_apollo.py`) — built, used, and just had a display bug fixed (see Known Bugs).

**Built but NOT yet live-verified:**
- `hubspot_sync.py` — written against HubSpot's documented v3/v4 REST API from training knowledge, tested only with `--dry-run` against synthetic data. **`HUBSPOT_ACCESS_TOKEN` is currently blank in `.env`** — this script cannot run for real until the user creates a HubSpot Private App and sets that token.
- `send_no_email_for_review.py` — logic verified with `--dry-run`, never actually sent a real email.

**Currently broken / needs attention:**
- **`SMTP_PASSWORD` is blank in `.env` right now.** It was set earlier in the conversation (a Gmail App Password was visible in `.env` at one point) but is empty as of the last file read. Email sending (`main.py` without `--no-email`, and `send_no_email_for_review.py`) will fail with a clear error from `config.require_email_config()` until this is refilled.
- No full pipeline run has happened yet on **agent version 12**, which is the version carrying ALL of: broadened ICP 2 titles, autonomy instructions, retry-on-error instructions, mandatory email-reveal enforcement, the `webhook_result_read` scope fix, the Sonnet 4.6 model change, and the 5-leads-per-ICP target. Every fix was verified individually but not yet in one combined end-to-end real run.

---

# Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.10 | Windows, path has a double-space folder name |
| Shell | PowerShell (primary), Git Bash (used throughout this session for Unix-style tooling) | |
| Agent runtime | **Claude Managed Agents** (Anthropic API, beta) | NOT the Claude Agent SDK, NOT a manual tool-use loop. See Design Decisions for why. |
| Agent model | `claude-sonnet-4-6`, `effort: medium` | Changed from initial `claude-opus-5`. See Design Decisions. |
| Lead data source | **Apollo.io**, via its **MCP server** (`https://mcp.apollo.io/mcp`) | Connected to the Managed Agent as an MCP tool source, not called directly by our Python code |
| Apollo auth | **OAuth 2.0 + PKCE + Dynamic Client Registration** | No API key option exists for Apollo's MCP server — confirmed from Apollo's own docs and live testing |
| Company knowledge | **Managed Agents Memory Store** | One markdown file (`namasys_company_profile.md`) mounted read-only into every session |
| Email | **Gmail SMTP** via Python stdlib `smtplib` | App Password auth |
| HubSpot | **Plain REST** via Python stdlib `urllib` | Deliberately NOT via MCP/agent — see Design Decisions |
| Persistence | **Flat files only** — CSV, YAML, Markdown | No database. See Database Schema. |
| Dependencies | `anthropic`, `python-dotenv`, `pyyaml` (see `requirements.txt`) | Everything else uses Python stdlib (`smtplib`, `urllib`, `csv`, `json`, `http.server`, `webbrowser`, `base64`, `hashlib`, `secrets`, `argparse`) |

---

# Architecture

## The Managed Agents object model (how this project uses it)

Anthropic's Managed Agents product has four persistent object types, all created via `client.beta.*`:

```
Agent (versioned config: model, system prompt, tools, MCP servers)
  └── created once, updated in place (new version each time) — NEVER recreated
Environment (sandbox template: networking config)
  └── created once, reused by every session
Vault (credential container)
  └── created once; holds ONE credential: the Apollo OAuth token (+ refresh)
Memory Store (persistent cross-session file storage)
  └── created once; holds ONE file: namasys_company_profile.md

Session (an actual running conversation with the agent)
  └── created FRESH every single pipeline run — never reused
  └── references the Agent (by ID+version), the Environment, the Vault, the Memory Store
```

**Critical mental model:** the Agent/Environment/Vault/Memory Store are set up **once** (via `setup_agent.py` + `setup_namasys_memory.py` + `apollo_oauth_connect.py`) and their IDs are stored in `.env`. Every actual lead-gen run (`main.py`, `save_to_apollo.py`) creates a **new Session** against those same stored IDs. This is documented in Anthropic's own Managed Agents guidance as the correct pattern — the anti-pattern (which this project avoids) is calling `agents.create()` on every run.

## Two sessions per ICP, not one combined session

`run_leadgen.py` exposes `run_icp1_session()` and `run_icp2_session()` as two **independent** Managed Agent sessions, each with its own kickoff message, each starting with zero prior context. `main.py --mode full` calls both and merges the results in Python (not in the agent's own context). This was a deliberate architecture decision — see Design Decisions §3.

## Pipeline stages (data flow)

```
┌─────────────┐
│  main.py    │  --mode {daily|icp1|full}
└──────┬──────┘
       │ runs 1 or 2 Managed Agent sessions (via run_leadgen.py)
       │ agent searches Apollo via MCP, scores leads, returns ONE markdown table per session
       ▼
  csv_writer.extract_table_rows()   — parses the markdown table into row dicts
  csv_writer.dedupe_rows()          — dedupes by domain, keeps higher score
  lead_ledger.split_new_vs_seen()   — filters out leads already surfaced in ANY previous run
  lead_ledger.record_run()          — updates the permanent ledger with everything found this run
       ▼
  csv_writer.write_csv()  →  output/namasys_leads_{mode}_{timestamp}.csv   (NEW leads only)
       ▼
  email_sender.send_lead_csv()  →  emails the CSV to SDR_EMAIL
       │
       │  (main.py's job ends here — it NEVER touches Apollo CRM or HubSpot)
       ▼
┌──────────────────┐
│ split_by_email.py │  reads the CSV (or any CSV), READ-ONLY, splits by whether Email column is populated
└─────────┬─────────┘
          ├──────────────────────────┐
          ▼                          ▼
  *_with_email.csv           *_no_email.csv
          │                          │
          ▼                          ▼
  ┌────────────────┐      ┌──────────────────────────┐
  │ hubspot_sync.py │      │ send_no_email_for_review.py │
  └────────┬────────┘      └──────────────┬───────────┘
           │                              │ emails CSV to SDR for manual review/edit
           │                              ▼
           │                    (SDR edits, approves rows, sends back —
           │                     this handoff is OUTSIDE the automation,
           │                     happens over email/Slack/however the
           │                     team normally shares files)
           │                              │
           │◄─────────────────────────────┘
           │  (SDR-approved file, possibly still missing emails on some rows,
           │   pointed at hubspot_sync.py manually)
           ▼
     HubSpot CRM (Companies + Contacts-if-email + Notes)


┌────────────────────┐
│ save_to_apollo.py   │  SEPARATE, independently-triggered. Reads a CSV,
└──────────┬──────────┘  filters to Score >= 50, shows preview, asks [y/N],
           │              then opens a NEW Managed Agent session with a
           │              "Saving to Apollo" kickoff (agent does NOT search —
           ▼              just saves the exact given records via Apollo's
     Apollo CRM            Accounts/Contacts create tools)
```

## Two distinct "save to CRM" flows — do not confuse them

1. **Apollo CRM** (`save_to_apollo.py`): triggered manually by the user on ANY csv, filters to `Score >= 50` internally, sends the approved rows to a **Managed Agent session** (the same NamaSys agent, but with a "Saving to Apollo" kickoff message instead of a search kickoff — the agent's system prompt has a dedicated `## Saving to Apollo` section gated on "only when explicitly instructed").
2. **HubSpot CRM** (`hubspot_sync.py`): triggered manually by the user on the `*_with_email.csv` or an SDR-approved file. Does **NOT** use a Managed Agent at all — it's plain deterministic Python making REST calls directly to HubSpot's API. No score filter (any row in the file gets processed; filtering to "good" leads is expected to have already happened via the split + SDR review).

---

# Directory Structure

```
lead  agent/                          (working dir — note double space in folder name)
├── .env                              # real secrets, NOT in version control (no git repo at all)
├── .env.example                      # template — keeps getting overwritten to .env when user copies it (see Constraints)
├── requirements.txt                  # anthropic, python-dotenv, pyyaml
├── HANDOFF.md                        # this file
│
├── namasys_leadgen.agent.yaml        # THE agent config — source of truth, applied via setup_agent.py/update_agent.py
├── namasys_leadgen.environment.yaml  # Managed Agents environment config
├── namasys_company_profile.md        # content of the Memory Store — NamaSys's own company profile
│
├── config.py                         # loads .env, exposes constants + require_*_config() validators
├── setup_agent.py                    # ONE-TIME: creates environment + vault + agent from the YAML files
├── update_agent.py                   # run after editing the agent YAML — pushes a new agent VERSION
├── setup_namasys_memory.py           # ONE-TIME: creates the memory store, seeds it from namasys_company_profile.md
├── apollo_oauth_connect.py           # ONE-TIME (or re-run to reconnect): OAuth dance with Apollo, stores token in vault
│
├── run_leadgen.py                    # core session-runner: run_icp1_session(), run_icp2_session()
├── main.py                           # CLI entry point: --mode {daily,icp1,full} — the main pipeline
├── csv_writer.py                     # CSV schema (COLUMNS), markdown-table parser, dedupe, write
├── lead_ledger.py                    # cross-run "have we seen this lead before" tracking
├── email_sender.py                   # SMTP sending (two functions: main leads, no-email-review leads)
│
├── split_by_email.py                 # splits a CSV into *_with_email.csv / *_no_email.csv
├── send_no_email_for_review.py       # emails the no-email CSV to the SDR
├── hubspot_sync.py                   # pushes a CSV into HubSpot (plain REST, no agent)
├── save_to_apollo.py                 # human-approved write-back into Apollo CRM (uses a Managed Agent session)
│
├── output/                           # generated lead CSVs, timestamped, never overwritten
│   ├── namasys_leads_daily_2026-08-06_1811.csv
│   ├── namasys_leads_full_2026-08-05_1910.csv
│   ├── namasys_leads_full_2026-08-06_1417.csv   ← OLD SCHEMA (pre-redesign), will error split_by_email.py's schema check
│   ├── namasys_leads_full_2026-08-06_1658.csv
│   └── namasys_leads_full_2026-08-06_1731.csv
│
└── state/
    └── seen_leads.csv                # the permanent lead ledger (10 real leads tracked as of last check)
```

**Files intentionally deleted during the project** (superseded, not just unused): `system_prompt.py` (replaced by the YAML's `system:` block), `split_score100.py` (replaced by `split_by_email.py` after the user corrected the split criteria from score-based to email-based).

---

# Key Files and Their Purpose

| File | Purpose | Run how often |
|---|---|---|
| `namasys_leadgen.agent.yaml` | **The single source of truth** for the agent's entire behavior — role, ICP definitions, workflow steps, scoring rubric, output format, guardrails, model, tools, MCP servers. Edit this, then run `update_agent.py` to push live. | Edited whenever behavior needs to change |
| `namasys_leadgen.environment.yaml` | Trivial — just `{name, config: {type: cloud, networking: {type: unrestricted}}}` | Rarely touched |
| `namasys_company_profile.md` | Plain-language NamaSys company profile (services, differentiators, target industries, "what good ICP 1 fit looks like") — mounted into every session as read-only reference material | Edit + re-run `setup_namasys_memory.py --force` if NamaSys's business description changes |
| `config.py` | Loads `.env` via `python-dotenv`; every other script imports constants from here. Has `require_runtime_config()`, `require_email_config()`, `require_hubspot_config()` — call these before using the relevant subsystem, they raise a clear error listing exactly what's missing. | N/A — imported everywhere |
| `setup_agent.py` | One-time (or full-reset) provisioning: creates Environment + Vault + Agent from the YAML files, prints the IDs to paste into `.env`. **Idempotent is false — re-running creates NEW resources**, it does not detect/reuse existing ones. | Once, or on a full teardown/rebuild |
| `update_agent.py` | Re-reads the agent YAML, fetches the **current live version** from the API first (not from `.env` — this was a real bug fix, see Debugging History), pushes an update, prints the new version to paste into `.env` | After every edit to `namasys_leadgen.agent.yaml` |
| `setup_namasys_memory.py` | Creates (or reuses, via `--force` to overwrite) the memory store; checks if the profile file already exists before writing (matches user's "check before crawling" requirement) | Once, or when `namasys_company_profile.md` content changes |
| `apollo_oauth_connect.py` | The most complex script in the project. Discovers Apollo's OAuth endpoints via RFC 9728/8414 metadata, dynamically registers an OAuth client (RFC 7591), runs a local PKCE authorization-code flow (opens the user's real browser, catches the redirect on `127.0.0.1:8765`), then stores the resulting access+refresh token in the Vault. See Debugging History for the two real bugs found and fixed here. | Once, or whenever OAuth scopes change, or if the token/refresh chain ever breaks |
| `run_leadgen.py` | Defines `ICP1_KICKOFF` / `ICP2_KICKOFF` prompt text, `run_session(kickoff_text, title)` (the core session-runner, streams events, auto-approves any tool confirmation, handles `session.status_idle`/`terminated`), and the two public wrappers `run_icp1_session()`/`run_icp2_session()` | Imported by `main.py` and `save_to_apollo.py` |
| `main.py` | CLI entry point. `--mode {daily,icp1,full}`, `--no-email`. Runs session(s), parses, dedupes, ledger-filters, writes CSV, emails, prints next-step hints. | Every day (`--mode daily`) / every week (`--mode icp1` or `--mode full`) |
| `csv_writer.py` | **The canonical CSV schema lives here as `COLUMNS`.** Also: `extract_table_rows()` (markdown → dicts), `score_of()` (robust score parsing), `dedupe_rows()`, `write_csv()`. | Imported everywhere |
| `lead_ledger.py` | `state/seen_leads.csv` — a **separate, intentionally different schema** from the lead CSVs (tracks Domain/Company/First Seen/Last Seen/Times Seen/Latest Score/Latest ICP). `split_new_vs_seen()` and `record_run()`. **No expiry — once a domain is seen, it is excluded from output forever** (a deliberate v1 choice — see Design Decisions and Remaining Tasks). | Imported by `main.py` |
| `email_sender.py` | Two functions: `send_lead_csv()` (main daily/weekly notification) and `send_no_email_leads_for_review()` (the review-request email). Both go through a shared `_send_email_with_attachment()` helper. | Imported by `main.py` and `send_no_email_for_review.py` |
| `split_by_email.py` | Read-only against its source CSV. Splits into `*_with_email.csv` / `*_no_email.csv` based **purely on whether the Email column is populated — NOT on score** (this was corrected mid-project, see Design Decisions). Has a schema-mismatch guard that fails loudly on old-format CSVs. | After every `main.py` run you want to route onward |
| `send_no_email_for_review.py` | Emails a `*_no_email.csv` to the SDR with instructions to fill in/approve/reject rows. Has `--dry-run` and `--yes` flags. | After `split_by_email.py`, when there are no-email leads worth chasing |
| `hubspot_sync.py` | The HubSpot integration. Upserts Company (by domain) always; upserts Contact (by email) only if the row has one; associates them; attaches a Note with all the rich NamaSys-specific context that doesn't map to standard HubSpot fields. **Handles mixed files** — a CSV with some rows having email and some not is fine, each row is handled on its own merits. | After SDR review, or directly on `*_with_email.csv` |
| `save_to_apollo.py` | Reads a CSV, filters `Score >= 50`, shows a preview (recently bug-fixed — see Known Bugs), asks `[y/N]`, then opens a dedicated Managed Agent session instructing it to save exactly those records (no new searching) into Apollo as Accounts/Contacts. | Whenever the user wants to push qualified leads into Apollo's own CRM |

---

# Features Implemented

- [x] Managed Agent provisioned from version-controlled YAML (not ad-hoc API calls)
- [x] Apollo MCP server connected via OAuth 2.0 (PKCE + Dynamic Client Registration, no pre-registered app needed)
- [x] Auto-refresh of the Apollo OAuth token (30-day access token + refresh token, confirmed working)
- [x] Least-privilege OAuth scopes (18 explicit scopes, verified against Apollo's live discovery endpoint — nothing extra, nothing missing for what the agent actually does)
- [x] Two ICP definitions, each with its own scoring rubric (0–100, transparent breakdown)
- [x] ICP 2 title-family broadening (Data Engineer, Data Analyst, Data Scientist, AI/ML Engineer, BA/BI Analyst — not just "Data Engineer")
- [x] ICP 1 corrected to "direct customer" framing (not partnership/reseller)
- [x] Company-knowledge Memory Store (read-only, mounted every session) grounding ICP 1 judgment in NamaSys's actual service catalog
- [x] Two independent sessions per full run (ICP 1, ICP 2) instead of one combined session
- [x] 5-leads-per-session target (down from an earlier 15; user-specified)
- [x] Mandatory email-reveal enrichment step (Apollo's "waterfall" email finder) — was previously always returning blank emails
- [x] `webhook_result_read` OAuth scope for polling the async waterfall enrichment job
- [x] Autonomous execution (agent no longer stops mid-run to ask "do you want to proceed?")
- [x] Retry-on-transient-tool-error instruction
- [x] `always_allow` permission policy on the built-in tool set + a client-side auto-approve safety net for any tool confirmation that slips through
- [x] Structured 17-column CSV output (no more one giant "Signal" prose blob)
- [x] Score Breakdown column (transparent scoring, includes a "LOW PRIORITY" flag for scores under 50)
- [x] Cross-run lead deduplication via a permanent local ledger
- [x] SMTP email of new leads to the SDR
- [x] Email/no-email CSV split (score-independent)
- [x] SDR review loop for no-email leads (send for review → SDR edits → re-sync)
- [x] Apollo CRM write-back (Accounts + Contacts), human-approved, `Score >= 50` gated
- [x] HubSpot CRM sync — Company always, Contact+association+full-context-Note when email present, Company+Note-only when not
- [x] `|`-character-in-cell guardrail (prevents the markdown table parser from misaligning columns)
- [x] Full schema-consistency audit across every script (just completed — found and fixed one stale-column-reference bug)

---

# Features In Progress / Not Done

- [ ] **HubSpot integration live-testing** — `hubspot_sync.py` has never made a real API call. No `HUBSPOT_ACCESS_TOKEN` is configured. Needs a HubSpot Private App created (scopes: `crm.objects.contacts.read/write`, `crm.objects.companies.read/write`, `crm.objects.notes.write`), then `--dry-run` first, then a small real batch.
- [ ] **Custom HubSpot properties.** Currently ICP, Score, Fit Reasoning, etc. only exist inside free-text Notes, not as first-class filterable/reportable HubSpot properties. If the NamaSys team wants to build HubSpot lists/reports/workflows filtered by ICP or Score, this needs custom property creation (`POST /crm/v3/properties/contacts` etc.) added to `hubspot_sync.py`.
- [ ] **Lead ledger expiry/cooldown.** Currently a lead is excluded from output **forever** once seen once, even if circumstances genuinely change (e.g., a new job posting three months later). No cooldown period has been implemented. Flagged to the user as a future option, not yet requested.
- [ ] **NamaSys website/LinkedIn knowledge auto-crawl agent.** Early in the conversation the user pasted a "Next Steps" document describing a separate Managed Agent that would crawl namasys.ai (and check-before-re-crawling) to keep the company-knowledge memory current automatically. This was explicitly deferred — the current `namasys_company_profile.md` was populated by a **one-time manual WebFetch** of namasys.ai (LinkedIn's About page could not be fetched — it's login-walled), not by an automated agent. If NamaSys's services/positioning change, someone has to manually re-fetch and re-run `setup_namasys_memory.py --force`.
- [ ] **Scheduling.** `schtasks` commands for Windows Task Scheduler were suggested in conversation (daily for `--mode daily`, weekly for `--mode icp1`/`--mode full`) but never confirmed as actually set up on the user's machine.
- [ ] **LinkedIn company data.** Never retrieved (login wall). If founding year, employee count, or specialties from LinkedIn specifically are wanted in the company-knowledge profile, someone needs to paste that content in manually.

---

# Design Decisions

### 1. Managed Agents, not the Claude Agent SDK, not a manual tool-use loop

**Decided:** Use Anthropic's **Managed Agents** product (`client.beta.agents`, `client.beta.sessions`, etc.) as the runtime for the search agent.
**Why:** The user explicitly asked to "use a Claude Managed Agent" connected via MCP to Apollo. Managed Agents is the option that supplies BOTH the agent loop AND a hosted sandbox where MCP tool calls execute, with built-in credential vaulting (so the Apollo OAuth token never has to touch our own code or leak into a sandbox we don't control) and a Memory Store primitive we needed anyway for company knowledge.
**Alternatives considered:** (a) Claude API + manual tool-use loop — would require us to host and implement the MCP client ourselves, and to handle credential storage ourselves (worse security posture, more code). (b) Claude Agent SDK — that's Claude Code repackaged as a library; wrong tool for a headless server automation, and doesn't have the Vault/Memory Store primitives this project relies on. Neither was seriously pursued once Managed Agents' fit became clear.

### 2. YAML + Python apply-scripts instead of the `ant` CLI

**Decided:** Define the agent/environment as YAML files, applied via small Python scripts (`setup_agent.py`, `update_agent.py`) that call the SDK directly.
**Why:** Anthropic's own docs recommend YAML + the `ant` CLI as the standard pattern for this. The `ant` CLI was **not installed** on the user's machine, and installing it wasn't pursued (no clear Windows-native install path was documented for it at the time). The YAML-as-source-of-truth *philosophy* was kept (so behavior changes are version-controlled and diffable), just applied via Python instead of the CLI.
**Alternatives considered:** Calling `agents.create()`/`agents.update()` directly with inline Python dicts (no YAML) — rejected because it loses the "the config is one readable file" property, and makes future edits harder to review.

### 3. Two separate Sessions (ICP 1, ICP 2), not one combined Session

**Decided:** `run_leadgen.py` runs ICP 1 and ICP 2 as two independent Managed Agent sessions, merging results in Python.
**Why:** Two problems observed with one combined session: (a) **token/cost inefficiency** — a shared session keeps accumulating ICP 2's entire tool-call history in context while ICP 1 runs, even though the two searches are logically unrelated; (b) **reliability** — in testing, the agent sometimes shortchanged ICP 1 after a long ICP 2 run within the same conversation, giving it less thorough treatment. Splitting into two fresh sessions fixed both.
**Alternatives considered:** The user directly asked "would 2 separate Agents be more efficient than 1?" The answer given (and implemented) was: **no, keep one Agent, split into two Sessions instead** — the token-efficiency win comes from fresh context per session, not from having two separate Agent *configs*, and two Agents would mean two system prompts to keep in sync for no additional benefit.

### 4. Apollo OAuth (not an API key)

**Decided:** Connect to Apollo's MCP server via OAuth 2.0.
**Why:** Not a choice — Apollo's own MCP documentation states plainly "API key required: No / Authentication: OAuth 2.0." The user initially assumed an API key would be needed (there's a "Create new API key" dialog in Apollo's UI) and was told to cancel it — that dialog is for Apollo's separate REST API, unrelated to the MCP connector.
**Alternatives considered:** None viable — this is dictated by Apollo's own architecture.

### 5. Dynamic Client Registration + PKCE, not a pre-registered OAuth app

**Decided:** `apollo_oauth_connect.py` registers a throwaway public OAuth client via RFC 7591 Dynamic Client Registration on every fresh setup, rather than requiring a pre-registered app in an Apollo developer portal.
**Why:** Apollo's own docs distinguish "Partners" (who register a formal OAuth app for partnership integrations) from regular users (who use DCR). Verified live against Apollo's actual `register_oauth_client` endpoint — works, returns a `client_id`, no secret (public/PKCE client).
**Alternatives considered:** None — this is what Apollo's API supports for non-partner integrations.

### 6. Least-privilege, explicitly enumerated OAuth scopes

**Decided:** Request exactly 18 named scopes (see Configuration section), never a wildcard or "all scopes."
**Why:** Security — the agent should never be able to send emails, purchase domains, manage billing, etc. through Apollo, even though Apollo's API offers all of that. Verified the full set against Apollo's live `scopes_supported` list and against every Apollo MCP tool the agent's system prompt actually references, to confirm nothing needed is missing and nothing unnecessary is granted.
**Alternatives considered:** Requesting Apollo's default full scope set (what you get if you don't specify `scope` at all) — rejected on least-privilege grounds; confirmed via live testing that Apollo *does* honor a restricted scope request (it doesn't silently grant everything anyway).

### 7. Archive-then-recreate the Apollo vault credential, not update-in-place

**Decided:** When re-authorizing Apollo (e.g., to add a scope, or because the token died), `apollo_oauth_connect.py` archives the old vault credential and creates a brand new one, rather than calling the credential-update endpoint.
**Why:** Discovered live (two separate 400 errors) that the Managed Agents vault credential **update** schema is materially narrower than the **create** schema: `token_endpoint_auth: {"type": "none"}` (needed for our public/PKCE client) is valid on create but rejected on update; `client_id` isn't even an accepted field on update. Worse, even a successful narrow update would leave a stored `client_id` that doesn't match the fresh `refresh_token` just obtained (issued for a newly-registered client), silently breaking future auto-refresh. Confirmed the exact accepted fields by **reading the installed `anthropic` Python SDK's own generated type stubs** (`.../types/beta/vaults/beta_managed_agents_mcp_oauth_*_params.py`), not by further guessing against the live API.
**Alternatives considered:** (a) Patch the update call to only send fields the update schema accepts — tried this first, hit the `client_id` "unknown field" error, realized it doesn't solve the deeper client-id/refresh-token mismatch problem anyway. (b) Persist and reuse the same `client_id` across every re-auth (would also solve the mismatch) — not implemented; archive+recreate was simpler and fully sidesteps the asymmetric-schema problem using only the fully-Required, fully-verified create path.

### 8. `access_type=offline` + `prompt=consent` OAuth hint parameters

**Decided:** Added these two non-standard-but-common query parameters to the Apollo authorization request.
**Why:** The first successful OAuth round-trip did **not** return a `refresh_token` (silently — the original code only printed a one-line warning that was easy to miss in scrollback). Without a refresh token, the access token (whatever its TTL) can never auto-renew, meaning scheduled runs would eventually start failing with "authorization token is invalid or expired" and require manual re-auth every time. Adding these Google-popularized OAuth extensions (many custom OAuth servers honor them even though they're not in the base RFC 6749 spec) fixed it — confirmed live: `expires_in=2592000s` (30 days) with `refresh_token=present`.
**Alternatives considered:** None tried before this — it worked on the first attempt. If it hadn't, the fallback plan (stated to the user, not built) would have been a scheduled re-run of `apollo_oauth_connect.py` before every token expiry, since Apollo may simply not issue refresh tokens for this integration type otherwise.

### 9. CSV schema redesign: v1 (one "Signal" blob) → v2 (17 distinct columns)

**Decided:** Replaced a single dense `Signal` free-text column (mixing job titles, posting age, revenue, headcount growth, decision-maker reasoning, and fit rationale into one run-on sentence) with 17 distinct columns.
**Why:** Direct user feedback after reviewing real output: "I don't understand the signal part... it looks bit unclear... how it is working." The blob required reading a full paragraph to find any single fact. Also found and fixed a **real parsing bug** in the same review: a company name containing a literal `|` character (`CoverGo | Insurtech`) broke the naive pipe-splitting markdown-table parser, shifting every subsequent column left by one and silently losing the last column's data for that row.
**Alternatives considered:** Keeping one blob but reformatting it (e.g., as a bulleted list within the cell) — rejected in favor of genuinely separate columns, since the user specifically wanted fields to be "distinct, clear, understandable" as separate facts, not just better-formatted prose.

### 10. ICP 1 redefinition: "partnership/reseller candidate" → "direct customer"

**Decided:** Rewrote both the agent system prompt's ICP 1 section AND the company-knowledge memory file to describe ICP 1 companies as **potential direct customers of NamaSys** (NamaSys is their vendor, solving a real problem for them), explicitly forbidding language like "subcontract candidate" or "white-label partner."
**Why:** This was the single largest correction in the whole project. The ORIGINAL ICP 1 definition (from the user's very first message) was titled "Service/Partnership-Based Companies," which — combined with the company-knowledge memory content the assistant wrote — got interpreted as "find companies who might resell/subcontract NamaSys's work to their own clients." The user corrected this explicitly: "they need to find the company which can be a potential customer/client for the namasys analytics and with there abilities namasys can solve the problem understand there pain point and provide them the solution." The **mechanical filters stayed the same** (11–50 employees, US/UK/UAE/India, service-based/agency/consultancy/BPO industry type) — only the **judgment lens** for what makes a good fit changed.
**Alternatives considered:** None — this was a direct correction of a misunderstanding, not a considered tradeoff.

### 11. Mandatory email-reveal enrichment step

**Decided:** Added explicit, repeated instructions (in Tools Available, in both ICP workflow steps, and in Guardrails) that finding a decision-maker via search is NOT sufficient — the agent must separately call the enrichment/match tool with an email-reveal option before writing anything other than "-" in the Email field.
**Why:** Every single lead in early real output had `Email: -`, even fully-enriched ones with LinkedIn found. Root cause: Apollo's plain people-search results never include a verified email by default (deliberately gated behind a separate enrichment/credit-consuming call) — the agent was only calling search, never enrichment.
**Alternatives considered:** None — this was a straightforward missing-instruction bug once diagnosed.

### 12. Autonomy instruction (fix for mid-run "do you want to proceed?" stalling)

**Decided:** Added an explicit "Execution Mode" section telling the agent to run the entire workflow without pausing to ask permission before searches/enrichments/saves, since the human already authorized the whole run by starting it.
**Why:** Observed in a live trace: the agent stopped mid-search to ask "Before I run this, here's the credit scope... Do you want to proceed?" — the session then went idle waiting for a human response that our automation script never sends, silently hanging the run forever. This is model behavior (Claude being cautious about resource-consuming actions), not a Managed-Agents-level permission gate.
**Alternatives considered:** Wiring up actual `user.tool_confirmation` handling to respond to such prompts — this WAS also done (see #13) as defense-in-depth, but the primary fix is the prompt instruction, since the observed stall was the *model* asking in plain text, not a real permission-gate event.

### 13. `always_allow` permission policy + client-side auto-approve safety net

**Decided:** Explicitly set `permission_policy: {type: always_allow}` on the `agent_toolset_20260401` tool block in the YAML, AND added code in `run_leadgen.py`'s event loop that auto-sends `user.tool_confirmation: allow` if it ever sees `evaluated_permission == "ask"` on any tool call.
**Why:** Belt-and-suspenders after the same "stuck waiting for approval nobody can find" class of failure recurred (a Console screenshot showed a genuine `agent.tool_use` event with `evaluated_permission: "ask"`, not just model text). The YAML fix addresses the documented default for the built-in toolset; the code fix is a safety net in case any other tool (present or future) ever defaults to requiring confirmation.
**Alternatives considered:** Setting the same `permission_policy` block on the `mcp_toolset` entry too — attempted, then **reverted**, because that field's schema support for `mcp_toolset` specifically was only "empirically observed" in Anthropic's own docs, not officially confirmed, and risked a 400 on the next agent update. Relying on Apollo/MCP tools' documented default (`always_allow`) plus the code-level safety net was judged the lower-risk choice.

### 14. Apollo CRM writes: fully decoupled into a separate, human-approved script

**Decided:** The search-and-score workflow (`main.py`) NEVER writes to Apollo CRM. Saving to Apollo is `save_to_apollo.py` — a wholly separate script the user runs deliberately, which shows a preview and requires typing `y`.
**Why:** Went through two iterations. First iteration: the agent's own workflow included an automatic "save qualified leads (Score≥50) to Apollo" step at the end of each search session. The user then explicitly asked for a human-approval gate: "before directly saving the changes to crm first show the information in csv if the user approve run the crm script." This was implemented by removing the auto-save step from the search workflow entirely and adding a dedicated `## Saving to Apollo` section to the system prompt that's gated on "only when explicitly instructed via a dedicated save-only kickoff — never during a normal search run."
**Alternatives considered:** An inline `[y/N]` prompt inside the same session/run as the search — rejected, because the whole point was a genuine human review step with the CSV in hand, not a blind terminal prompt mid-run.

### 15. Model: `claude-opus-5` → `claude-sonnet-4-6` (effort: medium)

**Decided:** User explicitly requested "sonnet 4.5 with effort medium." This is technically impossible — the `effort` parameter is not supported at all on Sonnet 4.5 (confirmed from Anthropic's own API docs: it errors if set). Offered two options: Sonnet 5 (current-gen, fully supports effort) or Sonnet 4.5 without effort control. **User chose neither** — replied "make it 4.6 effort=medium." Sonnet 4.6 does support `effort` (`low`/`medium`/`high`/`max`), so this was implemented as `model: {id: claude-sonnet-4-6, effort: medium}` in the YAML.
**Why:** User's explicit, final choice after being informed of the Sonnet-4.5 constraint.
**Alternatives considered:** Sonnet 5 (recommended by the assistant, not chosen by the user); Sonnet 4.5 without effort (offered, not chosen).

### 16. Lead count target: 15 → 5 per ICP session

**Decided:** Both `ICP1_KICKOFF` and `ICP2_KICKOFF` prompt text (and the corresponding workflow instructions in the agent YAML) target **5 leads per session** (so `--mode full` yields up to 10 total), down from an initial 15 per ICP (30 total).
**Why:** Direct user request ("change the total lead to 10 in total 5 per icp"), clarified via a quick disambiguating question (5 total vs 5-per-ICP) — user chose 5-per-ICP (10 total).
**Alternatives considered:** None — straightforward parameter change per explicit instruction.

### 17. Permanent (non-expiring) lead ledger

**Decided:** `lead_ledger.py` excludes a domain from all future output **forever** once it's been seen once — no cooldown/expiry.
**Why:** User asked "how do we know whether we have already processed that information to avoid duplication" — the simplest, most direct interpretation of "avoid duplication" was implemented. Flagged explicitly to the user as a design choice with a known limitation (a company's circumstances can genuinely change and it never resurfaces), inviting a future cooldown-period request.
**Alternatives considered:** A time-based cooldown (e.g., resurface after 30/90 days) — explicitly proposed as a fast follow-up, not implemented, not yet requested by the user.

### 18. CSV split by email presence, NOT by score

**Decided (after a correction):** `split_by_email.py` splits purely on whether the `Email` column is populated. Score plays no role in the split.
**Why:** First implementation (`split_score100.py`) filtered to `Score == 100` before splitting by email — this was a **misreading** of the original request. User corrected: "not on the basis of score change that." The score-based file was deleted entirely and replaced.
**Alternatives considered:** None after the correction — this was a direct fix of a wrong assumption, not a tradeoff.

### 19. No-email leads: Company-only HubSpot record, not skipped entirely

**Decided (after a clarification):** `hubspot_sync.py` creates a **Company** record (deduped by domain) even for rows with no email — it only skips the **Contact** half. The decision-maker's name/title, if known, is written into a Note attached to the Company instead of being lost.
**Why:** First implementation dropped no-email rows from HubSpot sync entirely (only email+domain rows were processed). User clarified the intended flow: after SDR review/approval, approved no-email records should ALSO go into HubSpot — just not as a Contact (no stable dedupe key without email, which would risk creating a duplicate Contact on every re-run).
**Alternatives considered:** Creating a Contact anyway without email, accepting duplicate risk — rejected, explained to the user as the reason for the Company-only fallback instead.

### 20. HubSpot via plain REST (`urllib`), not another Managed Agent / MCP integration

**Decided:** `hubspot_sync.py` is deterministic Python code making direct HTTP calls to `api.hubapi.com`, with no LLM/agent involved at all.
**Why:** Mapping a CSV row to HubSpot API calls (upsert Company, upsert Contact, associate, create Note) is a fully deterministic, well-specified operation — using an LLM agent for it would add latency, cost, and non-determinism for zero benefit. This is explicitly different from the Apollo CRM write-back, which reuses the Managed Agent (because that path already has the Apollo MCP tools and Apollo-side vault credentials wired up — there was no equivalent reason to route HubSpot through an agent).
**Alternatives considered:** Building a HubSpot MCP connection the same way as Apollo — rejected as unnecessary complexity for a task with no need for LLM judgment.

---

# Important Code Patterns

Patterns used repeatedly across the codebase — worth recognizing before making changes:

- **Single source of truth for CSV columns**: `csv_writer.COLUMNS`. Every script that reads or writes lead CSVs imports this rather than hardcoding a column list. A recent full audit (triggered by direct user request) confirmed every hardcoded `row.get("...")` / `row["..."]` string literal across the whole codebase matches this list exactly — do the same check again if you add a new script or change the schema.
- **`_first_or_none(name, row)`** (defined in `hubspot_sync.py`): treats both an empty string and the literal `"-"` placeholder as "not present." The agent is instructed to write `"-"` for any not-applicable/not-found field (never leave a cell truly blank), so this helper is the correct way to check "does this field actually have a value."
- **`score_of(row)`** (in `csv_writer.py`): parses the Score column via `int(re.sub(r"[^\d-]", "", ...))` rather than a bare `int()` cast — tolerant of stray whitespace or formatting.
- **Read-only source, write-derived-files pattern**: `split_by_email.py` never modifies the CSV it reads; it only ever writes new files alongside it. `save_to_apollo.py` and `hubspot_sync.py` also only ever read. This was an explicit user requirement ("leave the apollo file dont do anything to it").
- **`_latest_*_csv()` helper pattern**: several scripts (`save_to_apollo.py`, `hubspot_sync.py`, `send_no_email_for_review.py`) default to "the most recently modified matching file in `LEADS_OUTPUT_DIR`" via `sorted(glob(...), key=mtime)[-1]`, but always accept an explicit path as an override.
- **`[y/N]` confirmation gate before any external-system write**: `save_to_apollo.py`, `hubspot_sync.py`, `send_no_email_for_review.py` all print a preview and require typing `y` before doing anything irreversible, with a `--yes` flag to skip it for scripted/CI use. This is a strong, repeated user preference — see User Preferences.
- **`--dry-run` flag**: `hubspot_sync.py` and `send_no_email_for_review.py` support this to preview exactly what would happen with zero API calls / zero emails sent. Always test with this first when in doubt.
- **Stream-first, then send**: `run_leadgen.py`'s `run_session()` opens the Managed Agents SSE event stream BEFORE sending the kickoff `user.message` — this is required by Managed Agents semantics (events before the stream opens are missed).
- **Idle-break gate**: the event loop only breaks on `session.status_idle` when `stop_reason.type != "requires_action"` (otherwise it's waiting on something, like a tool confirmation — which the auto-approve safety net handles) — or on `session.status_terminated`.
- **Schema-compatibility guard**: `split_by_email.py` checks `set(rows[0].keys()) != set(COLUMNS)` and fails with a clear message rather than crashing deep inside `csv.DictWriter` when pointed at an old-schema CSV (some files in `output/` predate the schema redesign and will trip this — that's intentional/expected).
- **Verifying against live APIs and installed SDK source, not just documentation**: multiple bugs in this project were root-caused by directly querying Apollo's live discovery endpoints (`curl` + `python -c`) and by reading the installed `anthropic` package's generated type-stub `.py` files, rather than trusting cached documentation. This is a pattern worth continuing — the docs available were sometimes stale or ambiguous relative to the live API.

---

# APIs and Integrations

## Anthropic Managed Agents API (beta)

Used via the `anthropic` Python SDK's `client.beta.*` namespace. Key resource types used: `agents`, `environments`, `sessions`, `sessions.events`, `vaults`, `vaults.credentials`, `memory_stores`, `memory_stores.memories`.

- Beta header `managed-agents-2026-04-01` — set automatically by the SDK for all these calls.
- **Agent** (`agent_01PR7uFAnp7SvJcUgMscg5GZ`, currently version 12) — model `claude-sonnet-4-6` with `effort: medium`, one system prompt (~15KB), MCP server `apollo`, tools `agent_toolset_20260401` (always_allow) + `mcp_toolset`.
- **Environment** (`env_01GZ4wFkFGjfJk7PjcJ44L3V`) — `type: cloud`, `networking: unrestricted`.
- **Vault** (`vlt_011CdjYEYA46XMAmBrjWaxpF`) — holds one `mcp_oauth` credential for Apollo (`display_name: "Apollo OAuth (auto-connected)"`).
- **Memory Store** (`memstore_013a22kn81CaCWrkrY9N9exd`) — one memory at path `/namasys_company_profile.md`, mounted read-only, ~4.4KB.

## Apollo.io MCP Server

- Endpoint: `https://mcp.apollo.io/mcp` (Streamable HTTP transport)
- Auth: OAuth 2.0, discovered via:
  - Protected resource metadata: `https://mcp.apollo.io/.well-known/oauth-protected-resource/mcp`
  - Authorization server metadata: `https://mcp.apollo.io/.well-known/oauth-authorization-server`
  - `authorization_endpoint`: `https://mcp.apollo.io/mcp/oauth_metadata/redirect_to_authorize`
  - `token_endpoint`: `https://mcp.apollo.io/api/v1/oauth/token`
  - `registration_endpoint`: `https://mcp.apollo.io/api/v1/oauth/applications/register_oauth_client`
- **Important quirk**: Apollo's Cloudflare WAF returns 403 for Python's default `urllib` User-Agent string. Every request `apollo_oauth_connect.py` makes sets a browser-like `User-Agent` header explicitly.
- **18 OAuth scopes granted** (verified live, exact spelling confirmed against Apollo's `scopes_supported`):
  `read_user_profile`, `organizations_search`, `organizations_job_posting`, `organizations_enrich`, `organizations_bulk_enrich`, `mixed_people_api_search`, `mixed_companies_search`, `people_match`, `people_bulk_match`, `contacts_search`, `contact_read`, `webhook_result_read`, `account_write`, `account_update`, `account_bulk_create`, `contact_write`, `contact_update`, `contacts_bulk_create`. (Apollo auto-adds a 19th, `app_scopes`, to every grant regardless of what's requested.)
- **Apollo MCP tools referenced in the agent's system prompt** (exact names may vary slightly — the prompt tells the agent to use "the closest-matching tool name" — this is the full deferred-tool inventory seen at the start of the project):
  `apollo_organizations_job_postings`, `apollo_mixed_companies_search`, `apollo_mixed_people_api_search`, `apollo_organizations_enrich`, `apollo_organizations_bulk_enrich`, `apollo_people_match`, `apollo_people_bulk_match`, `apollo_webhook_result_show` (async waterfall email-enrichment polling), `apollo_users_api_profile` (called automatically by Apollo's own tooling, not explicitly by our prompt), `apollo_accounts_create`, `apollo_accounts_bulk_create`, `apollo_contacts_create`, `apollo_contacts_bulk_create`. There are MANY more Apollo tools available (emailer campaigns, domain purchases, tasks, sequences, etc.) that are deliberately never used and never scoped for.

## HubSpot CRM API (v3/v4 REST)

- Base: `https://api.hubapi.com`
- Auth: Bearer token from a HubSpot Private App (`HUBSPOT_ACCESS_TOKEN` — **currently not set**)
- Endpoints used (all in `hubspot_sync.py`):
  - `POST /crm/v3/objects/companies/batch/upsert` (idProperty: `domain`)
  - `POST /crm/v3/objects/contacts/batch/upsert` (idProperty: `email`)
  - `PUT /crm/v4/objects/{fromType}/{fromId}/associations/default/{toType}/{toId}`
  - `POST /crm/v3/objects/notes`
- **Not live-verified** — built from documented API shapes only.

## Gmail SMTP

- Host `smtp.gmail.com:587`, STARTTLS, App Password auth (not OAuth, not the account password).
- Sending account: `sakshampundeer333@gmail.com`. Recipient: `saksham.p@namasys.ai`.

---

# Database Schema

There is no database — everything is flat files. Two distinct CSV schemas exist; **do not confuse them**.

## Lead CSV schema (17 columns) — `csv_writer.COLUMNS`

| # | Column | Populated for | Notes |
|---|---|---|---|
| 1 | Company | both | |
| 2 | Domain | both | primary dedupe key throughout the whole pipeline |
| 3 | Country | both | |
| 4 | Employees | both | free-text range, e.g. "11-25" or "~20" |
| 5 | ICP | both | literal string "ICP 1" or "ICP 2" |
| 6 | Company Overview | **ICP 1 only** | what the company does, size/stage, revenue — "-" for ICP 2 |
| 7 | NamaSys Fit | **ICP 1 only** | the specific pain point + which NamaSys capability solves it |
| 8 | Fit Reason | **ICP 2 only** | why the hiring signal matters |
| 9 | Hiring For | **ICP 2 only** | role(s) being hired |
| 10 | Posting Age | **ICP 2 only** | e.g. "<14 days" |
| 11 | Decision-Maker Name | both | split from the old combined "Decision-Maker (Name, Title)" field |
| 12 | Decision-Maker Title | both | |
| 13 | Email | both | "-" if not found even after the mandatory enrichment step |
| 14 | LinkedIn | both | |
| 15 | Score | both | 0–100 integer as a string |
| 16 | Score Breakdown | both | e.g. `"Base 40 + industry match (+20) + size 11-30 (+20) + DM found (+20) = 100"`; scores under 50 get ` — LOW PRIORITY: hold for human review before routing to outreach` appended |
| 17 | Source | both | which Apollo tool/search found it |

**Blank/not-applicable cells always contain the literal string `"-"`, never a truly empty string** — this is enforced by an explicit agent guardrail so downstream parsing never has to distinguish "empty" from "missing."

## Lead ledger schema (7 columns) — `lead_ledger.LEDGER_COLUMNS`, file `state/seen_leads.csv`

| Column | Notes |
|---|---|
| Domain | lowercased, the dedupe key |
| Company | |
| First Seen | ISO date, set once |
| Last Seen | ISO date, updated every time the domain reappears in a run |
| Times Seen | integer counter |
| Latest Score | overwritten each time it reappears |
| Latest ICP | overwritten each time it reappears |

As of last check: **10 real leads** tracked here (from Aug 6 real runs).

---

# Configuration

All configuration lives in `.env` (loaded by `config.py` via `python-dotenv`). **`.env.example` is the template — it has repeatedly gotten overwritten/renamed to `.env` by the user copying it via `mv`-like behavior instead of `cp`; if `.env.example` is ever missing, that's why, and it should be recreated from this table.**

| Variable | Current value (as of last check) | Required for |
|---|---|---|
| `ANTHROPIC_API_KEY` | set (real key) | everything |
| `NAMASYS_AGENT_ID` | `agent_01PR7uFAnp7SvJcUgMscg5GZ` | every session |
| `NAMASYS_AGENT_VERSION` | `12` | pinning session to a specific agent version (optional — `update_agent.py` re-fetches live version itself now, doesn't trust this) |
| `NAMASYS_ENVIRONMENT_ID` | `env_01GZ4wFkFGjfJk7PjcJ44L3V` | every session |
| `NAMASYS_VAULT_ID` | `vlt_011CdjYEYA46XMAmBrjWaxpF` | every session (Apollo credential) |
| `NAMASYS_MEMORY_STORE_ID` | `memstore_013a22kn81CaCWrkrY9N9exd` | mounting company knowledge (optional — sessions work without it, just less-grounded ICP 1 judgment) |
| `APOLLO_MCP_URL` | `https://mcp.apollo.io/mcp` | OAuth discovery + agent config |
| `APOLLO_OAUTH_AUTHORIZATION_ENDPOINT` / `_TOKEN_ENDPOINT` / `_REGISTRATION_ENDPOINT` | blank | only needed if live discovery ever fails |
| `APOLLO_OAUTH_CLIENT_ID` / `_CLIENT_SECRET` | blank | only needed if DCR is unavailable and a pre-registered app must be used instead |
| `LEADS_OUTPUT_DIR` | `./output` | where lead CSVs are written |
| `SMTP_HOST` | `smtp.gmail.com` | email sending |
| `SMTP_PORT` | `587` | email sending |
| `SMTP_USERNAME` | `sakshampundeer333@gmail.com` | email sending |
| `SMTP_PASSWORD` | **BLANK — currently broken, see Current Status** | email sending |
| `SMTP_FROM` | `sakshampundeer333@gmail.com` | email sending |
| `SDR_EMAIL` | `saksham.p@namasys.ai` | email recipient |
| `HUBSPOT_ACCESS_TOKEN` | **blank — HubSpot not yet configured** | `hubspot_sync.py` |

`config.py` provides three validators, each raising a clear error naming exactly what's missing: `require_runtime_config()` (Anthropic + agent/env/vault IDs), `require_email_config()` (SMTP + SDR), `require_hubspot_config()` (HubSpot token).

---

# Dependencies

`requirements.txt`:
```
anthropic>=0.100.0
python-dotenv>=1.0.0
pyyaml>=6.0
```

Everything else is Python 3.10 stdlib: `smtplib`, `email.message`, `urllib.request`/`urllib.parse`/`urllib.error`, `csv`, `json`, `http.server`, `webbrowser`, `base64`, `hashlib`, `secrets`, `argparse`, `pathlib`, `datetime`, `re`, `time`.

No `requests` library — deliberately avoided to not add a dependency, since `urllib` was already proven sufficient (and used consistently) for both the Apollo OAuth flow and the HubSpot REST calls.

---

# Known Bugs

## Fixed during this project (documented here so they aren't accidentally reintroduced)

1. **OAuth vault credential update rejects `token_endpoint_auth: {"type": "none"}`** — valid on create, not on update. Fixed by switching to archive-then-recreate (see Design Decision #7).
2. **OAuth vault credential update rejects `client_id` as an unknown field** — same root cause as #1, same fix.
3. **Missing `webhook_result_read` OAuth scope** — broke Apollo's async waterfall email-enrichment polling (`apollo_webhook_result_show` errored with an auth issue). Fixed by adding the scope.
4. **Agent stalling mid-run asking "do you want to proceed?"** — fixed via the Execution Mode / autonomy instruction (Design Decision #12).
5. **Agent writing scratch notes into the read-only Memory Store mount** (`/mnt/memory/icp2-lead-gen-sessions.md`, failed with "Read-only file system") — harmless (the write correctly failed, protecting the real company-knowledge file) but wasted a tool call. Fixed by explicitly telling the agent to use `/tmp/` for scratch notes instead.
6. **Every lead had `Email: -`** — root cause was the agent only calling Apollo's plain people-search (no email in results by default), never the separate email-reveal enrichment step. Fixed via explicit mandatory-enrichment instructions.
7. **CSV markdown-table parser breaks on a literal `|` inside a cell** (real example: company name `"CoverGo | Insurtech"` shifted every subsequent column left by one, losing the Source value for that row). Fixed via an explicit prompt guardrail telling the agent never to use `|` inside a cell (use `;` or `/` instead). **Note: this is a prompt-level mitigation, not a parser-level fix** — if the agent ever violates the instruction again, the same column-shift bug would recur. A more robust fix (e.g., a parser that tolerates literal pipes, or post-validates cell count per row) was not implemented.
8. **Stale column reference in `save_to_apollo.py`'s preview**: `row.get("Decision-Maker (Name, Title)")` — the combined-field name from the OLD (pre-redesign) CSV schema. Since the current schema splits this into `Decision-Maker Name` + `Decision-Maker Title`, this always silently returned the "-" default, meaning every pre-approval preview showed no decision-maker information at all (the actual save operation was unaffected — it uses the generic `COLUMNS`-driven table builder, not this line). Found via a full schema-consistency audit requested by the user; fixed to properly combine the two current fields.
9. **Stale "Signal column" reference in the main lead-notification email body text** (`email_sender.py`) — referred to a column that no longer exists post-redesign. Fixed to reference "Score Breakdown" instead, matching where the LOW PRIORITY flag actually lives now.
10. **`update_agent.py` 409 "Concurrent modification detected"** — was pinning the optimistic-concurrency `version` parameter to the (possibly stale) value in `.env`. Fixed by fetching the agent's current live version from the API first, always.
11. **`setup_agent.py` "Set ANTHROPIC_API_KEY before running setup"` despite it being in `.env`** — the script never called `load_dotenv()` itself (only `config.py` did, and this script didn't import `config`). Fixed by adding the `load_dotenv()` call directly.

## Open / unresolved

1. **`hubspot_sync.py` is unverified against a real HubSpot portal.** Every endpoint shape (batch upsert response format, v4 associations "default" endpoint behavior, notes association) is built from documented API knowledge, not confirmed live. Specific risk areas: whether `results[0]["id"]` is really the correct way to extract the created/updated object's ID from a batch-upsert response; whether the "default" association type actually exists for every object-type pair without needing an explicit `associationTypeId`.
2. **`SMTP_PASSWORD` is currently blank** — not a code bug, but the pipeline's email step will fail right now until this is refilled in `.env`.
3. **The `|`-in-cell mitigation is prompt-level only** (see Fixed #7 above) — could recur if the model doesn't follow the instruction on some future run.
4. **No automated tests exist.** All verification in this project was done via ad-hoc `python -c "..."` scripts and real API calls during the conversation, not a persisted test suite. Anyone continuing this project has no regression safety net beyond re-running these same manual checks.
5. **Vault credential churn**: every time `apollo_oauth_connect.py` re-runs (to fix scopes, or because the token needs replacing), it registers a BRAND NEW OAuth client on Apollo's side via DCR and archives the old vault credential. Apollo-side OAuth client records accumulate (harmless functionally, but not cleaned up — includes at least 3 throwaway test client registrations made during scope-verification testing in this conversation).

---

# Debugging History

Chronological account of the significant debugging arcs, for context on WHY the code looks the way it does:

1. **Credit-scope confirmation stall** → agent asked "Do you want to proceed?" mid-search and the run hung forever (our script never sends a reply to plain-text questions). → Added the Execution Mode autonomy instruction.
2. **"ICP 1 shows nothing" confusion** → turned out to be expected behavior (`--mode daily` = ICP 2 only, by design) — but this conversation also surfaced a real architecture question (one combined session vs two), resolved by splitting ICP 1/ICP 2 into separate sessions AND adding a standalone `--mode icp1`.
3. **Token-efficiency question** ("would 2 agents be more efficient than 1?") → answered and implemented as "2 sessions, 1 agent" (see Design Decision #3).
4. **Agent trying to write into the read-only Memory Store** → observed directly in a Console trace screenshot (`Write /mnt/memory/icp2-lead-gen-sessions.md` → "Read-only file system") → fixed with explicit `/tmp/`-for-scratch-notes guidance.
5. **"Apollo Mixed Companies Search" `protocol error`** → observed in a trace, self-recovered (agent retried and continued) → added a general retry-on-transient-error instruction as a defensive measure, not because this specific error recurred.
6. **All emails blank** → root-caused to missing email-reveal enrichment step → fixed with explicit mandatory-enrichment instructions.
7. **"Waterfall email enrichment accepted... webhook polling tool has an auth issue"** → observed directly in a Console trace → root-caused via re-fetching Apollo's live `scopes_supported` list and cross-referencing against the tool → found `webhook_result_read` was the missing scope → added it, re-ran OAuth, verified live that the scope round-trips correctly through Apollo's DCR endpoint.
8. **"awaiting approval" with no visible way to approve** → root-caused to a real `agent.tool_use` event with `evaluated_permission: "ask"` → fixed with explicit `always_allow` policy in the YAML + a client-side auto-approve safety net in `run_leadgen.py`.
9. **"authorization token is invalid or expired"** (session died mid-run) → root-caused to no `refresh_token` ever being issued on the original OAuth grant → added `access_type=offline&prompt=consent` hint params → confirmed live: token now comes back with a 30-day expiry AND a refresh token.
10. **Two rounds of vault-credential-update 400 errors** (`token_endpoint_auth.type: "none" is not a valid value`, then `unknown field "client_id"`) → root-caused NOT by guessing but by reading the actual installed `anthropic` SDK's generated type-stub files (`beta_managed_agents_mcp_oauth_*_params.py`) → discovered the update schema is fundamentally narrower than create, AND that patching around it would leave an inconsistent client_id/refresh_token pair → redesigned to archive-then-recreate instead of update.
11. **CSV output reviewed by user, found confusing** → led to the full v1→v2 schema redesign (Signal blob → 17 distinct columns) AND the ICP 1 reframing (partnership → direct customer) AND discovery of the `|`-in-cell parsing bug, all from one round of user feedback on real output.
12. **Model/effort request that was technically invalid** (Sonnet 4.5 + effort) → clarified with the user via a disambiguating question → resolved to Sonnet 4.6 + effort medium.
13. **Lead count 15→5 per ICP** → straightforward parameter change, clarified via a disambiguating question (5 total vs 5-each) → 5-each (10 total) confirmed.
14. **First HubSpot-integration request misread as score-based split** → user corrected ("not on the basis of score") → `split_score100.py` deleted, replaced with `split_by_email.py`.
15. **No-email leads initially dropped from HubSpot sync entirely** → user clarified they should still go in (as Company-only, after SDR approval) → `hubspot_sync.py` rewritten to branch per-row on email presence rather than filtering rows out upfront.
16. **Final schema-consistency audit** (direct user request: "check that all the output format in csv's remains same") → systematic grep of every hardcoded column-name string literal across every script, cross-checked against `csv_writer.COLUMNS` → found and fixed the one remaining stale reference (`save_to_apollo.py`'s preview line).

---

# Constraints

- **Windows environment.** Folder path has a literal double-space (`lead  agent`) — must be quoted in every shell command. PowerShell is the primary shell per the user's environment, but Git Bash was used throughout this session for Unix-style tooling (`grep`, `curl`, `sed`) since it was more convenient for the verification work.
- **No `ant` CLI installed.** The officially-recommended Managed Agents CLI tool isn't available — everything goes through the Python SDK directly instead.
- **Anthropic API billing.** Hit a real "credit balance too low" 400 error once mid-project — required the user to manually top up via the Anthropic Console. No code-level handling for this exists (nor should there be — it's an account-level action only the user can take).
- **The assistant cannot itself complete OAuth authorization grants** — every `apollo_oauth_connect.py` run requires the user to personally log into Apollo in their own browser and click "Allow." This is a hard operational constraint, not a preference.
- **The assistant never sends real emails or makes real HubSpot/Apollo API writes on the user's behalf without explicit instruction** — every test throughout this project was done with `--dry-run` or synthetic local data; real sends/writes were left for the user to trigger themselves by running the scripts.
- **No live HubSpot account access** — the assistant could not verify `hubspot_sync.py` against a real portal (unlike Apollo, which was verified live extensively).
- **Not a git repository.** No version control, no commit history, no ability to diff against a prior state other than by re-reading files and comparing to what's documented here.

---

# User Preferences

Patterns in how the user wants to work, worth internalizing for continuity:

- **Human-in-the-loop for everything external-facing.** Repeatedly steered the design toward "the agent searches, a human approves, then a separate script pushes" rather than any single automatic end-to-end flow. This applies to Apollo CRM writes, HubSpot writes, and even the no-email-lead review process.
- **Wants real verification, not just a plausible-sounding fix.** When told "this should work now," the user's typical next move was to actually run it and report back the real error — and separately, directly asked "are you sure, make sure every permission and script is fine" after a fix, which prompted a full live-verified audit rather than a repeated assertion. Treat "I fixed it" claims as needing live confirmation, not just code review, whenever a live API is involved.
- **Corrects misunderstandings decisively and expects the correction to propagate everywhere it's relevant**, not just the one place mentioned. E.g., the ICP 1 reframing required updating the agent YAML AND the memory-store markdown file, not just one of them; the split-by-score→split-by-email correction required deleting the old script, not just adding a new one alongside it.
- **Wants CSV/data output to be structured and scannable, not prose-heavy.** Directly said records need to be "distinct, clear, understandable" — drove the entire schema redesign.
- **Communicates in short, sometimes grammatically loose messages** (e.g., "so hubspot will only add records with email?", "command for half mode") — these are usually precise asks despite the brevity; worth reflecting the request back concisely to confirm understanding rather than guessing at elaborate interpretations, but also not being paralyzed by minor ambiguity — the user answers disambiguating questions quickly and directly when asked.
- **Comfortable with the assistant making a reasonable default choice and explaining it**, rather than always stopping to ask — e.g., accepted the two-session-not-two-agent recommendation, the Company-only-Note-for-no-email HubSpot default, without pushback, as long as the reasoning was explained.
- **Wants transparency about confidence level.** The assistant explicitly distinguished "verified live against the real API" (Apollo work) from "built from documentation, not yet tested" (HubSpot work) — this distinction was well-received and should be maintained for any future integration work.

---

# Important Conversation Decisions

Numbered chronological list of the pivotal moments where the direction of the project changed (cross-references the fuller explanations above):

1. Committed to **Claude Managed Agents** (not Agent SDK, not manual loop) as the runtime, per explicit user request.
2. Discovered live that **Apollo requires OAuth, not an API key** — pivoted the entire credential-handling design mid-build.
3. Chose **two Sessions per run instead of two Agents** when asked directly about efficiency.
4. **Decoupled Apollo CRM writes** from the search workflow into a separate human-approved script, per explicit user request.
5. **Redefined ICP 1** from partnership/reseller framing to direct-customer framing, per explicit user correction.
6. **Redesigned the CSV schema** from one prose blob to 17 structured columns, per explicit user feedback, with the design proposed and approved before implementation (the one time in this project an explicit "does this work, should I implement?" approval gate was used before writing code).
7. Chose **Sonnet 4.6 + effort medium** as the final model, after clarifying a technically-invalid initial request.
8. Reduced the lead-count target from **15 to 5 per ICP**.
9. Added **HubSpot as a second CRM target**, explicitly separate from and never touching the Apollo integration.
10. Corrected the CSV split logic from **score-based to email-based**.
11. Corrected the HubSpot no-email handling from **skip entirely** to **Company-only record**.
12. Performed a **full schema-consistency audit** across every script on direct request, surfacing one real bug.

---

# Remaining Tasks (Priority Order)

1. **Restore `SMTP_PASSWORD` in `.env`.** Nothing email-related works until this is set. (Blocking, trivial.)
2. **Run one full, real end-to-end pipeline test on agent version 12** (`python main.py --mode full`) — this is the first run that will exercise ALL of: broadened ICP 2 titles, autonomy, retry, mandatory email-reveal, `webhook_result_read`, Sonnet 4.6, and the 5-per-ICP target together. Everything has been individually verified but never all at once.
3. **Set up `HUBSPOT_ACCESS_TOKEN`** (create a HubSpot Private App with the scopes listed in Configuration) and run `hubspot_sync.py --dry-run` against a real CSV, then a small real batch, then verify in the HubSpot UI that Companies/Contacts/Notes/associations look correct. Fix any API-shape assumptions that turn out to be wrong.
4. **Verify `send_no_email_for_review.py` sends a real email correctly** (never actually tested beyond `--dry-run`).
5. **Decide on and implement (or explicitly decline) a lead-ledger cooldown/expiry policy** — currently permanent exclusion.
6. **Set up actual OS-level scheduling** (Windows Task Scheduler `schtasks` commands were drafted in conversation but never confirmed installed) for the daily/weekly cadence.
7. **Decide whether custom HubSpot properties are worth adding** (ICP, Score, etc. as first-class filterable fields, not just in Notes) — depends on what the NamaSys sales team actually wants to do with the data inside HubSpot.
8. **Consider building the deferred NamaSys-website-knowledge auto-crawl agent** (mentioned early, explicitly deferred) if `namasys_company_profile.md` needs to be kept current automatically rather than manually re-fetched.
9. **Clean up accumulated throwaway Apollo OAuth client registrations** (cosmetic, low priority — functionally harmless).

---

# Risks

- **HubSpot integration could fail on first real use** in ways that weren't caught by `--dry-run` (which never makes a real API call) — e.g., if the batch-upsert response shape is subtly different from assumed, or if a specific HubSpot portal's default association type doesn't exist for Notes↔Companies. Mitigated by: test with a tiny batch first, read error messages carefully (the script surfaces full HubSpot API error responses), be ready to adjust field/endpoint assumptions against real error output the same way the Apollo bugs were resolved.
- **LLM agent behavior is inherently non-deterministic.** Even with the retry instruction, autonomy instruction, and email-reveal enforcement, a future run could still occasionally skip a step, misjudge an ICP fit, or hit a genuinely new Apollo API error class. There is no automated regression suite to catch this — only manual review of output.
- **The `|`-in-cell CSV parsing vulnerability is only prompt-mitigated, not code-mitigated.** If the model ever ignores that instruction, the same silent column-shift bug that affected the `CoverGo` row could recur, and it would NOT raise an error — it would silently produce a misaligned row.
- **Secrets live in plaintext `.env`** with no `.gitignore` verified (there's no git repo at all currently, so this is moot today, but if the project is ever put under version control, `.env` must be excluded immediately — it currently contains a real Anthropic API key and (when filled in) a Gmail App Password and HubSpot token).
- **Billing/credit exhaustion silently blocks ALL Anthropic API calls**, including trivial config operations like `update_agent.py` — already happened once. No proactive balance-checking exists in any script.
- **`.env.example` has repeatedly gotten clobbered** by the user's file-copying habit (renaming instead of copying) — if it goes missing again, it needs to be regenerated from the Configuration table in this document, not assumed to still exist.
- **Vault credential rotation (archive+recreate) means every re-auth is a hard cutover** — there's a brief window between archiving the old credential and creating the new one where, in principle, a concurrently-running session could fail an Apollo call. Not observed as a problem in practice (re-auth is an infrequent, deliberate manual action), but worth knowing.

---

*End of handoff document.*
