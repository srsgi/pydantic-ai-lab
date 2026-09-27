"""04 — The autonomous loop: limits, retries, multi-turn state.

An "autonomous" agent is just this loop left to run:
  model -> tool calls -> model -> ... -> structured output
with budgets so it can't run forever.

Key knobs shown here:
- UsageLimits(request_limit, tool_calls_limit, total_tokens_limit)
- retries={'tools': N, 'output': M}
- message_history: continue a conversation across runs
- agent.iter(): low-level graph iteration for visibility

Try: uv run python 04_autonomous_loop.py
"""
import asyncio

from pydantic_ai import Agent, UsageLimits

from common import get_model

agent = Agent(
    get_model(),
    instructions="Break tasks into steps. Use tools when available. Be concise.",
    retries={"tools": 3, "output": 1},
)


@agent.tool_plain
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


@agent.tool_plain
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b


async def main() -> None:
    limits = UsageLimits(request_limit=10, tool_calls_limit=10, total_tokens_limit=5000)

    r1 = await agent.run("What is 2 + 3?", usage_limits=limits)
    print("turn 1:", r1.output)

    # Continue the same conversation by passing history back in.
    r2 = await agent.run(
        "Now multiply that result by 10.",
        message_history=r1.all_messages(),
        usage_limits=limits,
    )
    print("turn 2:", r2.output)
    print("usage:", r2.usage)

    await show_iter()


async def show_iter() -> None:
    print("\n--- agent.iter() trace ---")
    async with agent.iter("What is 4 + 5?") as run:
        async for node in run:
            print(f"node: {type(node).__name__}")


if __name__ == "__main__":
    asyncio.run(main())
