"""15 — ACP harness driver: control ANY ACP CLI harness as a delegate.

AcpHarness (acp_harness.py) is a capability built on the official
`agent-client-protocol` SDK (client side). Any stdio ACP server works (verified initialize against all of these;
full prompt turn verified on opencode; kilo needs `kilo login` first):

    AcpHarness(("opencode", "acp"))                  # full turn verified
    AcpHarness(("kilo", "acp"))                      # handshake OK, needs login
    AcpHarness(("kiro", "acp"))                      # handshake OK
    AcpHarness(("hermes", "acp"))                    # handshake OK
    AcpHarness(("omp", "acp"))                       # handshake OK
    AcpHarness(("cline", "--acp"))                   # handshake OK
    AcpHarness(("copilot", "--acp"))                 # handshake OK
    AcpHarness(("gemini", "--experimental-acp"))     # same code path
    AcpHarness(("npx", "@zed-industries/codex-acp")) # same code path
    AcpHarness(("agy-acp",))  # sysCat64 adapter; full turn verified
    # AcpHarness(("cmd-acp",))  # soycanopa bridge; handshake + turn +
    #                              2-session multiplexing verified

    Prefer UnifiedHarness: ONE `delegate(task, backend, model)` tool for all
    10 backends, with per-backend spawn policy built in (native unlimited,
    cmd-acp/cmd capped at 1). `model` applies best-effort via the ACP model
    config option where advertised.

    9th harness, different route — Command Code (`cmd`) has no ACP server
    (and Herdr has no cmd integration; its hooks/mods react to the loop
    rather than driving turns). CmdHarness in the same module drives it via
    `cmd -p --trust --output-format json` (full turn verified). Better:
    soycanopa/cmd-acp (npm i -g cmd-acp) exposes cmd over ACP — handshake,
    prompt turn, and 2-session multiplexing all verified with AcpHarness:

    Not covered: `agy` (project-tracker/backend.acp.bridges.agy) speaks the
    pre-1.0 ACP dialect (protocolVersion "2024-11-05" string vs v1 integer)
    and fails handshake with the standard SDK — needs a legacy shim.

The model gets delegate_to_<name>(task); each call spawns the harness,
runs one turn, returns its text. Permission policy: allow-read (default),
allow-all, deny-all. Local fs reads/writes the model triggers are scoped
to cwd; terminal requests are refused.

Try:
    uv run python 15_acp_harness.py
    PYDANTIC_AI_MODEL=test uv run python 15_acp_harness.py  # skips live spawn
"""
from pydantic_ai import Agent

from acp_harness import AcpHarness
from common import get_model, is_live, tool_names


def main() -> None:
    agent = Agent(
        get_model(),
        instructions="Delegate coding questions to the opencode harness.",
        capabilities=[AcpHarness(("opencode", "acp"), name="opencode",
                                 cwd="/tmp", timeout=180.0)],
    )
    if not is_live():
        print("offline: agent built OK (tool: delegate_to_opencode).")
        print("Set a live model to actually spawn the harness.")
        return
    r = agent.run_sync("Ask the opencode harness to reply with exactly: delegated ok")
    print("output:", r.output)
    print("tools:", tool_names(r))


if __name__ == "__main__":
    main()
