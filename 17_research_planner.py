"""17 — Research planner: topic + fixed toolkit -> tailored workflow graph.

The planner may ONLY use the 8 generic tools in research_toolkit.py
(query_expand, broad_search, structured_search, deep_fetch, sample,
relevance_classify, frontier_expand, synthesize). Per-topic variance comes
from arrangement + params (source_config, criteria, schema_hint, limits),
never from new tools. Branching/recursion are graph nodes, not tools.

Flow: propose ResearchWorkflow (structured output) -> AskUser confirm loop
-> save workspace/research/<slug>/workflow.json for 18_ to compile.

Try:
    HITL_AUTO=1 uv run python 17_research_planner.py "Kerala cuisine YouTube channels"
    PYDANTIC_AI_MODEL=test HITL_AUTO=1 uv run python 17_research_planner.py "anything"
"""
import json
import os
import sys
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai_harness.ask_user import (
    AskUser,
    AskUserAnswer,
    AskUserRequest,
    AskUserResponse,
)

from common import get_model, run_safe
from research_toolkit import (
    RESEARCH_TOOLKIT,
    ResearchWorkflow,
    demo_workflow_for_topic,
)

AUTO = os.getenv("HITL_AUTO", "") == "1"


async def terminal_answerer(request: AskUserRequest, /) -> AskUserResponse:
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


TOOLKIT_HELP = "\n".join(f"- {k}: {v}" for k, v in RESEARCH_TOOLKIT.items())

planner_agent = Agent(
    get_model(),
    name="research-planner",
    output_type=ResearchWorkflow,
    instructions=(
        "You are a research strategist. You have EXACTLY these 8 generic tools "
        "and no others:\n" + TOOLKIT_HELP + "\n\n"
        "Arrange a minimal sufficient workflow GRAPH for THIS topic: pick entry, "
        "task/fanout nodes (each with one tool from the 8), branch nodes on "
        "relevance_classify labels (on_accept/on_reject/on_uncertain), one "
        "recurse node via frontier_expand, one synthesize(mode=final) node. "
        "Parametrize: source_config (youtube|arxiv|pubmed|generic + site), "
        "criteria string, schema_hint, limits. Same tools, different wiring "
        "per topic. After proposing, use ask_user to confirm or revise."
    ),
    capabilities=[AskUser(answerer=terminal_answerer)],
)


def save_workflow(wf: ResearchWorkflow) -> Path:
    slug = "".join(c.lower() if c.isalnum() else "-" for c in wf.topic)[:40].strip("-")
    outdir = Path(__file__).parent / "workspace" / "research" / (slug or "general")
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "workflow.json"
    path.write_text(wf.model_dump_json(indent=2))
    return path


def main() -> None:
    topic = sys.argv[1] if len(sys.argv) > 1 else "Kerala cuisine YouTube channels"
    print(f"Topic: {topic}")
    print(f"Fixed toolkit: {', '.join(RESEARCH_TOOLKIT)}")
    try:
        result = planner_agent.run_sync(
            f"Propose a research workflow graph for: {topic}. "
            "Then ask me to approve / revise via ask_user."
        )
        wf = result.output
        if not isinstance(wf, ResearchWorkflow):
            raise TypeError(f"unexpected output {type(wf)}")
        print("\n--- proposed workflow ---")
        print(wf.model_dump_json(indent=2)[:4000])
    except Exception as e:  # noqa: BLE001 - test model can't do structured graphs
        print(f"(planner fallback: {type(e).__name__}: {str(e)[:200]})")
        print("Using deterministic demo_workflow_for_topic() instead.")
        wf = demo_workflow_for_topic(topic)
        run_safe(planner_agent, f"Topic {topic!r} uses strategy {wf.strategy}.")
    path = save_workflow(wf)
    print(f"\nSaved: {path} (strategy={wf.strategy}, nodes={len(wf.nodes)})")
    print("Next: uv run python 18_research_compiler.py "
          f"\"{wf.topic}\"  # builds + runs the executor")


if __name__ == "__main__":
    main()
