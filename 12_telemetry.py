"""12 — Telemetry: OpenTelemetry traces in the Phoenix web UI.

Stack (all local, no signup):
  pydantic-ai `Instrumentation` capability  -> emits OTel GenAI spans
  OpenInferenceSpanProcessor                -> enriches spans for LLM UIs
  OTLPSpanExporter (HTTP)                   -> ships to Phoenix
  Arize Phoenix (http://127.0.0.1:6006)     -> trace visualization web UI

Start Phoenix once (separate terminal, leave running):
    uv run phoenix serve --port 6006

Then:
    uv run python 12_telemetry.py
    PYDANTIC_AI_MODEL=test uv run python 12_telemetry.py   # offline spans too

Open http://127.0.0.1:6006 and watch the agent run, tool calls, token usage.
"""
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from openinference.instrumentation.pydantic_ai import OpenInferenceSpanProcessor

from pydantic_ai import Agent
from pydantic_ai.capabilities import Instrumentation

from common import get_model, tool_names

PHOENIX_ENDPOINT = os.getenv("PHOENIX_ENDPOINT", "http://127.0.0.1:6006/v1/traces")


def setup_tracing() -> None:
    provider = TracerProvider()
    provider.add_span_processor(OpenInferenceSpanProcessor())
    provider.add_span_processor(
        SimpleSpanProcessor(OTLPSpanExporter(endpoint=PHOENIX_ENDPOINT))
    )
    trace.set_tracer_provider(provider)


agent = Agent(
    get_model(),
    instructions="Be concise.",
    capabilities=[Instrumentation()],
)


@agent.tool_plain
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


def main() -> None:
    setup_tracing()
    result = agent.run_sync("What is 21 + 21? Use the add tool.")
    print("output:", result.output)
    print("tools:", tool_names(result))
    print(f"\nOpen {PHOENIX_ENDPOINT.replace('/v1/traces', '')} to see the trace.")


if __name__ == "__main__":
    main()
