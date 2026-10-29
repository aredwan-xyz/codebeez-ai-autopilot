"""Authorization must precede data reads and writes, including sibling clients."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.agents.base_agent import BaseAgent
from src.api import server
from src.config.settings import Settings, settings
from src.integrations.airtable import AirtableClient
from src.integrations.gmail import GmailClient
from src.integrations.hubspot import HubSpotClient
from src.integrations.notion import NotionClient
from src.integrations.slack import SlackClient
from src.orchestrator import Orchestrator
from src.security import approved_execution, require_live_approval, valid_admin_token


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_API_TOKEN", "test-admin-token")
    monkeypatch.setattr(settings, "ENABLE_LIVE_ACTIONS", False)
    # No lifespan: use a fake orchestrator so API tests never start real agents.
    fake = AsyncMock()
    fake.run_history = []
    fake.active_agents = {}
    fake.get_status = lambda: {"active_agents": [], "recent_runs": []}
    monkeypatch.setattr(server, "_orchestrator", fake)
    test_client = TestClient(server.app)
    yield test_client
    test_client.close()


AUTH = {"Authorization": "Bearer test-admin-token"}


def test_non_ascii_token_denied(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_API_TOKEN", "test-admin-token")
    assert valid_admin_token("invalid-\u2603") is False


@pytest.mark.parametrize("path", ["/api/status", "/api/runs", "/api/agents"])
def test_reads_require_token(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer incorrect"}).status_code == 401
    assert client.get(path, headers=AUTH).status_code == 200


def test_missing_configuration_denies_api(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_API_TOKEN", "")
    assert client.get("/api/status", headers=AUTH).status_code == 401


def test_trigger_authentication_and_explicit_approval(client, monkeypatch):
    assert client.post("/api/trigger/email_agent").status_code == 401
    assert client.post("/api/trigger/email_agent", headers=AUTH,
                       json={"mode": "live", "approve_live": True}).status_code == 403
    monkeypatch.setattr(settings, "ENABLE_LIVE_ACTIONS", True)
    assert client.post("/api/trigger/email_agent", headers=AUTH,
                       json={"mode": "live"}).status_code == 403
    assert client.post("/api/trigger/email_agent", headers=AUTH,
                       json={"mode": "live", "approve_live": "true"}).status_code == 422
    server._orchestrator.trigger.assert_not_awaited()
    server._orchestrator.trigger.return_value = None
    assert client.post("/api/trigger/missing", headers=AUTH,
                       json={"mode": "live", "approve_live": True}).status_code == 404
    server._orchestrator.trigger.assert_awaited_once_with("missing", live=True)


def test_ordinary_trigger_is_preview(client):
    server._orchestrator.trigger.return_value = None
    assert client.post("/api/trigger/missing", headers=AUTH).status_code == 404
    server._orchestrator.trigger.assert_awaited_once_with("missing", live=False)


def test_websocket_auth_before_any_status(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"token": "incorrect"})
        with pytest.raises(WebSocketDisconnect) as denied:
            ws.receive_json()
        assert denied.value.code == 1008
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"token": "test-admin-token"})
        assert ws.receive_json()["event"] == "status"


def test_missing_websocket_token_cannot_read_status(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


@pytest.mark.parametrize("environment", ["development", "production", "test", "Production", "typo"])
def test_environment_does_not_enable_live_actions(environment):
    assert Settings(_env_file=None, APP_ENV=environment).ENABLE_LIVE_ACTIONS is False
    assert Orchestrator().dry_run is True


@pytest.mark.asyncio
async def test_every_mutating_adapter_denies_direct_unapproved_use(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_LIVE_ACTIONS", True)
    operations = [
        lambda: GmailClient().send_reply("thread", "test@example.com", "body"),
        lambda: GmailClient().apply_label("message", "label"),
        lambda: GmailClient().archive("message"),
        lambda: SlackClient().post_message("channel", "text"),
        lambda: SlackClient().post_file("channel", "text", "missing", "missing"),
        lambda: HubSpotClient().create_contact({}),
        lambda: NotionClient().mark_content_published("page", "https://example.com"),
        lambda: NotionClient().create_lead_record({}),
        lambda: AirtableClient().mark_processed("record", 1, False),
        lambda: AirtableClient().create_qualified_lead({}),
    ]
    for operation in operations:
        with pytest.raises(PermissionError):
            await operation()
    with pytest.raises(PermissionError):
        GmailClient()._get_or_create_label(None, "label")


@pytest.mark.asyncio
async def test_approved_adapter_write_and_scope_reset(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_LIVE_ACTIONS", True)
    slack = SlackClient()
    slack.token = "fake-test-value"
    slack._client = AsyncMock()
    with approved_execution():
        await slack.post_message("channel", "reviewed run")
    slack._client.chat_postMessage.assert_awaited_once_with(channel="channel", text="reviewed run")
    with pytest.raises(PermissionError):
        require_live_approval()


@pytest.mark.asyncio
async def test_approval_does_not_leak_to_concurrent_task(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_LIVE_ACTIONS", True)

    async def background():
        await asyncio.sleep(0)
        with pytest.raises(PermissionError):
            require_live_approval()

    task = asyncio.create_task(background())
    with approved_execution():
        require_live_approval()
        await task


def test_server_opt_in_is_required(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_LIVE_ACTIONS", False)
    with pytest.raises(PermissionError):
        with approved_execution():
            pytest.fail("Unconfigured live scope opened")


@pytest.mark.asyncio
async def test_expired_approval_is_not_reused_by_inherited_task(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_LIVE_ACTIONS", True)
    released = asyncio.Event()

    async def late_write():
        await released.wait()
        with pytest.raises(PermissionError):
            require_live_approval()

    with approved_execution():
        task = asyncio.create_task(late_write())
    released.set()
    await task


@pytest.mark.asyncio
async def test_live_trigger_does_not_mutate_scheduled_agent(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_LIVE_ACTIONS", True)

    class ExampleAgent(BaseAgent):
        async def run(self, run):
            if not self.dry_run:
                require_live_approval()
                run.items_actioned = 1
            return run

    orch = Orchestrator()
    agent = ExampleAgent()
    orch.active_agents["example"] = agent
    live = await orch.trigger("example", live=True)
    assert orch.get_agent_last_run("example") is live
    preview = await orch._run_agent("example")
    assert live.dry_run is False
    assert live.items_actioned == 1
    assert agent.dry_run is True
    assert preview.dry_run is True
    assert preview.items_actioned == 0
    with pytest.raises(PermissionError):
        require_live_approval()


@pytest.mark.asyncio
async def test_server_startup_always_previews(monkeypatch):
    fake = AsyncMock()
    fake.add_event_listener = lambda listener: None
    def constructor(**kwargs):
        assert kwargs == {"dry_run": True}
        return fake
    monkeypatch.setattr(server, "Orchestrator", constructor)
    await server.startup()
    fake.start.assert_awaited_once()
