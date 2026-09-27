"""07 — Harness: Planning + Memory (long-running coherence).

- Planning(): model-owned task plan with tools like create_plan/update_plan.
  The agent breaks work into steps and keeps the plan current — visible progress.
- Memory(FileStore(...)): persistent namespaced notebook across sessions.
  Bounded injection (max_tokens/max_lines) + on-demand search, so hour-ten
  still fits in context.

Try: uv run python 07_planning_and_memory.py
"""
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai_harness.memory import FileStore, Memory
from pydantic_ai_harness.planning import Planning

from common import get_model, run_safe, tool_names

MEMORY_DIR = Path(__file__).parent / ".agent-memory"
MEMORY_DIR.mkdir(exist_ok=True)

agent = Agent(
    get_model(),
    instructions="Plan multi-step work explicitly. Remember durable facts.",
    capabilities=[
        Planning(),
        Memory(FileStore(str(MEMORY_DIR)), max_tokens=2000, max_lines=200),
    ],
)


def main() -> None:
    run_safe(
        agent,
        "Plan a 3-step refactor of workspace/app.py, then remember that "
        "the project uses Python 3.10 and pytest.",
    )
    print(f"\nMemory persisted under {MEMORY_DIR}/ — run again and it remembers.")


if __name__ == "__main__":
    main()
