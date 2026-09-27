"""00 — OmniRoute smoke test (local docker provider).

Provider: http://127.0.0.1:20128/v1 (container `omniroute`, OpenAI-compatible).
Models: opencode/space-bunny-free (default, ungated), opencode/big-pickle
(big-pickle's upstream gates all-custom tool lists, so it gets FREETIER_PADDING).
Key: OMNIROUTE_API_KEY in .env (minted in the omniroute DB as `pydantic-ai-lab`).

Try:
    uv run python 00_omniroute_smoke.py
    SMOKE_MODEL=opencode/big-pickle uv run python 00_omniroute_smoke.py
    PYDANTIC_AI_MODEL=test uv run python 00_omniroute_smoke.py  # offline check
"""
import os

from pydantic_ai import Agent

from common import BIG_PICKLE, SPACE_BUNNY, freetier_padding, get_model, tool_names


def check(model_id: str) -> bool:
    os.environ["PYDANTIC_AI_MODEL"] = model_id
    kwargs = {"toolsets": [freetier_padding()]} if model_id == BIG_PICKLE else {}
    agent = Agent(get_model(), instructions="Be concise, one sentence.", **kwargs)

    @agent.tool_plain
    def add(a: float, b: float) -> float:
        """Add two numbers."""
        return a + b

    r = agent.run_sync("What is 21 + 21? Use the add tool, then answer in one sentence.")
    print(f"[{model_id}] output:", r.output)
    print(f"[{model_id}] tools:", tool_names(r))
    print(f"[{model_id}] usage:", r.usage)
    return True


def main() -> int:
    only = os.getenv("SMOKE_MODEL", "")
    targets = [only] if only else [BIG_PICKLE, SPACE_BUNNY]
    ok = True
    for m in targets:
        try:
            check(m)
        except Exception as e:  # noqa: BLE001 - smoke test reports, doesn't hide
            print(f"[{m}] FAILED: {type(e).__name__}: {str(e)[:300]}")
            ok = False
    print("\nBoth OmniRoute models work." if ok else "\nSome models failed.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
