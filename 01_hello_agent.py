"""01 — Hello agent.

The Agent is a container for: model + instructions + tools + output type.
`run_sync()` drives the loop to completion and returns a RunResult.

NOTE: one event loop per process — use a single asyncio.run() (or only
run_sync calls) so the shared HTTP client isn't bound to a dead loop.

Try:
    uv run python 01_hello_agent.py
    PYDANTIC_AI_MODEL=opencode/space-bunny-free uv run python 01_hello_agent.py
"""
import asyncio

from pydantic_ai import Agent

from common import get_model

# instructions = persistent system guidance for every run.
agent = Agent(
    get_model(),
    instructions="Be concise, reply with one sentence.",
    name="hello",
)


async def main() -> None:
    r1 = await agent.run('Where does "hello world" come from?')
    print("output:", r1.output)
    print("usage:", r1.usage)

    r2 = await agent.run("Say hello to a Python learner in one sentence.")
    print("async output:", r2.output)


if __name__ == "__main__":
    asyncio.run(main())
