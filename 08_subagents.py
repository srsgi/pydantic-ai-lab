"""08 — Sub-agents: delegation.

Two patterns:

A) Manual delegation (no harness): an @agent.tool that calls another
   agent's run() inside. Simple, explicit, works everywhere.
B) SubAgents capability: `delegate_task` tool that spawns named child
   agents with isolated context, depth limits, usage forwarding.

Try: uv run python 08_subagents.py
"""
from pydantic_ai import Agent, RunContext

from common import get_model

MODEL = get_model()

# --- Pattern A: manual delegation via a tool ---
researcher = Agent(MODEL, instructions="You research a topic in 2 sentences.")
writer = Agent(MODEL, instructions="You turn research into a one-line summary.")


@writer.tool
async def do_research(ctx: RunContext[None], topic: str) -> str:
    """Delegate research to the researcher sub-agent."""
    r = await researcher.run(topic, usage=ctx.usage)
    return r.output


# --- Pattern B: SubAgents capability ---
# from pydantic_ai_harness.subagents import SubAgents
# from pydantic_ai_harness.subagents import SubAgent  # named child spec
#
# boss = Agent(
#     MODEL,
#     instructions="Delegate self-contained subtasks, then synthesize.",
#     capabilities=[
#         SubAgents(
#             # agents=[SubAgent(name="explorer", agent=researcher)],
#             include_self=False,  # True lets it delegate to a fresh copy of itself
#             max_depth=3,
#         )
#     ],
# )


def main() -> None:
    r = writer.run_sync("Research pydantic-ai capabilities and summarize.")
    print("pattern A output:", r.output)
    print("\nPattern B (SubAgents) needs a real model to shine — uncomment")
    print("the block above and set PYDANTIC_AI_MODEL to try delegate_task.")


if __name__ == "__main__":
    main()
