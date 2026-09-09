import httpx

GITHUB_API_BASE = "https://api.github.com"


def _finding_to_comment(finding: dict) -> dict:
    # ponytail: GitHub requires a line for an inline comment; a finding
    # without one (e.g. a docs-level observation) falls back to line 1
    # rather than being dropped.
    return {
        "path": finding["file"],
        "line": finding.get("line") or 1,
        "body": (
            f"**[{finding['severity']}] {finding['category']}** "
            f"({finding['agent_type']}, confidence {finding['confidence']:.2f})\n\n{finding['rationale']}"
        ),
    }


async def post_review(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    pull_number: int,
    token: str,
    findings: list[dict],
    summary: str = "Automated review",
) -> dict:
    """Post a structured review to GitHub with findings attached to specific
    files/lines (FR-8)."""
    comments = [_finding_to_comment(f) for f in findings]
    response = await client.post(
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={"body": summary, "event": "COMMENT", "comments": comments},
    )
    response.raise_for_status()
    return response.json()
