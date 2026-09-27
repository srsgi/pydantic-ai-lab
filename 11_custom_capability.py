"""11 — Build your own capability (the one primitive).

Every harness feature is an AbstractCapability bundling:
  tools + instructions + hooks + model settings.
Subclass it, override get_instructions() / get_toolset(), add to
capabilities=[...]. This example adds a tiny on-demand date tool +
working-hours guidance.

Try: uv run python 11_custom_capability.py
"""
from datetime import datetime

from pydantic_ai import Agent
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import FunctionToolset

from common import get_model, tool_names


def current_time() -> str:
    """Return the current local time as ISO string."""
    return datetime.now().isoformat(timespec="seconds")


class WorkingHoursCapability(AbstractCapability[None]):
    """Example custom capability: guidance + one tool."""

    def get_instructions(self) -> str:
        return (
            "You know the current time via the current_time tool. "
            "If asked about working hours, compare against 09:00-17:00."
        )

    def get_toolset(self) -> FunctionToolset[None]:
        return FunctionToolset([current_time])


agent = Agent(
    get_model(),
    instructions="Be concise.",
    capabilities=[WorkingHoursCapability()],
)


def main() -> None:
    r = agent.run_sync("What time is it, and am I in working hours?")
    print("output:", r.output)
    print("tool calls:", tool_names(r))
    print("\nThis is how FileSystem/Shell/Memory are built — just bigger.")


if __name__ == "__main__":
    main()
