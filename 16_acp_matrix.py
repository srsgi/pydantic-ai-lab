"""16 — ACP backend matrix: drive every CLI harness one by one.

Runs the same tiny task on each backend in BACKENDS (plus direct cmd),
with tracing on so every turn lands in Phoenix as acp.delegate spans.
Open http://127.0.0.1:6006 after the run and filter by span name.

Try:
    uv run python 16_acp_matrix.py
    BACKENDS=opencode,cmd-acp uv run python 16_acp_matrix.py  # subset
"""
import asyncio
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from openinference.instrumentation.pydantic_ai import OpenInferenceSpanProcessor

from acp_harness import BACKENDS, _delegate_acp, _delegate_cmd, close_acp_pool
from common import get_model  # noqa: F401  (model documented; drivers call CLIs direct)

TASK = "Reply with exactly: matrix online"


async def one(name, spec):
    try:
        if spec["kind"] == "cmd":
            text = await asyncio.wait_for(
                _delegate_cmd("/tmp", 180.0, [], spec["max_concurrency"], TASK), 200)
        else:
            text = await asyncio.wait_for(
                _delegate_acp(spec["command"], "/tmp", spec["permission"],
                              spec["max_concurrency"], 180, TASK), 200)
        ok = "matrix online" in text.replace("\n", " ")
        print(f"[{name}] {'OK' if ok else 'UNEXPECTED'}: {text[:80]!r}", flush=True)
        return ok
    except Exception as e:  # noqa: BLE001 - matrix records, doesn't stop
        print(f"[{name}] FAIL {type(e).__name__}: {str(e)[:120]}", flush=True)
        return False


async def main():
    p = TracerProvider()
    p.add_span_processor(OpenInferenceSpanProcessor())
    p.add_span_processor(SimpleSpanProcessor(
        OTLPSpanExporter(endpoint="http://127.0.0.1:6006/v1/traces")))
    trace.set_tracer_provider(p)
    only = [b.strip() for b in os.getenv("BACKENDS", "").split(",") if b.strip()]
    names = [n for n in BACKENDS if not only or n in only]
    results = {}
    for name in names:
        results[name] = await one(name, BACKENDS[name])
    await close_acp_pool()
    print(f"\n{sum(results.values())}/{len(results)} backends OK")


asyncio.run(main())
