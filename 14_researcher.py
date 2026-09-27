"""14 — Researcher: complete web-research agent as one capability.

make_researcher_agent() builds parent + sub-researcher, both with rotating
web search (DDG -> SearXNG -> Exa/Brave) and DDG pacing. No API keys needed
for the keyless path; Exa joins when EXA_API_KEY is set.

Try:
    uv run python 14_researcher.py "What is Pydantic AI Harness?"
    PYDANTIC_AI_MODEL=test uv run python 14_researcher.py "anything"
    # Web UI: SERVE_AGENT=researcher uvicorn serve_web:app (see serve_web.py).
"""
import sys

from pydantic_ai import Agent
from pydantic_ai_harness.researcher import Researcher

from common import make_researcher_agent, run_safe

# Factory equips parent AND sub-researcher with rotating search + pacing.
# (Researcher()'s default sub-agent is bare — that gap caused the
# "delegate_task: No results found" halt under DDG throttling.)
researcher_agent = make_researcher_agent()


def main() -> None:
    prompt = sys.argv[1] if len(sys.argv) > 1 else "What is the Pydantic AI Harness?"
    run_safe(researcher_agent, prompt)


if __name__ == "__main__":
    main()
