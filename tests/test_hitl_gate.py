from core.hitl_gate import GateDecision, evaluate


def finding(severity="HIGH"):
    return {"severity": severity, "category": "injection", "file": "a.py", "confidence": 0.5, "rationale": "r"}


def test_high_confidence_no_critical_auto_posts():
    assert evaluate([finding("HIGH")], confidence=0.9, confidence_threshold=0.7) == GateDecision.AUTO_POST


def test_no_findings_at_all_auto_posts():
    assert evaluate([], confidence=1.0, confidence_threshold=0.7) == GateDecision.AUTO_POST


def test_confidence_below_threshold_routes_to_human_queue():
    assert evaluate([finding("HIGH")], confidence=0.5, confidence_threshold=0.7) == GateDecision.HUMAN_QUEUE


def test_any_critical_finding_escalates_regardless_of_high_confidence():
    findings = [finding("LOW"), finding("CRITICAL")]

    assert evaluate(findings, confidence=0.99, confidence_threshold=0.7) == GateDecision.ESCALATE


def test_critical_finding_escalates_even_with_low_confidence_not_just_queued():
    assert evaluate([finding("CRITICAL")], confidence=0.1, confidence_threshold=0.7) == GateDecision.ESCALATE
