from .base import BudgetCheckFn, EventLogFn, LLMCallFn, RetrieveFn, SpecialistAgent

DOMAIN_PROMPTS = {
    "security": (
        "You are a security code reviewer. Ask: could this be exploited? "
        "Look for injection risks, secrets in code, auth bypasses, unsafe deserialization."
    ),
    "quality": (
        "You are a code quality reviewer. Ask: is the logic right? "
        "Look for correctness bugs, logic errors, code smells, unnecessary complexity."
    ),
    "tests": (
        "You are a test-coverage reviewer. Ask: what's untested? "
        "Look for missing cases, untested edge conditions, brittle assertions, coverage gaps."
    ),
    "docs": (
        "You are a documentation reviewer. Ask: will the next reader understand? "
        "Look for missing docstrings, outdated comments, undocumented public APIs."
    ),
}


def build_specialists(
    retrieve: RetrieveFn, llm_call: LLMCallFn, budget_check: BudgetCheckFn, log_event: EventLogFn
) -> dict[str, SpecialistAgent]:
    return {
        name: SpecialistAgent(
            name=name,
            domain_prompt=prompt,
            retrieve=retrieve,
            llm_call=llm_call,
            budget_check=budget_check,
            log_event=log_event,
        )
        for name, prompt in DOMAIN_PROMPTS.items()
    }
