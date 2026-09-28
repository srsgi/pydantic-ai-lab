"""Shared fixed generic research toolkit + workflow DSL.

One fixed set of 8 generic tools for ALL research domains. The planner
(17_) only rearranges + parametrizes them; the compiler (18_) builds the
executor Agent from the approved workflow at runtime. No per-domain tools.

Tools (all generic):
  query_expand, broad_search, structured_search, deep_fetch,
  sample, relevance_classify, frontier_expand, synthesize

Control flow (branch/fanout/recurse/human_gate/join) lives in the
workflow graph nodes, not in tools.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Fixed toolkit registry: planner may reference ONLY these 8 names.
# ---------------------------------------------------------------------------

RESEARCH_TOOLKIT: dict[str, str] = {
    "query_expand": (
        "Generate search queries from a topic. Args: topic, dimensions "
        "(e.g. languages, synonyms, subtopics, source_type). Use first, always."
    ),
    "broad_search": (
        "Unstructured web search (rotating DDG -> SearXNG -> Exa/Brave). "
        "Args: query, max_results. Use for landscape + fallback."
    ),
    "structured_search": (
        "Generic source API search. Args: source (youtube|arxiv|pubmed|generic), "
        "query, source_config JSON. Same code path for all sources; planner "
        "supplies config. Falls back to broad_search with site: operator."
    ),
    "deep_fetch": (
        "Fetch one ref (URL, channelId, paper id) into normalized "
        "Document{title, text, meta}. Truncated. Args: ref."
    ),
    "sample": (
        "Sample k items of a collection (recent videos, papers, trials). "
        "Args: entity_ref, k, method (recent|top|citations). Avoids full crawl."
    ),
    "relevance_classify": (
        "Score one candidate bundle vs planner criteria. "
        "Args: bundle_text, criteria. Returns accept|reject|uncertain + reason. "
        "This output drives branch nodes."
    ),
    "frontier_expand": (
        "Snowball: neighbors of an accepted entity. Args: entity_ref, "
        "relation_hints (e.g. featured, related, citations, cited-by). "
        "Pushes unseen refs to frontier. Drives recurse nodes."
    ),
    "synthesize": (
        "Write findings.json + report.md from accepted set. Args: schema_hint, "
        "mode (draft|verify|final). mode=verify re-fetches before writing."
    ),
}

TOOL_NAMES = tuple(RESEARCH_TOOLKIT)

# ---------------------------------------------------------------------------
# Workflow DSL: graph with branching + recursion (not a linear list).
# ---------------------------------------------------------------------------

NodeKind = Literal["task", "branch", "fanout", "recurse", "human_gate", "join"]


class Limits(BaseModel):
    max_depth: int = 3
    max_nodes: int = 200
    max_accepts: int = 50


class ResearchNode(BaseModel):
    id: str
    kind: NodeKind = "task"
    tool: str | None = Field(default=None, description="One of RESEARCH_TOOLKIT, for task/fanout nodes")
    task: str = ""
    # Branching: relevance_classify label -> next node id.
    on_accept: str | None = None
    on_reject: str | None = None
    on_uncertain: str | None = None
    # Fanout: run `over` then continue at `join_to`.
    over: str | None = None
    join_to: str | None = None
    # Recursion: after this node, jump back to `recurse_to` while frontier grows.
    recurse_to: str | None = None
    # Static params for the tool call (source_config, criteria, k, ...).
    params: dict = Field(default_factory=dict)


class ResearchWorkflow(BaseModel):
    topic: str
    strategy: str = ""
    complexity: Literal["quick", "standard", "deep"] = "standard"
    complexity_why: str = ""
    source_config: dict = Field(default_factory=dict)
    criteria: str = ""
    schema_hint: str = ""
    limits: Limits = Field(default_factory=Limits)
    nodes: list[ResearchNode] = Field(default_factory=list)
    entry: str = "expand"

    def by_id(self, nid: str) -> ResearchNode:
        for n in self.nodes:
            if n.id == nid:
                return n
        raise KeyError(f"unknown node {nid!r}")


# ---------------------------------------------------------------------------
# Frontier state (visited/queued/accepted). Persisted as JSON so recursion
# survives restarts; Memory(FileStore) in the live agent mirrors it.
# ---------------------------------------------------------------------------

@dataclass
class Frontier:
    queued: list[str] = field(default_factory=list)
    visited: set[str] = field(default_factory=set)
    accepted: list[dict] = field(default_factory=list)
    depth: dict[str, int] = field(default_factory=dict)

    def push(self, ref: str, depth: int = 0) -> bool:
        if ref in self.visited or ref in self.queued:
            return False
        self.queued.append(ref)
        self.depth[ref] = depth
        return True

    def pop(self) -> str | None:
        while self.queued:
            ref = self.queued.pop(0)
            if ref not in self.visited:
                self.visited.add(ref)
                return ref
        return None

    def to_file(self, path: Path) -> None:
        path.write_text(json.dumps({
            "queued": self.queued, "visited": sorted(self.visited),
            "accepted": self.accepted, "depth": self.depth,
        }, indent=2))

    @staticmethod
    def from_file(path: Path) -> Frontier:
        d = json.loads(path.read_text())
        return Frontier(d.get("queued", []), set(d.get("visited", [])),
                        d.get("accepted", []), d.get("depth", {}))


# ---------------------------------------------------------------------------
# The 8 generic tool implementations (real where cheap, stubbed offline).
# ---------------------------------------------------------------------------

def query_expand(topic: str, dimensions: str = "synonyms, subtopics, languages") -> str:
    """Generate search queries from a topic along variation dimensions."""
    dims = [d.strip() for d in dimensions.split(",") if d.strip()]
    queries = [f"{topic} {d}" for d in dims[:6]] or [topic]
    queries += [f"{topic} overview", f"{topic} site:youtube.com" if "channel" in topic.lower() or "cuisine" in topic.lower() else f"{topic} review"]
    seen = list(dict.fromkeys(queries))[:10]
    return json.dumps({"topic": topic, "dimensions": dims, "queries": seen}, indent=2)


def broad_search(query: str, max_results: int = 5) -> str:
    """Unstructured web search via the rotating engines in common.py."""
    try:
        from common import rotating_web_search
        return rotating_web_search(query, max_results=max_results)
    except Exception as e:  # noqa: BLE001 - offline / throttled -> stub
        return f"(broad_search stub: engines unavailable [{type(e).__name__}]. query={query!r})"


def structured_search(source: str = "generic", query: str = "", source_config: str = "{}") -> str:
    """Generic source API search. YOU MUST CALL THIS TOOL for source evidence.

    NEVER write source facts, figures, prices, quotas, or URLs from memory:
    if you have not called this tool (or broad_search/deep_fetch) and quoted
    its result, you do not know the answer — say so. source_config holds
    LOCATORS only ({"source": ..., "site": "<bare-domain>"}), never answers
    or deep document paths. Live when the source key is configured
    (e.g. YOUTUBE_API_KEY, or an arxiv/pubmed HTTP endpoint); otherwise falls
    back to broad_search with a site: qualifier so the workflow runs keyless.
    """
    cfg: dict = {}
    try:
        cfg = json.loads(source_config or "{}")
    except Exception:  # noqa: BLE001 - bad config is non-fatal
        cfg = {}
    site = str(cfg.get("site", "") or "").strip()
    if source == "youtube" and os.getenv("YOUTUBE_API_KEY", ""):
        return f"(youtube API: query={query!r} — wire search.list here; key present)"
    if source in ("arxiv", "pubmed") and query:
        try:
            import httpx
            if source == "arxiv":
                r = httpx.get("https://export.arxiv.org/api/query",
                              params={"search_query": f"all:{query}", "max_results": 5},
                              timeout=25)
                r.raise_for_status()
                return r.text[:4000]
        except Exception as e:  # noqa: BLE001 - fall through to web search
            site = site or ("arxiv.org" if source == "arxiv" else "pubmed.ncbi.nlm.nih.gov")
        q = f"{query} site:{site}" if site else query
        return broad_search(q)
    # Keyless default: qualify and reuse the rotating engines.
    q = f"{query} site:{site}" if site else query
    return broad_search(q)


def deep_fetch(ref: str) -> str:
    """Fetch one ref into a truncated normalized document."""
    try:
        import httpx
        if ref.startswith(("http://", "https://")):
            r = httpx.get(ref, timeout=25, follow_redirects=True,
                          headers={"User-Agent": "pydantic-ai-lab/1.0"})
            r.raise_for_status()
            text = r.text[:4000].replace("\n", " ")
            return json.dumps({"ref": ref, "title": ref, "text": text,
                               "meta": {"status": r.status_code}}, indent=2)
    except Exception:  # noqa: BLE001 - fall through to stub
        pass
    return json.dumps({"ref": ref, "title": ref,
                       "text": f"(deep_fetch stub for {ref!r})",
                       "meta": {"stub": True}}, indent=2)


def sample(entity_ref: str, k: int = 10, method: str = "recent") -> str:
    """Sample k items of a collection without a full crawl."""
    return json.dumps({"entity": entity_ref, "method": method, "k": k,
                       "items": [f"{entity_ref}#{i + 1} ({method})" for i in range(min(k, 10))]},
                      indent=2)


def relevance_classify(bundle_text: str, criteria: str) -> str:
    """Heuristic scorer driving branch nodes (LLM re-judges live).

    Offline-safe keyword overlap; the live executor agent treats this as a
    first pass and applies its own judgment for the final label.
    """
    crit_words = {w.lower() for w in criteria.split() if len(w) > 3}
    bundle_words = set(bundle_text.lower().split())
    overlap = len(crit_words & bundle_words) if crit_words else 0
    if overlap >= 3:
        label = "accept"
    elif overlap == 0:
        label = "reject"
    else:
        label = "uncertain"
    return json.dumps({"label": label, "score": overlap, "criteria": criteria,
                       "reason": f"keyword overlap={overlap}"}, indent=2)


def frontier_expand(entity_ref: str, relation_hints: str = "related, featured, citations") -> str:
    """List neighbor refs of an accepted entity (snowball frontier)."""
    hints = [h.strip() for h in relation_hints.split(",") if h.strip()]
    neighbors = [f"{entity_ref}~{h[:8]}-{i + 1}" for h in hints[:3] for i in range(2)]
    return json.dumps({"entity": entity_ref, "hints": hints, "neighbors": neighbors}, indent=2)


def synthesize(schema_hint: str = "", mode: str = "draft") -> str:
    """Write findings (draft/verify/final). Real write happens via FileSystem."""
    return json.dumps({"mode": mode, "schema_hint": schema_hint[:200],
                       "note": "executor writes findings.json + report.md via FileSystem"}, indent=2)


# The planner agent gets query_expand + submit_workflow only (no I/O tools,
# so it cannot self-start execution). The executor agent gets the full set
# below and no planning tools (so it cannot replan). Separation — not gating
# — keeps small models on-protocol.


def research_toolset():
    """FunctionToolset exposing exactly the 8 fixed generic tools."""
    from pydantic_ai.toolsets import FunctionToolset

    return FunctionToolset([
        query_expand, broad_search, structured_search, deep_fetch,
        sample, relevance_classify, frontier_expand, synthesize,
    ])


# ---------------------------------------------------------------------------
# Demo workflow builder: deterministic fallback so 17_/18_ work offline with
# the test model AND give the live planner a shape reference in its prompt.
# ---------------------------------------------------------------------------

def demo_workflow_for_topic(topic: str) -> ResearchWorkflow:
    low = topic.lower()
    if "cuisine" in low or "recipe" in low or "youtube" in low or "channel" in low:
        strategy = "snowball-channel-discovery"
        source_config = {"source": "youtube", "site": "youtube.com"}
        criteria = f"dedicated channel for {topic}: >50% items about the cuisine"
        schema_hint = "ChannelTable{channel, url, subs, cadence, evidence_links}"
    elif any(w in low for w in ("cancer", "trial", "disease", "medical", "drug", "covid")):
        strategy = "systematic-evidence-review"
        source_config = {"source": "pubmed", "site": "pubmed.ncbi.nlm.nih.gov"}
        criteria = f"primary evidence for {topic}: RCTs / guidelines preferred"
        schema_hint = "EvidenceTable{claim, source, quality, link}"
    else:
        strategy = "literature-snowball"
        source_config = {"source": "arxiv", "site": "arxiv.org"}
        criteria = f"directly about {topic}, primary sources preferred"
        schema_hint = "FindingsTable{claim, source, link}"
    return ResearchWorkflow(
        topic=topic, strategy=strategy, source_config=source_config,
        criteria=criteria, schema_hint=schema_hint,
        limits=Limits(max_depth=2, max_nodes=60, max_accepts=30),
        entry="expand",
        nodes=[
            ResearchNode(id="expand", kind="task", tool="query_expand",
                         task=f"Generate queries for {topic!r} across languages/synonyms/subtopics"),
            ResearchNode(id="seed", kind="fanout", tool="structured_search",
                         task="Run each query against the configured source", over="expand", join_to="triage",
                         params={"source_config": source_config}),
            ResearchNode(id="triage", kind="branch", task="Classify each candidate vs criteria",
                         on_accept="expand_more", on_reject="drop", on_uncertain="deep_dive"),
            ResearchNode(id="deep_dive", kind="task", tool="deep_fetch",
                         task="Fetch ambiguous candidate in full, then re-classify; human_gate if still uncertain"),
            ResearchNode(id="expand_more", kind="recurse", tool="frontier_expand",
                         task="Snowball neighbors of accepted entities", recurse_to="triage"),
            ResearchNode(id="drop", kind="task", task="Terminal: pruned candidate"),
            ResearchNode(id="report", kind="task", tool="synthesize",
                         task="Verify citations then write findings.json + report.md", params={"mode": "final"}),
        ],
    )


# ---------------------------------------------------------------------------
# Runtime compiler: approved workflow -> live executor Agent (18_ uses this).
# ---------------------------------------------------------------------------

def compile_workflow(wf: ResearchWorkflow, model=None, workspace: str = "workspace/research"):
    """Build the executor Agent for an approved workflow at runtime."""
    from pydantic_ai import Agent
    from pydantic_ai_harness.compaction import ClearToolResults
    from pydantic_ai_harness.filesystem import FileSystem
    from pydantic_ai_harness.memory import FileStore, Memory
    from pydantic_ai_harness.planning import Planning
    from pydantic_ai_harness.tool_output_limits import ToolOutputLimits

    from common import DuckDuckGoPacing, get_model

    slug = "".join(c.lower() if c.isalnum() else "-" for c in wf.topic)[:40].strip("-")
    root = str(Path(workspace) / (slug or "general"))
    Path(root).mkdir(parents=True, exist_ok=True)
    memdir = Path(".agent-memory") / (slug or "general")
    memdir.mkdir(parents=True, exist_ok=True)

    toolkit_help = "\n".join(f"- {k}: {v}" for k, v in RESEARCH_TOOLKIT.items())
    graph = "\n".join(
        f"- {n.id} [{n.kind}] tool={n.tool} task={n.task} "
        f"accept->{n.on_accept} reject->{n.on_reject} uncertain->{n.on_uncertain} "
        f"recurse->{n.recurse_to}".rstrip()
        for n in wf.nodes
    )
    return Agent(
        model or get_model(),
        name="research-executor",
        instructions=(
            f"Execute this APPROVED research workflow, no deviation.\n"
            f"Topic: {wf.topic}\nStrategy: {wf.strategy}\n"
            f"Criteria: {wf.criteria}\nSchema: {wf.schema_hint}\n"
            f"Limits: depth<={wf.limits.max_depth}, nodes<={wf.limits.max_nodes}, "
            f"accepts<={wf.limits.max_accepts}.\n"
            f"Entry node: {wf.entry}. Graph:\n{graph}\n\n"
            f"Fixed toolkit (only these 8 tools exist):\n{toolkit_help}\n\n"
            "Rules: keep a frontier (queued/visited/accepted) in memory; "
            "branch on relevance_classify labels; recurse via frontier_expand "
            "until limits/frontier-empty/no-new-accepts; verify before "
            "synthesize(mode=final); write findings.json + report.md."
        ),
        capabilities=[
            Planning(),
            Memory(FileStore(str(memdir)), max_tokens=2000, max_lines=200),
            FileSystem(root_dir=root),
            ToolOutputLimits(),
            ClearToolResults(max_tokens=20000, keep_pairs=3),
            DuckDuckGoPacing(),
        ],
        toolsets=[research_toolset()],
    )


# ---------------------------------------------------------------------------
# Planner -> executor handoff (file protocol in workspace/research/).
# The planner writes workflow.json + approved.json; the executor refuses to
# run unless both exist with matching topics. No shared stage machine, no
# approval tools, no DeferredToolRequests — the user's "approved, run it"
# reply in the planner chat IS the approval, recorded on disk.
# ---------------------------------------------------------------------------

import re as _re

WORKFLOW_FILE = "workflow.json"
APPROVAL_FILE = "approved.json"

_MONEY = _re.compile(r"\$\s?\d")
_QUANTITY = _re.compile(
    r"\d+\s*(hours?|hrs?|days?|months?|years?|gb|tb|credits?|users?)\b", _re.IGNORECASE)
_DEEP_URL = _re.compile(r"https?://[^/,\s'\"]+/[^,\s'\"]+")


def workflow_path(root: str | Path) -> Path:
    return Path(root) / WORKFLOW_FILE


def approval_path(root: str | Path) -> Path:
    return Path(root) / APPROVAL_FILE


def record_approval(root: str | Path, topic: str) -> Path:
    """Record the user's chat approval of the validated plan on disk."""
    import time as _time

    path = approval_path(root)
    path.write_text(json.dumps({"approved": True, "topic": topic,
                                "at": _time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2))
    return path


def load_handoff(root: str | Path) -> tuple[ResearchWorkflow | None, str]:
    """Load (workflow, problem) for the executor: problem is '' when the
    handoff is complete (validated plan + matching approval on disk)."""
    wp, ap = workflow_path(root), approval_path(root)
    if not wp.exists():
        return None, ("no workflow.json — complete Research Plan first "
                      "(questions, submit, present, approve)")
    try:
        wf = ResearchWorkflow.model_validate(json.loads(wp.read_text()))
    except Exception as e:  # noqa: BLE001 - executor reports, doesn't crash
        return None, f"workflow.json is invalid: {str(e)[:200]}"
    if not ap.exists():
        return None, (f"plan for {wf.topic!r} is not approved yet — approve it "
                      "in Research Plan first (mark_approved)")
    try:
        apv = json.loads(ap.read_text())
    except Exception:  # noqa: BLE001
        apv = {}
    if not apv.get("approved") or apv.get("topic") != wf.topic:
        return None, (f"approval does not match plan topic {wf.topic!r} — "
                      "re-approve the current plan in Research Plan")
    return wf, ""


@dataclass
class LedgerEntry:
    ref: str
    depth: int = 0
    status: str = "queued"  # queued | accepted | rejected | uncertain
    reason: str = ""
    evidence: str = ""


@dataclass
class Ledger:
    """Candidate ledger for interpreted (stepwise) execution.

    Leg tools read/write ledger.json in the workflow root; each entry keeps
    its verdict + reason + evidence links, so legs are idempotent (triage
    skips non-queued, expand skips expanded) and resumable after budget stops.
    """

    entries: dict[str, LedgerEntry] = field(default_factory=dict)
    expanded: list[str] = field(default_factory=list)

    def add(self, ref: str, depth: int = 0) -> bool:
        if ref in self.entries:
            return False
        self.entries[ref] = LedgerEntry(ref=ref, depth=depth)
        return True

    def queued(self, limit: int = 25) -> list[LedgerEntry]:
        return [e for e in self.entries.values() if e.status == "queued"][:limit]

    def counts(self) -> dict[str, int]:
        d: dict[str, int] = {}
        for e in self.entries.values():
            d[e.status] = d.get(e.status, 0) + 1
        return d

    def to_file(self, path: Path) -> None:
        path.write_text(json.dumps({
            "entries": {r: {"depth": e.depth, "status": e.status,
                            "reason": e.reason, "evidence": e.evidence}
                        for r, e in self.entries.items()},
            "expanded": self.expanded,
        }, indent=2))

    @staticmethod
    def from_file(path: Path) -> Ledger:
        d = json.loads(path.read_text())
        lg = Ledger(expanded=d.get("expanded", []))
        for r, e in d.get("entries", {}).items():
            lg.entries[r] = LedgerEntry(ref=r, depth=e.get("depth", 0),
                                        status=e.get("status", "queued"),
                                        reason=e.get("reason", ""),
                                        evidence=e.get("evidence", ""))
        return lg


LEDGER_FILE = "ledger.json"
CURSOR_FILE = "cursor.json"


def ledger_path(root: str | Path) -> Path:
    return Path(root) / LEDGER_FILE


def cursor_path(root: str | Path) -> Path:
    return Path(root) / CURSOR_FILE


def read_cursor(root: str | Path) -> dict:
    try:
        return json.loads(cursor_path(root).read_text())
    except Exception:
        return {"rounds": 0, "legs": []}


def write_cursor(root: str | Path, cursor: dict) -> None:
    cursor_path(root).write_text(json.dumps(cursor, indent=2))


def validate_workflow(plan: dict) -> ResearchWorkflow:
    """Validate a submitted plan dict; raise ValueError listing problems.

    Enforces: known tools only, resolvable edges, branch+recurse structure
    for standard/deep tasks (quick tasks skip those), and NO memorized facts
    (money amounts, >=2 time/data quantities, deep doc URLs in configs —
    facts must come from tool results, not the model's memory).
    """
    errors: list[str] = []
    try:
        wf = ResearchWorkflow.model_validate(plan)
    except Exception as e:  # noqa: BLE001 - report shape errors plainly
        raise ValueError(f"plan shape invalid: {str(e)[:500]}") from e

    ids = {n.id for n in wf.nodes}
    if wf.entry not in ids:
        errors.append(f"entry {wf.entry!r} is not a node id {sorted(ids)}")
    for n in wf.nodes:
        if n.tool is not None and n.tool not in RESEARCH_TOOLKIT:
            errors.append(f"node {n.id!r}: unknown tool {n.tool!r} "
                          f"(allowed: {sorted(TOOL_NAMES)})")
        for edge in (n.on_accept, n.on_reject, n.on_uncertain, n.join_to, n.recurse_to):
            if edge is not None and edge not in ids:
                errors.append(f"node {n.id!r}: edge -> {edge!r} resolves to nothing")
    branches = [n for n in wf.nodes
                if n.kind == "branch" and n.on_accept and n.on_reject and n.on_uncertain]
    recurses = [n for n in wf.nodes
                if n.kind == "recurse" and n.recurse_to and n.recurse_to in ids]
    if wf.complexity == "quick":
        # Simple 1-2 question tasks: no branching/recursion required.
        if len(wf.nodes) < 2:
            errors.append("quick plan needs at least 2 nodes (search + synthesize)")
    else:
        if not branches:
            errors.append("no branch node with on_accept+on_reject+on_uncertain — "
                          "classify each candidate and wire all three outcomes "
                          "(or set complexity=quick with a reason, for single-question tasks)")
        if not recurses:
            errors.append("no recurse node with a resolvable recurse_to — wire "
                          "frontier_expand back to triage with limits "
                          "(or set complexity=quick with a reason)")
    if len(wf.nodes) < 4 and wf.complexity != "quick":
        errors.append("plan too small: need at least expand/seed/triage/recurse/report shape")
    blob = json.dumps({"t": [n.task for n in wf.nodes], "c": wf.criteria,
                       "p": [n.params for n in wf.nodes]})
    if _MONEY.search(blob):
        errors.append("plan contains money amounts ($...) from memory — remove all "
                      "facts/figures; they must come from tool results")
    if len(_QUANTITY.findall(blob)) > 1:
        errors.append("plan contains 2+ time/data quantities (30 days, 750 hours...) "
                      "from memory — keep at most one user-given constraint, "
                      "discover the rest via tools")
    for v in wf.source_config.values():
        if isinstance(v, str) and _DEEP_URL.search(v):
            errors.append(f"source_config has a deep doc URL {v!r} from memory — "
                          "use bare domains (site: <domain>) and fetch exact URLs via tools")
            break
    if errors:
        raise ValueError("plan rejected:\n- " + "\n- ".join(errors))
    return wf



PRESENT_RULES = (
    "Present the validated plan as short markdown tables/bullets, one row per "
    "node (id, tool, what it does, next on accept/reject/uncertain), lines "
    "<=100 chars. NEVER use fenced code blocks or ASCII-art trees for the "
    "plan (they get cut off). Then ask: approve, or what to change — and WAIT."
)
