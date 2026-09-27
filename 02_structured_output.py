"""02 — Structured output.

Plain text is fine for chat; production code needs guaranteed shape.
`output_type=SomeBaseModel` makes the model return that type, validated
with Pydantic. On validation failure the agent retries automatically.

Try: uv run python 02_structured_output.py
"""
from pydantic import BaseModel, Field

from pydantic_ai import Agent

from common import get_model


class SalesInsight(BaseModel):
    total_revenue: float = Field(description="Total revenue in USD")
    best_region: str
    recommendation: str


agent = Agent(
    get_model(),
    output_type=SalesInsight,
    instructions="Analyze sales data and return structured insights.",
)


def main() -> None:
    result = agent.run_sync(
        """Q1 sales:
        - North: $385,000 (470 units)
        - South: $256,000 (334 units)
        - East: $391,500 (381 units)
        Analyze and provide insights."""
    )
    out = result.output
    print(type(out), out)
    # With the 'test' model output is canned but still validated into SalesInsight.
    # With a real model you get real extraction, same type every time.


if __name__ == "__main__":
    main()
