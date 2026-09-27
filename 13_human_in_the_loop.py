"""13 — Human in the loop: AskUser questions + tool approval.

Two primitives, same UI story:

A) AskUser (harness): the model asks YOU multiple-choice questions mid-run
   via the `ask_user` tool. You supply the `answerer`: terminal menu here,
   a web form / websocket push in a UI (`Answerer` is just an async callable).

B) Tool approval (core): `@agent.tool(requires_approval=True)` pauses the
   run with `DeferredToolRequests`; you approve/deny, then resume with
   `deferred_tool_results=...`. The built-in web UI (`agent.to_web()`)
   renders these as approve/reject prompts with zero extra code; the AG-UI
   adapter maps them to interrupts for custom frontends.

Non-interactive mode for scripts/CI: HITL_AUTO=1 picks option 1 / approves.

Try:
    HITL_AUTO=1 uv run python 13_human_in_the_loop.py
    uv run python 13_human_in_the_loop.py              # real terminal prompts
    HITL_AUTO=1 uv run python 13_human_in_the_loop.py  # + PYDANTIC_AI_MODEL for live
"""
import json
import os

from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults
from pydantic_ai_harness.ask_user import (
    AskUser,
    AskUserAnswer,
    AskUserRequest,
    AskUserResponse,
)

from common import get_model, tool_names

AUTO = os.getenv("HITL_AUTO", "") == "1"


async def terminal_answerer(request: AskUserRequest, /) -> AskUserResponse:
    """An Answerer that asks in the terminal. Swap for a web form in a UI."""
    answers: list[AskUserAnswer] = []
    for q in request.questions:
        print(f"\n[agent asks] {q.header}: {q.question}")
        for i, opt in enumerate(q.options, 1):
            print(f"  {i}. {opt.label} — {opt.description}")
        if AUTO or not q.options:
            pick = 1
            print("(auto) picked 1")
        else:
            pick = int(input(f"Pick 1-{len(q.options)} (0 = decline): ") or "1")
        if pick == 0:
            return AskUserResponse(answers=[], cancelled=True)
        answers.append(AskUserAnswer(header=q.header, selected=[q.options[pick - 1].label]))
    return AskUserResponse(answers=answers, cancelled=False)


ask_agent = Agent(
    get_model(),
    instructions="When a choice genuinely matters, ask the user via ask_user.",
    capabilities=[AskUser(answerer=terminal_answerer)],
)


approve_agent = Agent(
    get_model(),
    instructions="Use wipe_cache to clear caches when asked.",
    output_type=[str, DeferredToolRequests],
)


@approve_agent.tool_plain(requires_approval=True)
def wipe_cache(scope: str) -> str:
    """Wipe a cache scope. Dangerous: needs human approval."""
    return f"wiped {scope}"


def run_with_approval(prompt: str) -> None:
    r1 = approve_agent.run_sync(prompt)
    if not isinstance(r1.output, DeferredToolRequests):
        print("no approval needed:", r1.output)
        return
    results: dict[str, object] = {}
    for call in r1.output.approvals:
        args = call.args if isinstance(call.args, dict) else json.loads(call.args or "{}")
        argstr = "".join(f" {k}={v!r}" for k, v in args.items())
        print(f"\n[approval] {call.tool_name}({args} )")
        ok = True if AUTO else (input("Approve? [y/N] ").lower() == "y")
        from pydantic_ai.tools import ToolApproved, ToolDenied

        results[call.tool_call_id] = ToolApproved() if ok else ToolDenied("denied by human")
        print("(auto) approved" if AUTO and ok else "")
    r2 = approve_agent.run_sync(
        prompt,
        message_history=r1.all_messages(),
        deferred_tool_results=DeferredToolResults(approvals=results),
    )
    print("after approval:", r2.output)
    print("tools:", tool_names(r2))


def main() -> None:
    print("=== A) ask_user ===")
    try:
        r = ask_agent.run_sync("Should I use tabs or spaces? Ask me.")
        print("answer:", r.output)
    except Exception as e:  # noqa: BLE001 - small free models wrap options oddly
        print("(model quirk: free-tier models send options as {'item': [...]}")
        print(f" rather than [...], failing schema validation: {type(e).__name__})")

    print("\n=== B) tool approval ===")
    try:
        run_with_approval("Wipe the thumbnail cache.")
    except Exception as e:  # noqa: BLE001
        print(f"(test-model caveat: {type(e).__name__}: {str(e)[:150]})")

    print("\n=== C) web UI ===")
    print("Serve this same agent in a browser with approval prompts built in:")
    print("  uvicorn myapp:app  # where app = approve_agent.to_web()")
    print("Verified: to_web() builds a Starlette app; requires_approval tools")
    print("render as approve/reject prompts, no extra code. Custom frontend?")
    print("Use the AG-UI adapter: requires_approval tools map to interrupts;")
    print("resume[] carries {approved, editedArgs, reason}. AskUser in a UI =")
    print("pass a web-form Answerer (same async signature as terminal_answerer).")


if __name__ == "__main__":
    main()
