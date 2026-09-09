import asyncio

import pytest
from langgraph.checkpoint.memory import MemorySaver

from orchestrator.graph import SPECIALISTS, build_graph

pytestmark = pytest.mark.asyncio


def make_specialist(calls: list[str], *, sleep: float = 0, fail: bool = False):
    async def run(diff: str) -> list[dict]:
        calls.append(diff)
        if sleep:
            await asyncio.sleep(sleep)
        if fail:
            raise RuntimeError("specialist blew up")
        return [{"diff": diff}]

    return run


async def test_all_four_specialists_run_in_parallel_and_findings_merge():
    calls: dict[str, list[str]] = {name: [] for name in SPECIALISTS}
    specialists = {name: make_specialist(calls[name]) for name in SPECIALISTS}
    app = build_graph(specialists)

    result = await app.ainvoke({"diff": "diff-1"}, {"configurable": {"thread_id": "t1"}})

    assert set(result["findings"].keys()) == set(SPECIALISTS)
    assert result.get("errors", {}) == {}
    for name in SPECIALISTS:
        assert calls[name] == ["diff-1"]


async def test_one_failing_specialist_does_not_block_the_others():
    calls: dict[str, list[str]] = {name: [] for name in SPECIALISTS}
    specialists = {name: make_specialist(calls[name], fail=(name == "security")) for name in SPECIALISTS}
    app = build_graph(specialists)

    result = await app.ainvoke({"diff": "diff-1"}, {"configurable": {"thread_id": "t2"}})

    assert set(result["findings"].keys()) == {"quality", "tests", "docs"}
    assert "security" in result["errors"]


async def test_a_hung_specialist_times_out_instead_of_blocking_the_join():
    calls: dict[str, list[str]] = {name: [] for name in SPECIALISTS}
    specialists = {name: make_specialist(calls[name], sleep=(5 if name == "docs" else 0)) for name in SPECIALISTS}
    app = build_graph(specialists, timeout_seconds=0.05)

    result = await app.ainvoke({"diff": "diff-1"}, {"configurable": {"thread_id": "t3"}})

    assert set(result["findings"].keys()) == {"security", "quality", "tests"}
    assert "TimeoutError" in result["errors"]["docs"]


async def test_crash_mid_review_resumes_without_rerunning_completed_nodes():
    calls: dict[str, list[str]] = {name: [] for name in SPECIALISTS}
    # `docs` is the slow one that gets interrupted by the simulated crash.
    specialists = {name: make_specialist(calls[name], sleep=(0.3 if name == "docs" else 0)) for name in SPECIALISTS}
    checkpointer = MemorySaver()
    app = build_graph(specialists, checkpointer=checkpointer, timeout_seconds=5)
    config = {"configurable": {"thread_id": "crash-1"}}

    # Simulate a worker crash: the process dies partway through, before the
    # slow node finishes.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(app.ainvoke({"diff": "diff-1"}, config), timeout=0.1)

    completed_before_resume = {name: list(c) for name, c in calls.items()}
    assert completed_before_resume["docs"] == ["diff-1"]  # it started, but hadn't returned

    # Resume: a fresh call against the same thread/checkpointer, as a
    # replacement worker would do.
    result = await app.ainvoke(None, config)

    assert set(result["findings"].keys()) == set(SPECIALISTS)
    # The fast specialists must not have been re-run after the crash.
    for name in ("security", "quality", "tests"):
        assert calls[name] == ["diff-1"]
