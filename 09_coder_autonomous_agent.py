"""09 — Coder: the complete autonomous coding agent in one capability.

Coder() is a *combined* capability bundling:
  FileSystem (read/write/edit/list/grep) + Shell (persistent, no allowlist)
  + RepoContext + SubAgents (delegate to itself) + ClearToolResults/
  WarnNearLimits + ToolOutputLimits + default autonomous instructions.

One import = working agent. Take it apart later via the blocks in 05-08+10.

Safe default here: point it at ./workspace, not your repo root.
Pass a prompt via CLI arg, or run interactively with .to_cli_sync().

Try:
    uv run python 09_coder_autonomous_agent.py "list files and summarize notes.txt"
    uv run python 09_coder_autonomous_agent.py --stream "list files and summarize notes.txt"
    PYDANTIC_AI_MODEL="openai:gpt-4o" uv run python 09_coder_autonomous_agent.py "fix the bug in app.py so pytest passes"
"""
import asyncio
import sys
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai_harness.coder import Coder

from common import get_model, run_safe, tool_names

WORKSPACE = Path(__file__).parent / "workspace"
WORKSPACE.mkdir(exist_ok=True)
# Seed a tiny buggy app so the coder has something real to fix.
(APP := WORKSPACE / "app.py").write_text(
    "def parse(text: str) -> str:\n"
    '    """Return stripped text; bug: returns None on empty input."""\n'
    "    if not text:\n"
    "        return None  # BUG: should raise ValueError\n"
    "    return text.strip()\n"
)

agent = Agent(
    get_model(),
    capabilities=[Coder(str(WORKSPACE))],
)


async def main_stream(prompt: str) -> None:
    """Streaming mode: print text deltas + tool calls as they happen.

    Uses run_stream_events (runs the loop to completion, unlike run_stream
    which can stop early once text looks final). Lesson learned: plain
    run_stream + stream_text() defaults to full-text snapshots (prints
    duplicates unless delta=True) and may end before later tool steps.
    """
    from pydantic_ai import AgentRunResultEvent
    from pydantic_ai.messages import FunctionToolCallEvent, PartDeltaEvent, TextPartDelta

    try:
        async with agent.run_stream_events(prompt) as events:
            async for event in events:
                if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                    print(event.delta.content_delta or "", end="", flush=True)
                elif isinstance(event, FunctionToolCallEvent):
                    print(f"\n[tool: {event.part.tool_name}]", flush=True)
                elif isinstance(event, AgentRunResultEvent):
                    print()
                    print("tool calls:", tool_names(event.result))
    except Exception as e:  # noqa: BLE001 - same offline caveat as run_safe
        print(f"\noffline note: test model dummy tool call failed: {type(e).__name__}: {str(e)[:200]}")


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--stream"]
    prompt = args[0] if args else "List files and read notes.txt."
    if "--stream" in sys.argv:
        asyncio.run(main_stream(prompt))
    else:
        run_safe(agent, prompt)
    # Interactive alternative (uncomment): agent.to_cli_sync()


if __name__ == "__main__":
    main()
