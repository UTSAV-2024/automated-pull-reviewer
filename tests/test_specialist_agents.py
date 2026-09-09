import asyncio
import json

import pytest

from agents.base import BudgetExceededError
from agents.specialists import DOMAIN_PROMPTS, build_specialists

pytestmark = pytest.mark.asyncio

VALID_RESPONSE = json.dumps(
    [
        {
            "severity": "HIGH",
            "category": "injection",
            "file": "app.py",
            "line": 42,
            "confidence": 0.9,
            "rationale": "user input reaches a raw SQL string",
        }
    ]
)


def make_deps(llm_response: str = VALID_RESPONSE, under_budget: bool = True):
    events: list[dict] = []
    retrieved_for: list[str] = []
    llm_calls: list[tuple[str, str]] = []

    async def retrieve(diff: str) -> list[dict]:
        retrieved_for.append(diff)
        return [{"chunk_text": "def handler(): ..."}]

    async def llm_call(system_prompt: str, user_content: str) -> str:
        llm_calls.append((system_prompt, user_content))
        return llm_response

    def budget_check() -> bool:
        return under_budget

    def log_event(event: dict) -> None:
        events.append(event)

    return retrieve, llm_call, budget_check, log_event, events, retrieved_for, llm_calls


async def test_all_four_specialists_return_well_formed_findings():
    deps = make_deps()
    retrieve, llm_call, budget_check, log_event, events, *_ = deps
    specialists = build_specialists(retrieve, llm_call, budget_check, log_event)

    results = await asyncio.gather(*(agent.run("diff text") for agent in specialists.values()))

    assert set(specialists.keys()) == set(DOMAIN_PROMPTS.keys())
    for name, findings in zip(specialists.keys(), results):
        assert len(findings) == 1
        finding = findings[0]
        assert finding["agent_type"] == name
        for field in ("agent_type", "severity", "category", "file", "line", "confidence", "rationale"):
            assert field in finding
        assert isinstance(finding["confidence"], float)


async def test_specialist_grounds_its_prompt_in_retrieved_context():
    retrieve, llm_call, budget_check, log_event, events, retrieved_for, llm_calls = make_deps()
    specialists = build_specialists(retrieve, llm_call, budget_check, log_event)

    await specialists["security"].run("some diff")

    assert retrieved_for == ["some diff"]
    system_prompt, user_content = llm_calls[0]
    assert "def handler(): ..." in user_content  # retrieved context reached the prompt
    assert "some diff" in user_content


async def test_budget_exceeded_blocks_the_llm_call_and_logs_it():
    retrieve, llm_call, budget_check, log_event, events, _, llm_calls = make_deps(under_budget=False)
    specialists = build_specialists(retrieve, llm_call, budget_check, log_event)

    with pytest.raises(BudgetExceededError):
        await specialists["quality"].run("diff")

    assert llm_calls == []  # never reached the LLM
    assert events[-1] == {"agent_type": "quality", "event_type": "budget_blocked"}


async def test_malformed_llm_response_yields_no_findings_instead_of_crashing():
    retrieve, llm_call, budget_check, log_event, events, *_ = make_deps(llm_response="not json")
    specialists = build_specialists(retrieve, llm_call, budget_check, log_event)

    findings = await specialists["docs"].run("diff")

    assert findings == []
    assert events[-1]["event_type"] == "completed"
    assert events[-1]["finding_count"] == 0


async def test_llm_call_failure_is_logged_and_reraised():
    async def failing_llm_call(system_prompt: str, user_content: str) -> str:
        raise RuntimeError("provider unavailable")

    retrieve, _, budget_check, log_event, events, *_ = make_deps()
    specialists = build_specialists(retrieve, failing_llm_call, budget_check, log_event)

    with pytest.raises(RuntimeError):
        await specialists["tests"].run("diff")

    assert events[-1]["event_type"] == "error"
    assert "provider unavailable" in events[-1]["error"]
