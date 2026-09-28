"""Serve a lab agent as a web chat UI. Fresh prompts in the chat box start
new runs; requires_approval tools pause with approve/reject buttons.

Run: SERVE_AGENT=researcher     uv run uvicorn serve_web:app --host 127.0.0.1 --port 7933
     SERVE_AGENT=approval       uv run uvicorn serve_web:app --host 127.0.0.1 --port 7932
     SERVE_AGENT=acptest        uv run uvicorn serve_web:app --host 127.0.0.1 --port 7941
     SERVE_AGENT=researchplan   uv run uvicorn serve_web:app --host 127.0.0.1 --port 7934
     SERVE_AGENT=researchexecute uv run uvicorn serve_web:app --host 127.0.0.1 --port 7935
     SERVE_AGENT=researchflow   uv run uvicorn serve_web:app --host 127.0.0.1 --port 7936
Then open the URL. Local-only: put auth in front before exposing beyond localhost.
"""
import os
from pathlib import Path

from pydantic_ai import Agent, DeferredToolRequests

from common import WEBUI_MODELS, get_model, make_researcher_agent, omni_model

WHICH = os.getenv("SERVE_AGENT", "approval")

if WHICH == "researcher":
    agent = make_researcher_agent()
elif WHICH in ("researchplan", "researchexecute", "researchflow"):
    # Split-phase research flow; builders live in research_agents.py so the
    # standalone backends and the flow orchestrator share the SAME planner
    # and executor instances (same factories, same tools, same validation).
    # Boundaries hold by construction: planner has no I/O tools, executor
    # has no planning tools, flow has neither (only 3 delegate tools).
    # Patched chat CSS (lab_web_ui.html): wraps long lines, wider column.
    from research_agents import (
        build_executor_agent,
        build_flow_agent,
        build_planner_agent,
    )

    if WHICH == "researchplan":
        agent = build_planner_agent()
    elif WHICH == "researchexecute":
        agent = build_executor_agent()
    else:
        agent = build_flow_agent()
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
    models={mid.split("/")[-1]: omni_model(mid) for mid in WEBUI_MODELS},
    # Patched chat CSS (wraps code, wider column); other agents keep CDN UI.
    html_source=(str(Path(__file__).parent / "lab_web_ui.html")
                 if WHICH in ("researchplan", "researchexecute", "researchflow")
                 else None),
)

if WHICH in ("researchplan", "researchexecute", "researchflow"):
    # The UI shell ships `cache-control: public, max-age=3600`, so browsers
    # kept showing the pre-patch CDN copy after restart. Force no-store.
    _INNER = app

    class _NoStoreMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope.get("type") != "http":
                await self.app(scope, receive, send)
                return

            async def _send(message):
                if message.get("type") == "http.response.start":
                    headers = [(k, v) for k, v in message.get("headers", [])
                               if k.lower() != b"cache-control"]
                    headers.append((b"cache-control", b"no-store"))
                    message = {**message, "headers": headers}
                await send(message)

            await self.app(scope, receive, _send)

    app = _NoStoreMiddleware(_INNER)
