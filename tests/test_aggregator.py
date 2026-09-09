from orchestrator.aggregator import aggregate, deduplicate, overall_confidence


def finding(agent_type, file="app.py", line=10, category="injection", confidence=0.5, rationale="r"):
    return {
        "agent_type": agent_type,
        "severity": "HIGH",
        "category": category,
        "file": file,
        "line": line,
        "confidence": confidence,
        "rationale": rationale,
    }


def test_distinct_findings_are_all_kept():
    findings = [finding("security", file="a.py"), finding("quality", file="b.py")]

    result = deduplicate(findings)

    assert len(result) == 2


def test_overlapping_findings_are_merged_with_agreeing_agents_recorded():
    findings = [
        finding("security", confidence=0.6, rationale="security take"),
        finding("quality", confidence=0.9, rationale="quality take"),
    ]

    result = deduplicate(findings)

    assert len(result) == 1
    merged = result[0]
    assert set(merged["agreeing_agents"]) == {"security", "quality"}
    # Higher-confidence version wins as the surfaced rationale/confidence.
    assert merged["confidence"] == 0.9
    assert merged["rationale"] == "quality take"


def test_overall_confidence_is_the_minimum_across_findings():
    findings = [finding("security", confidence=0.9), finding("quality", file="b.py", confidence=0.3)]

    assert overall_confidence(findings) == 0.3


def test_overall_confidence_with_no_findings_is_fully_confident():
    assert overall_confidence([]) == 1.0


def test_aggregate_waits_for_all_four_and_merges_into_one_result():
    findings_by_agent = {
        "security": [finding("security", confidence=0.6)],
        "quality": [finding("quality", confidence=0.9)],
        "tests": [finding("tests", file="c.py", confidence=0.8)],
        "docs": [],
    }

    result = aggregate(findings_by_agent)

    assert len(result["findings"]) == 2  # security+quality merged, tests distinct
    assert result["confidence"] == 0.8  # min across the two distinct findings
