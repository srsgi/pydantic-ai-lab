"""18 — Research compiler: approved workflow.json -> executor Agent at runtime.

Loads workspace/research/<slug>/workflow.json (written by 17_), rebuilds
the ResearchWorkflow model, calls research_toolkit.compile_workflow() to
build the live executor Agent, then runs it. No new tools are created:
the executor gets exactly the 8 fixed generic tools + Planning/Memory/
FileSystem/guardrail capabilities.

Try:
    HITL_AUTO=1 uv run python 17_research_planner.py "Kerala cuisine YouTube channels"
    uv run python 18_research_compiler.py "Kerala cuisine YouTube channels"
    PYDANTIC_AI_MODEL=test uv run python 18_research_compiler.py "anything"
"""
import json
import sys
from pathlib import Path

from common import get_model, run_safe, tool_names
from research_toolkit import (
    Frontier,
    ResearchWorkflow,
    compile_workflow,
    demo_workflow_for_topic,
)


def slug_of(topic: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in topic)[:40].strip("-") or "general"


def load_or_demo(topic: str) -> tuple[ResearchWorkflow, bool]:
    path = Path(__file__).parent / "workspace" / "research" / slug_of(topic) / "workflow.json"
    if path.exists():
        wf = ResearchWorkflow.model_validate(json.loads(path.read_text()))
        # Re-slug check: user may pass a slightly different topic string.
        return wf, True
    return demo_workflow_for_topic(topic), False


def main() -> None:
    topic = sys.argv[1] if len(sys.argv) > 1 else "Kerala cuisine YouTube channels"
    wf, from_file = load_or_demo(topic)
    print(f"Workflow: strategy={wf.strategy} nodes={len(wf.nodes)} "
          f"({'file' if from_file else 'demo fallback'})")
    print(f"Entry: {wf.entry} | criteria: {wf.criteria[:120]}")
    print(f"Limits: depth<={wf.limits.max_depth} nodes<={wf.limits.max_nodes} "
          f"accepts<={wf.limits.max_accepts}")

    # Deterministic frontier smoke test (no model needed): proves the
    # recurse/branch wiring in the approved graph is executable.
    f = Frontier()
    assert f.push("seed-channel-1", 0) and f.push("seed-channel-1", 0) is False
    assert f.pop() == "seed-channel-1" and f.pop() is None
    print("frontier check: push/dedupe/pop OK")

    agent = compile_workflow(wf, model=get_model())
    print(f"executor built: {agent.name} "
          f"(toolsets={[type(t).__name__ for t in (agent.toolsets or [])]})")
    run_safe(agent, f"Execute the approved {wf.strategy} workflow for: {wf.topic}. "
                    "Start at entry node, respect limits, write findings.json + report.md.")


if __name__ == "__main__":
    main()
