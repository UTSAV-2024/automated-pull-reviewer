def flatten_findings(findings_by_agent: dict[str, list[dict]]) -> list[dict]:
    return [finding for findings in findings_by_agent.values() for finding in findings]


def _dedup_key(finding: dict) -> tuple:
    return (finding.get("file"), finding.get("line"), finding.get("category"))


def deduplicate(findings: list[dict]) -> list[dict]:
    """Merge findings raised by more than one specialist for the same
    file/line/category: several agents flagging the same issue slightly
    differently is a signal, not noise. Keeps the highest-confidence version
    and records which agents agreed."""
    merged: dict[tuple, dict] = {}
    for finding in findings:
        key = _dedup_key(finding)
        if key not in merged:
            merged[key] = {**finding, "agreeing_agents": [finding["agent_type"]]}
            continue
        existing = merged[key]
        agreeing = existing["agreeing_agents"] + [finding["agent_type"]]
        if finding["confidence"] > existing["confidence"]:
            merged[key] = {**finding, "agreeing_agents": agreeing}
        else:
            existing["agreeing_agents"] = agreeing
    return list(merged.values())


def overall_confidence(findings: list[dict]) -> float:
    """One overall confidence score for the review: the lowest per-finding
    confidence, since the HITL gate must be as cautious as its least-confident
    finding — three easy findings shouldn't paper over one shaky one."""
    if not findings:
        return 1.0
    return min(finding["confidence"] for finding in findings)


def aggregate(findings_by_agent: dict[str, list[dict]]) -> dict:
    """Wait-for-all-four join happens upstream in the orchestrator graph; this
    merges the results into one de-duplicated finding list plus one score."""
    findings = deduplicate(flatten_findings(findings_by_agent))
    return {"findings": findings, "confidence": overall_confidence(findings)}
