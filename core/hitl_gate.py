from enum import Enum


class GateDecision(str, Enum):
    AUTO_POST = "auto_post"
    HUMAN_QUEUE = "human_queue"
    ESCALATE = "escalate"


def evaluate(findings: list[dict], confidence: float, confidence_threshold: float) -> GateDecision:
    """Confidence-weighted HITL gate (FR-7): any CRITICAL finding escalates
    regardless of confidence (AC-5, consequence of error is too high to
    automate); otherwise confidence below the threshold routes to a human
    queue, and only a confident, non-CRITICAL result auto-posts (AC-4).

    # ponytail: no default threshold value baked in here on purpose — it's an
    # explicit open decision (see ASSUMPTION-51dccc33), the caller must set it.
    """
    if any(finding.get("severity") == "CRITICAL" for finding in findings):
        return GateDecision.ESCALATE
    if confidence < confidence_threshold:
        return GateDecision.HUMAN_QUEUE
    return GateDecision.AUTO_POST
