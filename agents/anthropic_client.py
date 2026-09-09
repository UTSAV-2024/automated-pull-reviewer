import os

from anthropic import AsyncAnthropic

_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


async def call_claude(system_prompt: str, user_content: str, model: str = "claude-sonnet-5") -> str:
    response = await _get_client().messages.create(
        model=model,
        max_tokens=2048,
        system=system_prompt
        + "\n\nRespond with a JSON array of findings only, each with keys: "
        "severity, category, file, line, confidence, rationale.",
        messages=[{"role": "user", "content": user_content}],
    )
    return "".join(block.text for block in response.content if block.type == "text")
