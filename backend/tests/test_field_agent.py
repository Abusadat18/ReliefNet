"""The Field agent runs on LangChain's create_agent (LangGraph). A scripted
model stands in for a real provider, so the test needs no API key; FalkorDB
must be reachable."""
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from reliefnet import db, llm, routing
from reliefnet.agents.field import FieldSession
from reliefnet.db import query
from reliefnet.seed import seed_org, seed_region

ORG = "pytest_field"


class ScriptedModel(BaseChatModel):
    """Returns the scripted messages in order, like a model deciding on tools."""

    script: list[AIMessage]
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedModel":
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        msg = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])


@pytest.fixture
async def org(monkeypatch):
    try:
        await db.redis().ping()
    except Exception:
        pytest.skip("FalkorDB not reachable")
    await seed_region()
    await seed_org(ORG, "Pytest Field", reset=True)
    before = await routing.road_state("Old Iron Bridge")
    yield ORG
    await routing.set_road_status("Old Iron Bridge", before or "open")
    await query("region", "MATCH (p:Report {org:$o}) DELETE p", {"o": ORG})
    await db.falkor().select_graph(f"org_{ORG}").delete()
    await db.redis().hdel("rn:orgs", ORG)
    await db.close()


async def test_agent_calls_our_tool_and_the_graph_changes(org, monkeypatch):
    model = ScriptedModel(script=[
        AIMessage(content="", tool_calls=[{"name": "report_road", "id": "call_1",
                                           "args": {"road": "Old Iron Bridge", "status": "flooded"}}]),
        AIMessage(content="Recorded: Old Iron Bridge is reported flooded."),
    ])
    monkeypatch.setattr(llm, "is_live", lambda: True)
    monkeypatch.setattr(llm, "chat_model", lambda spec, effort=None: model)

    volunteer = {"id": "vol_test", "name": "Test Volunteer", "team": "Team 1", "role": "volunteer"}
    out = await FieldSession(org, volunteer, "web").reply("old iron bridge par paani bhar gaya")

    assert out["reply"] == "Recorded: Old Iron Bridge is reported flooded."
    assert [a["tool"] for a in out["actions"]] == ["report_road"]
    assert await routing.road_state("Old Iron Bridge") == "reported"  # one team's report, not yet confirmed
    assert model.calls == 2  # tool call, then the final answer


async def test_agent_failure_falls_back_to_rules(org, monkeypatch):
    class Broken(ScriptedModel):
        def _generate(self, *a, **kw):
            raise RuntimeError("provider down")

    monkeypatch.setattr(llm, "is_live", lambda: True)
    monkeypatch.setattr(llm, "chat_model", lambda spec, effort=None: Broken(script=[]))
    volunteer = {"id": "vol_test", "name": "Test Volunteer", "team": "Team 1", "role": "volunteer"}
    out = await FieldSession(org, volunteer, "web").reply("what are my tasks")
    assert "assignment" in out["reply"].lower()
