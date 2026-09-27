"""06 — Harness: Shell capability (safe command execution).

Shell gives run_command/start_command/check_command/stop_command.
Safety comes from:
  allowed_commands=[...]  allowlist (empty = ask? here we set explicit list)
  denied_commands           blocklist (rm etc. denied by default)
  default_timeout           don't hang forever
  max_output_chars          don't blow the context window

Try: uv run python 06_harness_shell.py
"""
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai_harness.shell import Shell

from common import get_model, run_safe, tool_names

WORKSPACE = Path(__file__).parent / "workspace"

agent = Agent(
    get_model(),
    instructions="You can run safe read-only shell commands to inspect the workspace.",
    capabilities=[
        Shell(
            cwd=str(WORKSPACE),
            allowed_commands=["ls", "cat", "echo", "pwd", "python3", "pytest"],
            default_timeout=15.0,
            max_output_chars=10_000,
        )
    ],
)


def main() -> None:
    run_safe(agent, "What files are in the workspace? (use ls)")
    print("\nLesson: autonomous != unrestricted. Allowlist the commands")
    print("your agent actually needs; Coder() removes the allowlist on purpose.")


if __name__ == "__main__":
    main()
