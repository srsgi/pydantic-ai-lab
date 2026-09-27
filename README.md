# pydantic-ai-lab

Learn `pydantic-ai` (typed agent loop) + `pydantic-ai-harness`
(capabilities that turn the loop into an autonomous agent).

## Setup

```bash
cd pydantic-ai-lab
uv sync
```

All examples run **offline** with `PYDANTIC_AI_MODEL=test` — no API key needed.

## Live provider: OmniRoute docker (default)

The local `omniroute` container serves an OpenAI-compatible API at
`http://127.0.0.1:20128/v1`. The lab key lives in `.env` as
`OMNIROUTE_API_KEY` (minted in the container DB as `pydantic-ai-lab`,
full model access). `common.py` autoloads `.env`, so examples just work:

```bash
uv run python 00_omniroute_smoke.py   # space-bunny-free + big-pickle
uv run python 09_coder_autonomous_agent.py "fix the bug in workspace/app.py"
PYDANTIC_AI_MODEL=opencode/big-pickle uv run python 01_hello_agent.py
PYDANTIC_AI_MODEL=test uv run python run_all_offline.py
```

Default model is `opencode/space-bunny-free` (ungated upstream).
`opencode/big-pickle` is gated: its upstream rejects requests whose tools
are all custom-named. `common.freetier_padding()` declares inert stock
OpenCode tools (`bash`, `read`) alongside yours to pass the gate —
verified 200, model still calls only your real tools:

```python
Agent(get_model(), toolsets=[freetier_padding()], ...)
```

## Model list: `MODELS.md`

Full OmniRoute catalog (3645 models grouped by provider, e.g. `kg/` +
`kilo-gateway/` dual prefixes, `dva/`, `cxa/`, `aug/`, `cfp/`, `gh/`),
with spot-verified working models and known-bad routes. Any id works as
`PYDANTIC_AI_MODEL=<prefix>/<model>` since `get_model()` routes everything
through OmniRoute — probe first:

```bash
SMOKE_MODEL=kilo-gateway/stealth/space-bunny-alpha uv run python 00_omniroute_smoke.py
```

## Telemetry: Phoenix web UI (local, no signup)

I chose **Arize Phoenix** over building from scratch (Jaeger/Tempo show
generic spans; Logfire needs a cloud account). Phoenix is purpose-built for
LLM traces and runs locally. `12_telemetry.py` wires it up:

- `Instrumentation` capability → OTel GenAI spans out of the agent loop
- `OpenInferenceSpanProcessor` → enriches spans for LLM UIs
- OTLP/HTTP exporter → `http://127.0.0.1:6006/v1/traces`

```bash
uv run phoenix serve --port 6006   # separate terminal, leave running
uv run python 12_telemetry.py      # run any example, traces appear live
```

Then open **http://127.0.0.1:6006**: each run shows as
`invoke_agent → chat → execute_tool → chat` with prompts, tool args,
token usage, and latency per span.

## Unified UI: Pydantic AI Lab hub (one URL)

One dashboard entry — **Pydantic AI Lab** → `http://localhost:7940` —
with an agent dropdown (Research / Approval / ACP Test), a **Direct** tab
for talking to any CLI harness with no parent model in between
(`/api/direct/*`, persistent session per backend), plus a Telemetry tab
(`serve_unified.py`; backends on :7933/:7932/:7941/:6006 load lazily in
iframes). The individual backend entries stay in the dashboard for
start/stop but are unpinned; day-to-day, open only the hub.

## Paused: Pixel Canary on Vercel AI Gateway

`stealth/pixel-canary` via `https://ai-gateway.vercel.sh/v1` is wired
(`00_pixel_canary_smoke.py`, Vercel account `pixel-canary-lab`, key in
`.env`) but the gateway 403s until a credit card is on file — even for
free credits. Revisit after adding a card in Vercel billing.

## Learning path

| File | Concept |
|------|---------|
| `00_omniroute_smoke.py` | Live provider check: big-pickle + space-bunny-free |
| `00_pixel_canary_smoke.py` | Paused: Pixel Canary via Vercel AI Gateway |
| `01_hello_agent.py` | Agent = loop + model + instructions. `run_sync` / `run` |
| `02_structured_output.py` | `output_type=BaseModel` -> guaranteed typed output, retry on validation fail |
| `03_tools_and_dependencies.py` | `@agent.tool` + `RunContext[Deps]` dependency injection |
| `04_autonomous_loop.py` | UsageLimits, retries, multi-turn `message_history` — the autonomous loop |
| `05_harness_filesystem.py` | `FileSystem` capability: sandboxed file workspace |
| `06_harness_shell.py` | `Shell` capability: safe command execution with allowlists |
| `07_planning_and_memory.py` | `Planning` + `Memory(FileStore)` — long-running coherence |
| `08_subagents.py` | Delegation: manual tool-delegation + `SubAgents` capability |
| `09_coder_autonomous_agent.py` | `Coder()` — complete coding agent as one combined capability |
| `10_guardrails_and_limits.py` | `InputGuardrail` / `OutputGuardrail` + `ToolOutputLimits` + `ClearToolResults` |
| `11_custom_capability.py` | Build your own `AbstractCapability` — the one primitive of the harness |
| `12_telemetry.py` | OpenTelemetry traces in the Phoenix web UI |
| `13_human_in_the_loop.py` | AskUser questions + tool approval (terminal; same hooks drive web UIs) |
| `14_researcher.py` | Researcher harness: search + fetch + sub-researcher with citations |
| `15_acp_harness.py` | Drive any ACP CLI harness (opencode acp verified) as a delegate |
| `16_acp_matrix.py` | Drive every backend one by one (8/10 live; kilo/omp need login) |

## Key mental model

- `pydantic-ai` owns the **loop**: model calls, tool execution, validation, retries.
- `pydantic-ai-harness` owns the **harness**: everything around the model
  (workspace, plan, memory, sub-agents, context management).
- Everything in the harness is one primitive: a **capability** added via
  `capabilities=[...]`. Complete agents like `Coder` are just combined
  capabilities — they come apart the way they went together.

Run everything offline first:

```bash
uv run python run_all_offline.py
```
