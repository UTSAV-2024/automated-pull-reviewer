import json
from dataclasses import dataclass
from typing import Awaitable, Callable

Finding = dict  # agent_type, severity, category, file, line, confidence, rationale

RetrieveFn = Callable[[str], Awaitable[list[dict]]]
LLMCallFn = Callable[[str, str], Awaitable[str]]  # (system_prompt, user_content) -> raw text
BudgetCheckFn = Callable[[], bool]  # True if under budget
EventLogFn = Callable[[dict], None]


class BudgetExceededError(Exception):
    pass


@dataclass
class SpecialistAgent:
    """Shared shape for every specialist: budget check, retrieval call, LLM
    call, event logging, error handling. Specialists differ only in name/
    domain_prompt (agents/specialists.py); everything else is dependency-
    injected so this plumbing is testable without a live LLM or database."""

    name: str
    domain_prompt: str
    retrieve: RetrieveFn
    llm_call: LLMCallFn
    budget_check: BudgetCheckFn
    log_event: EventLogFn

    async def run(self, diff: str) -> list[Finding]:
        if not self.budget_check():
            self.log_event({"agent_type": self.name, "event_type": "budget_blocked"})
            raise BudgetExceededError(f"{self.name}: daily budget exceeded")

        try:
            context = await self.retrieve(diff)
            context_text = "\n\n".join(chunk.get("chunk_text", "") for chunk in context)
            prompt = f"{self.domain_prompt}\n\nRetrieved context:\n{context_text}\n\nDiff:\n{diff}"
            raw = await self.llm_call(self.domain_prompt, prompt)
            findings = _parse_findings(self.name, raw)
            self.log_event({"agent_type": self.name, "event_type": "completed", "finding_count": len(findings)})
            return findings
        except BudgetExceededError:
            raise
        except Exception as exc:
            self.log_event({"agent_type": self.name, "event_type": "error", "error": str(exc)})
            raise


def _parse_findings(agent_type: str, raw: str) -> list[Finding]:
    """Parse the LLM's JSON response into structured Findings. A malformed
    response yields no findings rather than crashing the run; the orchestrator
    node already isolates and times out a failing specialist."""
    try:
        items = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    findings = []
    for item in items if isinstance(items, list) else []:
        if not all(k in item for k in ("severity", "category", "file", "confidence", "rationale")):
            continue
        findings.append(
            {
                "agent_type": agent_type,
                "severity": item["severity"],
                "category": item["category"],
                "file": item["file"],
                "line": item.get("line"),
                "confidence": float(item["confidence"]),
                "rationale": item["rationale"],
            }
        )
    return findings
