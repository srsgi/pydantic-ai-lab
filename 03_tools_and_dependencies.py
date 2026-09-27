"""03 — Tools + dependency injection.

Tools give the agent actions. `@agent.tool` functions receive a
`RunContext[Deps]` (your deps: DB handles, config, user id...).
Everything else in the signature becomes the LLM-facing tool schema,
derived from type hints + docstring. Args are validated before your code runs.

Try: uv run python 03_tools_and_dependencies.py
"""
from dataclasses import dataclass

from pydantic_ai import Agent, RunContext

from common import get_model, tool_names


@dataclass
class Deps:
    user_id: int
    # In real code: db connection, http client, config...
    balances: dict[int, float]


agent = Agent(
    get_model(),
    deps_type=Deps,
    instructions="You are a bank support agent. Use tools to look up facts.",
)


@agent.tool
async def get_balance(ctx: RunContext[Deps], include_pending: bool) -> float:
    """Returns the customer's current account balance.

    Args:
        include_pending: Whether to include pending transactions.
    """
    base = ctx.deps.balances.get(ctx.deps.user_id, 0.0)
    return base + (10.0 if include_pending else 0.0)


@agent.tool_plain
def celsius_to_fahrenheit(celsius: float) -> float:
    """Convert Celsius to Fahrenheit. Use for weather questions."""
    return celsius * 9 / 5 + 32


def main() -> None:
    deps = Deps(user_id=123, balances={123: 100.0})
    result = agent.run_sync("What is my balance including pending?", deps=deps)
    print("output:", result.output)
    print("tools called:", tool_names(result))


if __name__ == "__main__":
    main()
