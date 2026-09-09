import asyncio
import operator
from typing import Annotated, Awaitable, Callable, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

SPECIALISTS = ("security", "quality", "tests", "docs")

SpecialistFn = Callable[[str], Awaitable[list[dict]]]

# ponytail: fixed per-node timeout; make configurable per-specialist if one
# legitimately needs longer.
NODE_TIMEOUT_SECONDS = 60


class ReviewState(TypedDict, total=False):
    diff: str
    # dict-merge reducers: parallel specialist branches write disjoint keys,
    # so concurrent partial updates combine instead of clobbering each other.
    findings: Annotated[dict, operator.or_]
    errors: Annotated[dict, operator.or_]


def _make_specialist_node(name: str, run: SpecialistFn, timeout_seconds: float):
    async def node(state: ReviewState) -> dict:
        try:
            result = await asyncio.wait_for(run(state["diff"]), timeout=timeout_seconds)
            return {"findings": {name: result}}
        except Exception as exc:  # noqa: BLE001 - a hung/failing specialist must not block the join
            return {"errors": {name: f"{type(exc).__name__}: {exc}"}}

    return node


def build_graph(specialists: dict[str, SpecialistFn], checkpointer=None, timeout_seconds: float = NODE_TIMEOUT_SECONDS):
    """Fan out to every specialist in parallel; each is isolated by a timeout so a
    hung or failing specialist cannot deadlock the join (NFR-7). Checkpointing
    (default: in-memory; pass a durable checkpointer, e.g. Redis-backed, in
    production) lets a crashed worker resume from the last completed node
    instead of restarting the whole review (NFR-2, AC-8)."""
    graph = StateGraph(ReviewState)
    for name, run in specialists.items():
        graph.add_node(name, _make_specialist_node(name, run, timeout_seconds))
        graph.add_edge(START, name)
        graph.add_edge(name, END)
    return graph.compile(checkpointer=checkpointer or MemorySaver())
