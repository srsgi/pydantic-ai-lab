"""Shared builders for the split-phase research agents.

One factory per agent, used both standalone (serve_web backends) and
composed (the Research Flow orchestrator delegates to the SAME planner and
executor instances built here):

  build_planner_agent(interactive=True)  — :7934 standalone. With
      interactive=False it becomes the flow's internal drafter: same
      validation, same submit tool, but skips the opening questions (the
      orchestrator already collected the answers) and goes straight to
      submit_workflow.
  build_executor_agent()                 — :7935 standalone, and the flow's
      runner. Reads workflow.json + approved.json, refuses unless approved.
  build_flow_agent()                     — :7936 orchestrator. Owns NO research
      tools at all (only draft_plan / record_approval_step /
      run_{seed,triage,expand,report}_step, each running a bounded executor
      sub-run), so it cannot self-start execution or replan — the phase
      boundary holds by construction. Each leg result is announced before
      the next call, which IS the progress display.

Handoff files live in workspace/research/ (see research_toolkit helpers).
"""
import json as _json
from pathlib import Path as _Path

from pydantic_ai import Agent, RunContext, UsageLimits
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.toolsets import FunctionToolset as _FunctionToolset
from pydantic_ai_harness.compaction import ClearToolResults
from pydantic_ai_harness.filesystem import FileSystem
from pydantic_ai_harness.planning import Planning
from pydantic_ai_harness.tool_output_limits import ToolOutputLimits

from common import DuckDuckGoPacing, get_model
from research_toolkit import (
    PRESENT_RULES,
    RESEARCH_TOOLKIT,
    query_expand,
    read_cursor,
    record_approval,
    research_toolset,
    validate_workflow,
    workflow_path,
    write_cursor,
)

FLOW_WS = _Path(__file__).parent / "workspace" / "research"
FLOW_WS.mkdir(parents=True, exist_ok=True)
TOOLKIT_HELP = "\n".join(f"- {k}: {v}" for k, v in RESEARCH_TOOLKIT.items())


def _today_line() -> str:
    import datetime as _dt

    now = _dt.datetime.now(_dt.timezone.utc).astimezone()
    return ("Today is " + now.strftime("%A, %d %B %Y (%Z, UTC offset %z)") +
            ". Use this date for all recency judgments; never rely on your "
            "training cutoff for 'current' facts — verify via tools, "
            "preferring sources from the last 12 months for limits/pricing.")


TODAY = _today_line()

# Budgets so delegated runs can never spin forever: on exhaustion the tool
# returns a BUDGET-HIT message and the orchestrator tells the user, who can
# say "continue" (resume=last summary) to carry on from workspace files.
DRAFT_LIMITS = {"request_limit": 15, "tool_calls_limit": 30}
LEG_LIMITS = {
    "seed": {"request_limit": 15, "tool_calls_limit": 30},
    "triage": {"request_limit": 30, "tool_calls_limit": 60},
    "expand": {"request_limit": 20, "tool_calls_limit": 40},
    "report": {"request_limit": 20, "tool_calls_limit": 40},
}

SUBMIT_SHAPE = """Copy this exact shape (standard task); change ONLY the topic-specific
strings. Allowed node kinds: task, branch, fanout, recurse, join,
human_gate. Task/fanout/recurse nodes need "tool" (one of the 8).
{"topic":"...","strategy":"...","complexity":"standard",
"complexity_why":"...","criteria":"...","schema_hint":"...",
"limits":{"max_depth":2,"max_nodes":60,"max_accepts":30},
"source_config":{"source":"generic","site":"example.com"},"entry":"expand",
"nodes":[{"id":"expand","kind":"task","tool":"query_expand","task":"..."},
{"id":"seed","kind":"fanout","tool":"structured_search","task":"...","over":"expand","join_to":"triage"},
{"id":"triage","kind":"branch","task":"...","on_accept":"expand_more","on_reject":"drop","on_uncertain":"deep_dive"},
{"id":"deep_dive","kind":"task","tool":"deep_fetch","task":"..."},
{"id":"expand_more","kind":"recurse","tool":"frontier_expand","task":"...","recurse_to":"triage"},
{"id":"drop","kind":"task","task":"Terminal: pruned candidate"},
{"id":"report","kind":"task","tool":"synthesize","task":"...","params":{"mode":"final"}}]}"""


def build_planner_agent(model=None, interactive: bool = True) -> Agent:
    """Planner: questions -> submit -> present -> approve. No I/O tools."""
    step1 = (
        "Step 1 — FIRST message: ask ONLY 3-6 short clarifying "
        "questions (scope, language, depth, exhaustive vs top-N, "
        "sources). No plan, no tool calls, no facts, no source lists. "
        "Wait for answers.\n"
        if interactive else
        "Step 1 — skipped: the topic and the user's answers are given in "
        "your prompt. Go straight to Step 2, no questions.\n"
    )
    agent = Agent(
        model or get_model(),
        name="research-planner",
        instructions=(
            TODAY + "\n"
            "You are the research PLANNER. You cannot search, fetch, or "
            "execute anything (you have no such tools) — your only job is "
            "to agree the workflow with the user.\n"
            + step1 +
            "Step 2 — set complexity (quick = single 1-2 question lookup, no "
            "branch/recurse; standard = multi-source comparison; deep = "
            "snowball/exhaustive with branch+recurse) and call submit_workflow "
            "once per revision (exact shape is in its description — copy it, "
            "change only topic strings). A rejection lists exact fixes: apply "
            "only those, resubmit. The graph holds QUERIES and criteria, "
            "never findings.\n"
            "Step 3 — present the VALIDATED plan. " + PRESENT_RULES +
            " Ask: approve, or what to change — and WAIT.\n"
            + ("Step 4 — when the user explicitly approves (approve / go / "
                "looks good): call mark_approved once, then tell them to open "
                "Research Execute to run it. One topic at a time; a new topic "
                "restarts at Step 1.\n" if interactive else
                "Step 4 — not yours: just return the VALID plan JSON and stop. "
                "Approval and execution happen outside you.\n") +
            "Never narrate tool internals or retries — only questions, "
            "plan progress, and the approval handoff.\n"
            "Workflow shape for submit_workflow (copy exactly, change only "
            "topic strings):\n" + SUBMIT_SHAPE,
        ),
        toolsets=[_FunctionToolset([query_expand])],
    )

    @agent.tool_plain
    def submit_workflow(plan_json: str) -> str:
        """Submit the workflow graph JSON for validation.

        Must satisfy: known tools only, resolvable edges, no memorized facts.
        Branching + recursion are required for standard/deep tasks; set
        complexity=quick with a reason for single-question tasks to skip them.
        Persists workspace/research/workflow.json on success. Returns VALID
        or a rejection listing exact fixes (no exception — just resubmit).
        """
        try:
            wf = validate_workflow(_json.loads(plan_json))
        except Exception as e:  # noqa: BLE001 - return, don't burn retries
            return ("REJECTED — fix ONLY the listed items and resubmit:\n" + str(e)[:1500])
        workflow_path(FLOW_WS).write_text(wf.model_dump_json(indent=2))
        return (f"VALID ({len(wf.nodes)} nodes, complexity={wf.complexity}, "
                f"strategy={wf.strategy}). " + SUBMIT_SHAPE)

    if interactive:
        @agent.tool_plain
        def mark_approved() -> str:
            """Record the user's explicit approval of the presented plan.

            Call ONLY after the user approved in chat (approve / go / looks
            good). Writes approved.json; then direct the user to Research
            Execute — planning is done.
            """
            wp = workflow_path(FLOW_WS)
            if not wp.exists():
                return "No validated plan yet — submit_workflow first."
            try:
                topic = validate_workflow(_json.loads(wp.read_text())).topic
            except Exception as e:  # noqa: BLE001
                return f"Stored plan is invalid ({str(e)[:150]}) — resubmit first."
            record_approval(FLOW_WS, topic)
            return (f"Approval recorded for {topic!r}. Tell the user to open "
                    "Research Execute now — planning is done.")

    return agent


def build_executor_agent(model=None) -> Agent:
    """Executor: runs the approved on-disk plan. No planning tools."""
    return Agent(
        model or get_model(),
        name="research-executor",
        instructions=(
            TODAY + "\n"
            "You are the research EXECUTOR. You never plan — execute the "
            "approved plan only. Each run starts by reading workspace "
            "files with the filesystem tools:\n"
            "1. Read workflow.json and approved.json in the workspace root. "
            "If either is missing, topics mismatch, or the plan is not "
            "approved: STOP and tell the user to finish Research Plan "
            "first (questions, submit, present, approve). Research nothing.\n"
            "2. Otherwise announce in ONE short message (topic, strategy, "
            "complexity, limits, and that deep runs take many minutes of paced "
            "searches — the tool badge spinning means active, not stuck) and "
            "execute immediately:\n"
            + TOOLKIT_HELP + "\n\n"
            "Rules: follow the plan graph (entry first; fanout per query; "
            "branch every candidate on relevance_classify labels; recurse "
            "via frontier_expand within limits / frontier-empty / "
            "no-new-accepts); verify citations before the final synthesize; "
            "write findings.json + report.md beside workflow.json; end with "
            "a short sourced summary. Every fact, figure, or URL must come "
            "from a tool result quoted with its source — never from memory; "
            "say so when a tool comes back empty. Tables/bullets, lines "
            "<=100 chars, never fenced code blocks or ASCII trees. Never "
            "narrate tool internals."
        ),
        capabilities=[
            Planning(),
            FileSystem(root_dir=str(FLOW_WS)),
            ToolOutputLimits(),
            ClearToolResults(max_tokens=20000, keep_pairs=3),
            DuckDuckGoPacing(),
        ],
        toolsets=[research_toolset()],
    )


def build_flow_agent(model=None) -> Agent:
    """Orchestrator: talks to the user, executes the plan leg by leg.

    Owns zero research tools — only draft_plan / record_approval_step /
    run_{seed,triage,expand,report}_step, each running a bounded executor
    sub-run and returning its result, announced before the next call. That
    per-leg narration IS the progress display: no silent 15-minute blocks.
    """
    m = model or get_model()
    planner = build_planner_agent(model=m, interactive=False)
    executor = build_executor_agent(model=m)

    agent = Agent(
        m,
        name="research-flow",
        instructions=(
            "You are the research FLOW orchestrator. You hold the user "
            "conversation; the planner and executor sub-agents do the work "
            "via your three tools. Follow this script exactly:\n"
            "1. FIRST message: ask ONLY 3-6 short clarifying questions "
            "(scope, language, depth, exhaustive vs top-N, sources). No plan, "
            "no tool calls, no facts. Wait for answers.\n"
            "2. After answers: call draft_plan ONCE with the topic, the "
            "user's answers, and empty feedback. If it returns REJECTED, call "
            "draft_plan again with the SAME topic/answers plus the rejection "
            "text as feedback (fix only listed items). Repeat until VALID — "
            "never more than 4 attempts; then summarize and stop.\n"
            "3. Present the VALIDATED plan: " + PRESENT_RULES +
            " Ask: approve, or what to change — and WAIT. "
            "If changes: redraft with feedback, re-present.\n"
            "4. On explicit approval (approve / go / looks good): call "
            "record_approval_step once, then execute leg by leg, announcing "
            "each leg's result briefly before the next call (this narration "
            "IS the progress display — never skip it):\n"
            "   a. run_seed_step once → announce query/candidate counts.\n"
            "   b. run_triage_step once → announce accept/reject/uncertain counts.\n"
            "   c. Up to 3 rounds: run_expand_step → if it says DONE or limits "
            "hit, go to (d); else run_triage_step for the new queued batch.\n"
            "   d. run_report_step once → present the findings summary with "
            "file locations.\n"
            "   On BUDGET-HIT: tell the user in one line, retry the SAME leg "
            "once; if it hits again, stop and report workspace state.\n"
            "One topic at a time; a new topic restarts at step 1. Never "
            "narrate tool internals or retries."
        ),
    )

    @agent.tool
    async def draft_plan(ctx: RunContext[None], topic: str, answers: str,
                        feedback: str = "") -> str:
        """Draft (or redraft) the validated workflow via the planner sub-agent.

        Pass the topic, the user's answers, and any prior rejection as
        feedback. Returns VALID + plan JSON, or REJECTED with fixes.
        """
        prompt = (f"Topic: {topic}\nUser answers: {answers}\n"
                  f"Prior rejection to fix (empty = first draft): {feedback}\n"
                  "Draft the validated workflow now: submit immediately, "
                  "fix-only resubmits on rejection, then reply with the full "
                  "VALID plan JSON and stop.")
        try:
            r = await planner.run(
                prompt, usage=ctx.usage,
                usage_limits=UsageLimits(request_limit=DRAFT_LIMITS["request_limit"],
                                         tool_calls_limit=DRAFT_LIMITS["tool_calls_limit"]))
        except UsageLimitExceeded as e:  # noqa: BLE001 - bounded, resumable
            return ("BUDGET-HIT drafting (limits requests<=15, tools<=30): "
                    f"{str(e)[:200]} Tell the user; to continue, call draft_plan "
                    "again with feedback=continue-from-budget.")
        return str(r.output)

    @agent.tool
    async def record_approval_step(ctx: RunContext[None]) -> str:
        """Record the user's chat approval on disk. Call ONCE, only after the
        user explicitly approved the presented plan."""
        del ctx
        wp = workflow_path(FLOW_WS)
        if not wp.exists():
            return "No validated plan on disk — draft_plan first."
        try:
            from research_toolkit import validate_workflow as _v

            topic = _v(_json.loads(wp.read_text())).topic
        except Exception as e:  # noqa: BLE001
            return f"Stored plan invalid ({str(e)[:150]}) — redraft first."
        record_approval(FLOW_WS, topic)
        return (f"Approval recorded for {topic!r}. Now run the legs, "
                "starting with run_seed_step.")

    def _plan_brief() -> str:
        try:
            plan = _json.loads(workflow_path(FLOW_WS).read_text())
        except Exception:
            return ""
        return (f"topic={plan.get('topic','')} | criteria={plan.get('criteria','')[:300]} | "
                f"source_config={_json.dumps(plan.get('source_config', {}))[:300]} | "
                f"limits={_json.dumps(plan.get('limits', {}))[:200]} | "
                f"schema={str(plan.get('schema_hint',''))[:200]}")

    async def _run_leg(ctx: RunContext[None], leg: str, prompt: str) -> str:
        from research_toolkit import load_handoff as _lh

        _, problem = _lh(FLOW_WS)
        if problem:
            return f"REFUSED {leg}: {problem}"
        lim = LEG_LIMITS[leg]
        try:
            r = await executor.run(
                prompt, usage=ctx.usage,
                usage_limits=UsageLimits(request_limit=lim["request_limit"],
                                         tool_calls_limit=lim["tool_calls_limit"]))
        except UsageLimitExceeded as e:  # noqa: BLE001 - ledger persists; retryable
            return (f"BUDGET-HIT {leg} (limits {lim}): {str(e)[:200]} "
                    "Ledger/ledger.json persist — retry this SAME leg to continue.")
        cur = read_cursor(FLOW_WS)
        cur["legs"].append(leg)
        cur["last_" + leg] = str(r.output)[:500]
        write_cursor(FLOW_WS, cur)
        return str(r.output)

    @agent.tool
    async def run_seed_step(ctx: RunContext[None]) -> str:
        """Leg 1: expand queries + seed candidates into ledger.json (queued).
        Call ONCE after record_approval_step. Returns counts."""
        return await _run_leg(
            ctx, "seed",
            "LEG=seed. Plan brief: " + _plan_brief() +
            " Do ONLY this leg: (1) query_expand the topic across "
            "languages/synonyms/subtopics; (2) structured_search each query "
            "with the plan source_config; (3) write NEW candidate refs to "
            "ledger.json as queued (dedupe; depth 0). Reply: queries used, "
            "N new queued, M total in ledger. Nothing else.")

    @agent.tool
    async def run_triage_step(ctx: RunContext[None], batch: int = 25) -> str:
        """Leg 2: classify queued candidates (accept/reject/uncertain) per the
        plan criteria. Call after seed, and after each expand leg."""
        return await _run_leg(
            ctx, "triage",
            "LEG=triage. Plan brief: " + _plan_brief() +
            f" Do ONLY this leg: read ledger.json queued (first {batch}); for "
            "each, sample + deep_fetch as needed, relevance_classify vs the "
            "plan criteria; update status/reason/evidence in ledger.json. "
            "Reply counts + top accepts with evidence. Nothing else.")

    @agent.tool
    async def run_expand_step(ctx: RunContext[None]) -> str:
        """Leg 3: snowball from accepted candidates into new queued refs.
        Reply DONE when nothing new or limits hit."""
        return await _run_leg(
            ctx, "expand",
            "LEG=expand. Plan brief: " + _plan_brief() +
            " Do ONLY this leg: read accepted entries not yet expanded "
            "(track in ledger expanded list; add each after use); "
            "frontier_expand each per the plan recurse node; add NEW refs as "
            "queued with depth+1 respecting max_depth; stop early when no new "
            "refs or max_accepts reached. Reply new-queued count, or DONE "
            "with the stop reason. Nothing else.")

    @agent.tool
    async def run_report_step(ctx: RunContext[None]) -> str:
        """Leg 4 (final): verify accepted entries, write findings.json +
        report.md, reply the sourced summary."""
        return await _run_leg(
            ctx, "report",
            "LEG=report. Plan brief: " + _plan_brief() +
            " Do ONLY this leg: re-fetch key claims for accepted entries, "
            "write findings.json + report.md beside workflow.json per the "
            "schema hint, reply the short sourced summary with file paths.")

    return agent
