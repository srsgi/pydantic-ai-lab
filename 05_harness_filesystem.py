"""05 — Harness: FileSystem capability (the agent's workspace).

Core pydantic-ai has no file access. The harness adds it as a capability:
  capabilities=[FileSystem(root_dir="workspace")]

This mounts tools: read_file, write_file, edit_file, list_directory,
search_files, find_files, create_directory, file_info — all sandboxed
under root_dir (path-traversal + symlink safe).

Try: uv run python 05_harness_filesystem.py
With a real model, ask it to create/fix files and watch it work.
"""
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai_harness.filesystem import FileSystem

from common import get_model, run_safe, tool_names

WORKSPACE = Path(__file__).parent / "workspace"
WORKSPACE.mkdir(exist_ok=True)

agent = Agent(
    get_model(),
    instructions="You work inside the workspace directory. Explain what you would do.",
    capabilities=[
        FileSystem(
            root_dir=str(WORKSPACE),
            # read_only=False lets it write; set True for a read-only explorer
            # tools=(...) can subset, e.g. tools=["read_file", "list_directory"]
        )
    ],
)


def main() -> None:
    # Seed a file so there is something to find even offline.
    (WORKSPACE / "notes.txt").write_text("TODO: fix off-by-one in app.py\n")
    run_safe(agent, "List the workspace files and read notes.txt.")
    print("\nWith PYDANTIC_AI_MODEL=openai:gpt-4o the agent would actually")
    print("call list_directory/read_file instead of answering from text.")


if __name__ == "__main__":
    main()
