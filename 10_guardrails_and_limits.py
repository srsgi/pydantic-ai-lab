"""10 — Guardrails + context controls (safe long runs).

- InputGuardrail / OutputGuardrail: validate/block/redact. Guard funcs
  return GuardrailResult.allow() or .block(reason).
- ToolOutputLimits: truncate/spill/summarize oversized tool returns at source.
- ClearToolResults: drop old tool results to keep context small (hour-ten fix).

Try: uv run python 10_guardrails_and_limits.py
"""
from pydantic_ai import Agent
from pydantic_ai_harness.compaction import ClearToolResults
from pydantic_ai_harness.guardrails import GuardrailResult, InputGuardrail, OutputGuardrail
from pydantic_ai_harness.tool_output_limits import ToolOutputLimits

from common import get_model


def no_secrets(prompt: str) -> GuardrailResult:
    if "api_key" in prompt.lower():
        return GuardrailResult.block("Message looks like it contains an API key.")
    return GuardrailResult.allow()


def no_paste_output(output: str) -> GuardrailResult:
    if "BEGIN PRIVATE KEY" in output:
        return GuardrailResult.block("Output would leak a private key.")
    return GuardrailResult.allow()


agent = Agent(
    get_model(),
    instructions="Be helpful and concise.",
    capabilities=[
        InputGuardrail(guard=no_secrets),
        OutputGuardrail(guard=no_paste_output),
        ToolOutputLimits(),  # bounded tool returns by default
        ClearToolResults(max_tokens=20000, keep_pairs=3),  # keep recent, clear old
    ],
)


@agent.tool_plain
def huge_output() -> str:
    """Return a large blob to demonstrate truncation."""
    return "x" * 100_000


def main() -> None:
    r = agent.run_sync("Hello, what can you do?")
    print("ok output:", r.output)

    blocked = agent.run_sync("Here is my api_key=12345, what do I do?")
    print("guarded output:", blocked.output)


if __name__ == "__main__":
    main()
