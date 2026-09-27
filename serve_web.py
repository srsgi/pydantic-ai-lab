"""Serve a lab agent as a web chat UI. Fresh prompts in the chat box start
new runs; requires_approval tools pause with approve/reject buttons.

Run: SERVE_AGENT=researcher uv run uvicorn serve_web:app --host 127.0.0.1 --port 7933
     SERVE_AGENT=approval   uv run uvicorn serve_web:app --host 127.0.0.1 --port 7932
     SERVE_AGENT=acptest    uv run uvicorn serve_web:app --host 127.0.0.1 --port 7941
     SERVE_AGENT=acptest    uv run uvicorn serve_web:app --host 127.0.0.1 --port 7941
Then open the URL. Local-only: put auth in front before exposing beyond localhost.
"""
import os

from pydantic_ai import Agent, DeferredToolRequests

from common import WEBUI_MODELS, get_model, make_researcher_agent, omni_model

WHICH = os.getenv("SERVE_AGENT", "approval")

if WHICH == "researcher":
    agent = make_researcher_agent()
elif WHICH == "acptest":
    from acp_harness import DirectHarness, UnifiedHarness

    agent = Agent(
        get_model(),
        name="acp-tester",
        instructions=("Drive CLI harness backends. Two modes: delegate(task, "
                      "backend, model) for one-shot tasks; chat_with(backend, "
                      "message) for direct ongoing conversations (use when the "
                      "user wants to talk to a CLI, run the same probe on "
                      "several backends one by one, and report a table)."),
        capabilities=[UnifiedHarness(cwd="/tmp"), DirectHarness(cwd="/tmp")],
    )
else:
    agent = Agent(
        get_model(),
        instructions="Use wipe_cache to clear caches when asked. Be concise.",
        output_type=[str, DeferredToolRequests],
    )

    @agent.tool_plain(requires_approval=True)
    def wipe_cache(scope: str) -> str:
        """Wipe a cache scope. Dangerous: needs human approval."""
        return f"wiped {scope}"


app = agent.to_web(
    models={mid.split("/")[-1]: omni_model(mid) for mid in WEBUI_MODELS}
)
