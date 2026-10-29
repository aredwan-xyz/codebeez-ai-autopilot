# 🤖 AI Business Autopilot System

> **An experimental framework for previewing business workflows with AI agents.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code Style: Black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)

---

## What is This?

The **AI Business Autopilot System** is a prototype that connects AI reasoning with business-tool adapters. It includes email triage, lead scoring, content drafting and reporting workflows. Some adapters and publishing steps are placeholders; this repository does not establish production readiness or measured business outcomes.

All scheduled runs and dashboard buttons preview actions by default. Live integration mutations require both a server opt-in and one authenticated, explicitly approved API trigger. Dry-run still reads configured sources and may call a paid model; use dummy data when evaluating.

Built for founders, operators, and small teams who want to run lean while scaling output.

---

## Core Capabilities

| Module | What it Does |
|--------|-------------|
| **LeadAgent** | Scrapes, scores, and enriches inbound leads. Auto-qualifies and routes to CRM |
| **EmailAgent** | Reads, categorizes, drafts replies, and triages inbox at set intervals |
| **ContentAgent** | Generates, schedules, and publishes social content from a brief or calendar |
| **ReportAgent** | Pulls KPIs from integrations and generates weekly/monthly PDF reports |
| **InvoiceAgent** | Monitors overdue invoices, sends follow-ups, flags critical accounts |
| **SupportAgent** | Handles tier-1 support tickets, escalates complex issues to humans |
| **ResearchAgent** | Deep-dives topics, competitors, or markets and returns structured briefs |
| **SchedulerAgent** | Orchestrates all agents on cron-like schedules with retry/fallback logic |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Orchestrator Layer                    │
│              (SchedulerAgent + EventBus)                 │
└──────────────┬──────────────────────────┬───────────────┘
               │                          │
    ┌──────────▼──────────┐   ┌──────────▼──────────┐
    │    Agent Runtime     │   │   Workflow Engine    │
    │  (LLM + Tool Calls)  │   │  (DAG + State Mgmt) │
    └──────────┬──────────┘   └──────────┬──────────┘
               │                          │
    ┌──────────▼──────────────────────────▼──────────┐
    │               Integration Layer                  │
    │  Gmail │ Slack │ Notion │ Airtable │ HubSpot    │
    │  Stripe │ LinkedIn │ Twitter │ Webhook │ S3      │
    └─────────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/aredwan-xyz/codebeez-ai-autopilot.git
cd codebeez-ai-autopilot
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Fill in your API keys and integration credentials
# Generate ADMIN_API_TOKEN locally (for example: python -c 'import secrets; print(secrets.token_urlsafe(32))')
# Keep ENABLE_LIVE_ACTIONS=false while evaluating.
```

### 3. Run Your First Agent

```bash
# Start the scheduler in preview mode
python -m src.orchestrator start

# Launch the dashboard
python -m src.api.server
```

### 4. Open the Dashboard

Navigate to `http://localhost:8000` to view the live agent dashboard.
Enter your admin API token when prompted; it stays in this tab's memory. Use HTTPS
when accessing the dashboard remotely. REST clients send `Authorization: Bearer <token>`.
An empty configured token denies all protected requests.

To approve one live agent execution, first configure `ENABLE_LIVE_ACTIONS=true`,
then send an authenticated `POST /api/trigger/<agent_name>` with JSON
`{"mode":"live","approve_live":true}`. The approval is scoped to that execution;
it does not enable later scheduled writes. Review the agent configuration and
source data before approving; this is run-level approval, not per-message review.
Standalone integration mutations outside that approved execution fail closed.
`GET /health` is public and contains no run data.

Before using customer data, validate provider access, integration behavior and
the workflow with a reviewed test account. The CI suite uses mocks, not live
provider credentials. Container CI verifies startup and unauthenticated denial;
it does not validate real email, CRM or publishing delivery.

---

## Project Structure

```
ai-autopilot/
├── src/
│   ├── agents/              # Individual AI agent implementations
│   │   ├── base_agent.py    # Abstract base class for all agents
│   │   ├── email_agent.py   # Email triage + auto-reply
│   │   ├── lead_agent.py    # Lead scoring + CRM routing
│   │   ├── content_agent.py # Content generation + scheduling
│   │   ├── report_agent.py  # KPI reports + PDF generation
│   │   ├── invoice_agent.py # Invoice monitoring + follow-ups
│   │   ├── support_agent.py # Tier-1 support handling
│   │   └── research_agent.py# Deep research + briefing
│   ├── workflows/           # Multi-step workflow definitions
│   │   ├── lead_pipeline.py
│   │   ├── content_calendar.py
│   │   └── client_onboarding.py
│   ├── integrations/        # Third-party service connectors
│   │   ├── gmail.py
│   │   ├── slack.py
│   │   ├── notion.py
│   │   ├── hubspot.py
│   │   ├── stripe.py
│   │   └── airtable.py
│   ├── api/                 # REST API + Dashboard backend
│   │   ├── server.py
│   │   ├── routes/
│   │   └── websocket.py
│   ├── utils/               # Shared utilities
│   │   ├── llm.py           # LLM client wrapper (Anthropic/OpenAI)
│   │   ├── memory.py        # Agent memory + context management
│   │   ├── logger.py        # Structured logging
│   │   └── retry.py         # Retry + backoff utilities
│   ├── config/
│   │   ├── settings.py      # Pydantic settings model
│   │   └── agents.yaml      # Agent configuration
│   └── orchestrator.py      # Main scheduler/orchestrator
├── tests/
├── docs/
├── scripts/
├── .github/workflows/
├── requirements.txt
├── docker-compose.yml
├── Dockerfile
└── .env.example
```

---

## Configuration

All agents are configured via `src/config/agents.yaml`:

```yaml
agents:
  email_agent:
    enabled: true
    schedule: "*/15 * * * *"   # Every 15 minutes
    max_emails_per_run: 50
    auto_reply: true
    escalation_threshold: 0.7

  lead_agent:
    enabled: true
    schedule: "0 9 * * 1-5"    # 9am weekdays
    min_score_to_route: 65
    crm_target: hubspot
```

---

## Contributing

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/new-agent`)
3. Write tests for new agents
4. Submit a PR with a clear description

See [CONTRIBUTING.md](docs/CONTRIBUTING.md) for full guidelines.

---

## License

MIT © CodeBeez / Abid Redwan. See [LICENSE](LICENSE) for details.
