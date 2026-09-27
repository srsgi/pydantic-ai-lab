"""00 — Pixel Canary smoke test (Vercel AI Gateway).

Model: stealth/pixel-canary, free while in stealth.
Gateway: https://ai-gateway.vercel.sh/v1 (OpenAI-compatible).
Setup: `npx vercel ai-gateway setup`, then export AI_GATEWAY_API_KEY.

Try:
    export AI_GATEWAY_API_KEY="..."
    uv run python 00_pixel_canary_smoke.py
    PYDANTIC_AI_MODEL=test uv run python 00_pixel_canary_smoke.py  # offline check
"""
import os
import sys

from pydantic_ai import Agent

from common import GATEWAY_BASE_URL, PIXEL_CANARY_MODEL_ID, get_model


def main() -> int:
    if not os.getenv("AI_GATEWAY_API_KEY"):
        print("AI_GATEWAY_API_KEY is not set — offline mode.")
        print("Get one with: npx vercel ai-gateway setup")
        print("Falling back to get_model() =", repr(get_model()))
        agent = Agent(get_model(), instructions="Be concise, one sentence.")
        print("output:", agent.run_sync("Say hello in one sentence.").output)
        return 0

    print(f"model: {PIXEL_CANARY_MODEL_ID}")
    print(f"gateway: {GATEWAY_BASE_URL}")

    agent = Agent(get_model(), instructions="Be concise, reply with one sentence.")

    @agent.tool_plain
    def add(a: float, b: float) -> float:
        """Add two numbers."""
        return a + b

    r1 = agent.run_sync("Reply with exactly: pixel canary online.")
    print("text output:", r1.output)

    r2 = agent.run_sync("What is 21 + 21? Use the add tool.")
    print("tool output:", r2.output)
    print("usage:", r2.usage)
    print("\nPixel Canary via AI Gateway works. Now try:")
    print("  uv run python 09_coder_autonomous_agent.py 'list files and summarize notes.txt'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
