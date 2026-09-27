"""Generic harness-driver capabilities.

AcpHarness: control ANY ACP stdio harness from a agent, built on the
official `agent-client-protocol` SDK (client side) — no per-harness code.

CmdHarness: control Command Code (`cmd`), which has no ACP server.
Driver is `cmd -p --trust --output-format json` (NDJSON events); the final
`run_end` line carries finalText. Herdr has no cmd integration either
(checked kinds + integration list), and cmd hooks/mods react to the loop
rather than driving turns — headless print mode is the external route.
"""
import asyncio
import os
from pathlib import Path

#: Extra dirs searched for harness binaries (dashboard-managed servers run
#: with a minimal PATH that lacks ~/.local/bin).
_BIN_DIRS = [str(Path.home() / ".local" / "bin"),
             str(Path.home() / ".opencode" / "bin"),
             "/usr/local/bin", "/usr/bin", "/bin"]


def _resolve_cmd(cmd):
    """Resolve argv[0] to an absolute path so spawns work under any PATH."""
    import shutil

    if "/" in cmd[0]:
        return cmd
    for d in [os.environ.get("PATH", "")] + _BIN_DIRS:
        for part in d.split(":"):
            cand = Path(part) / cmd[0] if part else None
            if cand and cand.is_file() and os.access(cand, os.X_OK):
                return (str(cand),) + tuple(cmd[1:])
    found = shutil.which(cmd[0], path=":".join(_BIN_DIRS))
    if found:
        return (found,) + tuple(cmd[1:])
    raise FileNotFoundError(
        f"harness binary {cmd[0]!r} not found (searched PATH + {_BIN_DIRS})")

READ_LIKE = {"read", "search", "think", "fetch", "switch_mode", "other"}


def _block_text(block) -> str:
    text = getattr(block, "text", None)
    if isinstance(text, str):
        return text
    content = getattr(block, "content", None)
    if isinstance(content, list):
        return "".join(_block_text(b) for b in content)
    return ""


class _Driver:
    """Minimal ACP Client: collects text, answers permissions, scopes fs."""

    def __init__(self, root: Path, permission: str):
        from acp import Client

        self._root = root
        self._permission = permission
        self.text_parts: list[str] = []
        self.tool_calls: list[str] = []
        # Full turn transcript: every session_update + permission/fs decision,
        # each {"kind": ..., "detail": ...}. Sliced per task; also mirrored
        # to the OTel span so Phoenix shows inner steps like harness steps.
        self.transcript: list[dict] = []
        self._client_cls = Client

    @staticmethod
    def _snap(obj, limit: int = 400) -> str:
        try:
            dump = obj.model_dump_json(exclude_none=True)
        except Exception:
            dump = str(obj)
        return dump[:limit]

    def _pick(self, options) -> str:
        opts = list(options)
        if self._permission == "allow-all":
            return opts[0].option_id
        deny = next((o for o in opts
                     if "deny" in o.option_id.lower() or "reject" in o.option_id.lower()
                     or "cancel" in o.option_id.lower()), None)
        if self._permission == "deny-all":
            return (deny or opts[-1]).option_id
        # allow-read: an explicitly read-like option, else the deny option
        for o in opts:
            if str(getattr(o, "kind", "")).lower() in READ_LIKE:
                return o.option_id
        return (deny or opts[-1]).option_id

    def build(self):
        from acp import Client
        from acp.schema import RequestPermissionResponse, SelectedPermissionOutcome

        driver = self

        class _Client(Client):
            async def session_update(self, session_id, update, **kwargs):
                kind = getattr(update, "session_update", None) or getattr(update, "kind", "")
                driver.transcript.append({"kind": str(kind),
                                          "detail": _Driver._snap(update)})
                if kind in ("agent_message_chunk", "user_message_chunk"):
                    content = getattr(update, "content", None)
                    if isinstance(content, list):
                        for b in content:
                            t = _block_text(b)
                            if t:
                                driver.text_parts.append(t)
                    elif content is not None:
                        t = _block_text(content)
                        if t:
                            driver.text_parts.append(t)
                elif kind == "tool_call":
                    driver.tool_calls.append(str(getattr(update, "title", None) or getattr(update, "kind", "")))
                return None

            async def request_permission(self, session_id, tool_call, options, **kwargs):
                choice = driver._pick(options)
                driver.transcript.append({
                    "kind": "permission",
                    "detail": f"{getattr(tool_call, 'title', tool_call)} -> {choice}"[:300]})
                return RequestPermissionResponse(
                    outcome=SelectedPermissionOutcome(option_id=choice))

            async def read_text_file(self, session_id, path, **kwargs):
                p = (driver._root / path).resolve()
                if driver._root not in p.parents and p != driver._root:
                    raise RuntimeError(f"outside workspace: {path}")
                driver.transcript.append({"kind": "fs_read", "detail": str(path)[:200]})
                return {"content": p.read_text()[:20000]}

            async def write_text_file(self, session_id, path, content, **kwargs):
                p = (driver._root / path).resolve()
                if driver._root not in p.parents and p != driver._root:
                    raise RuntimeError(f"outside workspace: {path}")
                driver.transcript.append({"kind": "fs_write", "detail": str(path)[:200]})
                p.write_text(content)
                return {}

            async def create_terminal(self, *a, **k):
                raise RuntimeError("terminal not supported by this driver")

        return _Client()


from contextlib import AsyncExitStack

_POOL: dict[tuple, dict] = {}
_POOL_LOCKS: dict[tuple, asyncio.Lock] = {}
_POOL_SEMAPHORES: dict[tuple, asyncio.Semaphore] = {}


def _pool_semaphore(cmd, root, permission, max_concurrency):
    if max_concurrency is None:
        return None
    key = (cmd, str(root), permission)
    sem, saved = _POOL_SEMAPHORES.get(key, (None, None))
    if sem is None or saved != max_concurrency:
        sem = asyncio.Semaphore(max_concurrency)
        _POOL_SEMAPHORES[key] = (sem, max_concurrency)
    return sem


async def _pooled_entry(cmd, root, permission):
    """Return the shared pool entry, spawning the backend on first use."""
    import acp
    from acp.stdio import spawn_agent_process

    key = (cmd, str(root), permission)
    lock = _POOL_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        entry = _POOL.get(key)
        proc = entry["proc"] if entry else None
        if entry is not None and (proc is None or proc.returncode is None):
            entry["sessions"] += 1
            return entry
        if entry is not None:  # dead backend: drop it
            try:
                await entry["stack"].aclose()
            except Exception:
                pass
            _POOL.pop(key, None)
        driver = _Driver(root, permission)
        stack = AsyncExitStack()
        conn, proc = await stack.enter_async_context(
            spawn_agent_process(driver.build(), *_resolve_cmd(cmd), cwd=str(root)))
        await conn.initialize(protocol_version=acp.PROTOCOL_VERSION,
                              client_capabilities=None, client_info=None)
        entry = {"conn": conn, "driver": driver, "proc": proc,
                 "stack": stack, "sessions": 1,
                 "last_used": __import__("time").monotonic()}
        _POOL[key] = entry
        return entry


async def _release_entry(cmd, root, permission, idle_ttl=600.0):
    """Decrement sessions; reap the backend if idle past ttl."""
    import time

    key = (cmd, str(root), permission)
    lock = _POOL_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        entry = _POOL.get(key)
        if entry is None:
            return
        entry["sessions"] = max(0, entry["sessions"] - 1)
        entry["last_used"] = time.monotonic()
        if entry["sessions"] == 0 and idle_ttl <= 0:
            try:
                await entry["stack"].aclose()
            except Exception:
                pass
            _POOL.pop(key, None)


async def close_acp_pool():
    """Shut down all pooled harness backends (end of run/session)."""
    for key in list(_POOL):
        entry = _POOL.pop(key)
        try:
            await entry["stack"].aclose()
        except Exception:
            pass


_DIRECT_SESSIONS: dict[tuple, str] = {}


# ---------------------------------------------------------------------------
# Unified multi-backend tool: one `delegate` tool for every known harness.
# Backend-specific spawning policy lives here, not in the model prompt:
# native ACP backends multiplex unlimited; child-per-turn bridges (cmd-acp)
# and direct cmd are capped at 1. `model` is applied best-effort via the
# ACP `model` session config option where the server advertises it.
# ---------------------------------------------------------------------------

BACKENDS: dict[str, dict] = {
    "opencode": {"command": ("opencode", "acp"), "kind": "acp",
                 "max_concurrency": None, "permission": "allow-read"},
    "kilo": {"command": ("kilo", "acp"), "kind": "acp",
             "max_concurrency": None, "permission": "allow-read"},
    "kiro": {"command": ("kiro", "acp"), "kind": "acp",
             "max_concurrency": None, "permission": "allow-read"},
    "hermes": {"command": ("hermes", "acp"), "kind": "acp",
               "max_concurrency": None, "permission": "allow-read"},
    "omp": {"command": ("omp", "acp"), "kind": "acp",
            "max_concurrency": None, "permission": "allow-read"},
    "cline": {"command": ("cline", "--acp"), "kind": "acp",
              "max_concurrency": None, "permission": "allow-read"},
    "copilot": {"command": ("copilot", "--acp"), "kind": "acp",
                "max_concurrency": None, "permission": "allow-read"},
    "agy": {"command": ("agy-acp",), "kind": "acp",
            "max_concurrency": None, "permission": "allow-read"},
    "agy-cli": {"command": ("agy",), "kind": "agy-direct",
                "max_concurrency": 1, "permission": "allow-read"},
    "cmd-acp": {"command": ("cmd-acp",), "kind": "acp",
                "max_concurrency": 1, "permission": "allow-read"},
    "cmd": {"command": ("cmd",), "kind": "cmd",
            "max_concurrency": 1, "permission": "allow-read"},
}


def _describe_backends() -> str:
    return "Known backends: " + ", ".join(sorted(BACKENDS))


async def _delegate_acp(cmd, root, permission, max_concurrency, timeout,
                        task, model=None) -> str:
    import acp

    entry = await _pooled_entry(cmd, root, permission)
    conn, driver = entry["conn"], entry["driver"]
    sem = _pool_semaphore(cmd, root, permission, max_concurrency)

    async def _turn():
        from opentelemetry import trace as _otel

        session = await conn.new_session(cwd=str(root))
        session_id = session.session_id
        before = len(driver.text_parts)
        tmark = len(driver.transcript)
        if model:
            try:
                await conn.set_config_option("model", session_id, model)
            except Exception:
                pass  # server doesn't advertise a model option; use default

        async def _run():
            await conn.prompt(session_id, [acp.text_block(task)])
            return "".join(driver.text_parts[before:]).strip()

        tracer = _otel.get_tracer("pydantic-ai-lab.acp")
        try:
            with tracer.start_as_current_span(
                    "acp.delegate",
                    attributes={"acp.backend": cmd[0],
                                "acp.session_id": session_id}) as span:
                text = await asyncio.wait_for(_run(), timeout=timeout)
                steps = driver.transcript[tmark:]
                kinds = [s["kind"] for s in steps
                         if s["kind"] not in ("agent_message_chunk",)]
                for s in steps:
                    if s["kind"] in ("tool_call", "permission", "fs_read",
                                     "fs_write", "tool_call_update"):
                        span.add_event(s["kind"], {"detail": s["detail"][:500]})
                span.set_attribute("acp.steps", len(steps))
                span.set_attribute("acp.transcript",
                                   __import__("json").dumps(steps)[:8000])
                if kinds:
                    shown = ", ".join(kinds[:12])
                    text += f"\n\n[harness inner steps ({len(steps)}): {shown}]"
                return text
        finally:
            try:
                await conn.close_session(session_id)
            except Exception:
                pass

    try:
        if sem is None:
            return await _turn()
        async with sem:
            return await _turn()
    finally:
        await _release_entry(cmd, root, permission)


async def _delegate_cmd(root, timeout, extra, max_concurrency, task) -> str:
    import json

    key = (root, tuple(extra))
    if key not in CmdHarness._cmd_semaphores:
        CmdHarness._cmd_semaphores[key] = (asyncio.Semaphore(max_concurrency)
                                           if max_concurrency else None)
    sem = CmdHarness._cmd_semaphores[key]

    async def _spawn():
        proc = await asyncio.create_subprocess_exec(
            "cmd", "-p", "--trust", "--output-format", "json", task, *extra,
            cwd=root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"cmd run exceeded {timeout}s")
        final = ""
        for line in out.decode(errors="replace").splitlines():
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("type") == "event" and obj.get("event", {}).get("type") == "run_end":
                final = ((obj["event"].get("result") or {}).get("finalText") or "")
        if proc.returncode != 0 and not final:
            raise RuntimeError(f"cmd exited {proc.returncode}")
        return final.strip()

    if sem is None:
        return await _spawn()
    async with sem:
        return await _spawn()


class UnifiedHarness:
    """One tool for all backends: delegate(task, backend='opencode', model=None).

    Backend spawning policy is built in (see BACKENDS): native ACP backends
    share one warm process with unlimited turns; cmd-acp and cmd serialize
    at 1. Unknown backend names raise with the valid list.
    """
    def __new__(cls, *, cwd=".", timeout=300.0):
        from pydantic_ai.capabilities import AbstractCapability
        from pydantic_ai.toolsets import FunctionToolset

        root = Path(cwd).resolve()

        async def delegate(task: str, backend: str = "opencode",
                           model: str | None = None) -> str:
            """Delegate a task to a CLI harness backend.

            Args:
                task: complete task description for the harness.
                backend: one of the known backends (opencode, kilo, kiro,
                    hermes, omp, cline, copilot, agy, cmd-acp, cmd).
                model: backend model id where the server supports it
                    (best-effort; default model otherwise).
            """
            name = (backend or "opencode").strip().lower()
            if name not in BACKENDS:
                raise ValueError(f"unknown backend {backend!r}. {_describe_backends()}")
            spec = BACKENDS[name]
            if spec["kind"] == "cmd":
                return await _delegate_cmd(root, timeout, [], spec["max_concurrency"], task)
            return await _delegate_acp(
                spec["command"], root, spec["permission"],
                spec["max_concurrency"], timeout, task, model)

        class _Cap(AbstractCapability[None]):
            def get_instructions(self) -> str:
                return ("You can delegate tasks to CLI harness backends via "
                        f"delegate(task, backend, model). {_describe_backends()}.")

            def get_toolset(self):
                return FunctionToolset([delegate])

        return _Cap()


class AcpHarness:
    """Capability factory driving any ACP stdio harness as a delegate tool.

    Backends are pooled: one warm process per command, sessions multiplex
    on top (verified: 2 isolated sessions, 1 pid). Use close_acp_pool()
    to shut backends down.

    Args:
        command: argv of the harness, e.g. ("opencode", "acp").
        name: delegate/tool name suffix + model-facing name.
        cwd: working directory for harness sessions.
        permission: 'allow-read' | 'allow-all' | 'deny-all'.
        timeout: seconds per delegated turn.
        max_concurrency: cap simultaneous turns on the shared backend
            (None = unlimited). Critical for bridges that spawn a child
            per turn (cmd-acp); harmless backpressure everywhere else.
    """

    def __new__(cls, command, *, name=None, description=None, cwd=".",
                permission="allow-read", timeout=300.0, max_concurrency=None):
        from pydantic_ai.capabilities import AbstractCapability
        from pydantic_ai.toolsets import FunctionToolset

        cmd = tuple(command)
        label = name or cmd[0]
        tool_name = f"delegate_to_{label.replace('-', '_').replace(' ', '_')}"
        root = Path(cwd).resolve()

        async def _delegate(task: str) -> str:
            """Delegate a self-contained task to the SUB_NAME harness.

            Use for work suited to an autonomous coding agent. Pass a complete
            task description; returns the harness's final answer text plus a
            compact inner-steps summary (full transcript mirrored to trace).
            Sessions multiplex on one warm backend process per harness.
            """.replace("SUB_NAME", label)
            return await _delegate_acp(cmd, root, permission, max_concurrency,
                                       timeout, task)

        _delegate.__name__ = tool_name

        class _Cap(AbstractCapability[None]):
            def get_instructions(self) -> str:
                return (f"You can delegate self-contained coding tasks to the '{label}' "
                        f"harness via {tool_name} (permission policy: {permission}).")

            def get_toolset(self):
                return FunctionToolset([_delegate])

        inst = _Cap()
        inst._acp_command = cmd  # introspection aid
        return inst


class CmdHarness:
    """Capability factory driving Command Code via headless print mode.

    `cmd` has hooks (shell scripts on tool/session lifecycle) and mods
    (TypeScript packages extending the loop) but no ACP server, and Herdr
    has no cmd integration — so the external control route is
    `cmd -p --trust --output-format json`, parsed for the run_end finalText.

    Args:
        cwd: working directory for harness runs.
        timeout: seconds per delegated turn.
        extra_args: appended after the prompt, e.g. ["--model", "x"].
        max_concurrency: cap simultaneous `cmd` spawns (None = unlimited).
            Recommended: 1, since every turn is a full process.
    """

    _cmd_semaphores: dict[tuple, object] = {}

    def __new__(cls, *, cwd=".", timeout=300.0, extra_args=(), max_concurrency=1):
        import json

        from pydantic_ai.capabilities import AbstractCapability
        from pydantic_ai.toolsets import FunctionToolset

        root = str(Path(cwd).resolve())
        extra = list(extra_args)
        key = (root, tuple(extra))
        if key not in cls._cmd_semaphores:
            cls._cmd_semaphores[key] = (asyncio.Semaphore(max_concurrency)
                                        if max_concurrency else None)
        sem = cls._cmd_semaphores[key]

        async def _spawn(task: str) -> str:
            proc = await asyncio.create_subprocess_exec(
                "cmd", "-p", "--trust", "--output-format", "json", task, *extra,
                cwd=root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                raise TimeoutError(f"cmd run exceeded {timeout}s")
            final = ""
            for line in out.decode(errors="replace").splitlines():
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get("type") == "event" and obj.get("event", {}).get("type") == "run_end":
                    final = ((obj["event"].get("result") or {}).get("finalText") or "")
            if proc.returncode != 0 and not final:
                raise RuntimeError(f"cmd exited {proc.returncode}")
            return final.strip()

        async def delegate_to_cmd(task: str) -> str:
            """Delegate a self-contained coding task to the Command Code CLI.

            Pass a complete task description; returns the harness's final
            answer text.
            """
            if sem is None:
                return await _spawn(task)
            async with sem:
                return await _spawn(task)

        class _Cap(AbstractCapability[None]):
            def get_instructions(self) -> str:
                return ("You can delegate self-contained coding tasks to the "
                        "Command Code CLI via delegate_to_cmd.")

            def get_toolset(self):
                return FunctionToolset([delegate_to_cmd])

        return _Cap()


class DirectHarness:
    """Talk to a backend CLI directly: chat_with(backend, message).

    Unlike delegate() (one-shot task in a fresh session), chat_with keeps
    ONE persistent session per backend across calls — a real conversation
    with that CLI. end_chat(backend) closes it. Sessions multiplex on the
    same pooled backend processes. Direct cmd uses one session id per
    backend via --session-id (process itself is still per call).
    """

    def __new__(cls, *, cwd=".", timeout=300.0):
        from pydantic_ai.capabilities import AbstractCapability
        from pydantic_ai.toolsets import FunctionToolset

        root = Path(cwd).resolve()

        async def chat_with(backend: str, message: str,
                            model: str | None = None) -> str:
            """Chat directly with a backend CLI, keeping conversation state.

            Args:
                backend: opencode, kilo, kiro, hermes, omp, cline, copilot,
                    agy, cmd-acp, cmd.
                message: what to say in that backend's ongoing session.
                model: backend model id where supported (best-effort).
            """
            import acp

            name = (backend or "opencode").strip().lower()
            if name not in BACKENDS:
                raise ValueError(f"unknown backend {backend!r}. {_describe_backends()}")
            spec = BACKENDS[name]
            if spec["kind"] == "cmd":
                extra = ["--session-id", f"lab-{name}"]
                return await _delegate_cmd(
                    root, timeout, extra, spec["max_concurrency"],
                    message + " [direct chat, same session]")
            entry = await _pooled_entry(spec["command"], root, spec["permission"])
            conn, driver = entry["conn"], entry["driver"]
            sem = _pool_semaphore(spec["command"], root, spec["permission"],
                                  spec["max_concurrency"])
            key = (spec["command"], str(root), spec["permission"])

            async def _turn():
                session_id = _DIRECT_SESSIONS.get(key)
                if session_id is None:
                    session = await conn.new_session(cwd=str(root))
                    session_id = session.session_id
                    _DIRECT_SESSIONS[key] = session_id
                    if model:
                        try:
                            await conn.set_config_option("model", session_id, model)
                        except Exception:
                            pass
                before = len(driver.text_parts)

                async def _run():
                    await conn.prompt(session_id, [acp.text_block(message)])
                    return "".join(driver.text_parts[before:]).strip()

                try:
                    return await asyncio.wait_for(_run(), timeout=timeout)
                except Exception:
                    _DIRECT_SESSIONS.pop(key, None)
                    raise

            try:
                if sem is None:
                    return await _turn()
                async with sem:
                    return await _turn()
            finally:
                await _release_entry(spec["command"], root, spec["permission"])

        async def end_chat(backend: str) -> str:
            """Close the persistent chat session for a backend."""
            name = (backend or "opencode").strip().lower()
            if name not in BACKENDS:
                raise ValueError(f"unknown backend {backend!r}. {_describe_backends()}")
            spec = BACKENDS[name]
            if spec["kind"] == "cmd":
                return f"direct cmd chat for {name} closed (sessions persist in cmd itself)."
            key = (spec["command"], str(root), spec["permission"])
            session_id = _DIRECT_SESSIONS.pop(key, None)
            if session_id is None:
                return f"no open chat for {name}."
            entry = await _pooled_entry(spec["command"], root, spec["permission"])
            try:
                await entry["conn"].close_session(session_id)
            except Exception:
                pass
            finally:
                await _release_entry(spec["command"], root, spec["permission"])
            return f"chat with {name} closed."

        class _Cap(AbstractCapability[None]):
            def get_instructions(self) -> str:
                return ("Talk to backend CLIs directly via chat_with(backend, "
                        f"message) — one persistent session each. {_describe_backends()} "
                        "Use end_chat(backend) when done. Prefer this over "
                        "delegate() when the user wants a conversation, not a task.")

            def get_toolset(self):
                return FunctionToolset([chat_with, end_chat])

        return _Cap()


_DIRECT_TURNS: dict[tuple, list[dict]] = {}
_AGY_SEEN: dict[str, int] = {}


def _proto_strings(blob: bytes) -> list[str]:
    """Schemaless protobuf string extractor (no schema/dependency needed)."""
    out: list[str] = []
    i, n = 0, len(blob)

    def varint(j):
        s = sh = 0
        while j < n:
            b = blob[j]
            j += 1
            s |= (b & 0x7F) << sh
            if not b & 0x80:
                return s, j
            sh += 7
        return None, j

    while i < n:
        r = varint(i)
        if r[0] is None:
            break
        key, i = r
        wt = key & 7
        if wt == 2:
            r = varint(i)
            if r[0] is None:
                break
            ln, i = r
            chunk = blob[i:i + ln]
            i += ln
            try:
                s = chunk.decode("utf-8")
                if len(s) >= 3 and all(c.isprintable() or c in "\n\t" for c in s):
                    out.append(s[:300])
            except ValueError:
                pass
            if len(chunk) > 4:
                for s2 in _proto_strings(chunk):
                    if s2 not in out:
                        out.append(s2)
        elif wt == 0:
            _, i = varint(i)
        elif wt == 5:
            i += 4
        elif wt == 1:
            i += 8
        else:
            break
    return out


def _agy_db_steps(conv_id: str) -> list[dict]:
    """Scrape new tool steps from agy's conversation DB. Never raises."""
    import sqlite3

    steps: list[dict] = []
    db_path = Path.home() / ".gemini" / "antigravity-cli" / "conversations" / f"{conv_id}.db"
    if not db_path.exists():
        return steps
    try:
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        last = _AGY_SEEN.get(conv_id, -1)
        rows = db.execute(
            "SELECT idx, step_type, step_payload FROM steps WHERE idx > ? ORDER BY idx",
            (last,)).fetchall()
        db.close()
        for idx, stype, pay in rows:
            _AGY_SEEN[conv_id] = max(_AGY_SEEN.get(conv_id, -1), idx)
            if stype != 132:  # 132 = tool call rows
                continue
            strs = [s for s in _proto_strings(bytes(pay))
                    if len(s) < 300 and " " not in s[:60] or "{" in s or "/" in s]
            name = next((s.split("{")[0].strip(" \"") for s in strs
                         if s and len(s) < 60 and "_" in s
                         and not s.startswith("call_")), "?")
            arg = next((s for s in strs if s.startswith("{")), "")
            steps.append({"kind": "tool_call", "detail": f"{name} {arg[:200]}"})
    except Exception:
        pass
    return steps


def _agy_conv_for_acp_session(session_id: str) -> str | None:
    """Map an ACP session to its agy conversation via the bridge store."""
    import json

    try:
        store = json.loads((Path.home() / ".openab" / "agy-acp" / "sessions.json").read_text())
        return ((store.get("sessions") or {}).get(session_id) or {}).get("conversation_id")
    except Exception:
        return None


async def direct_send(backend: str, message: str, model: str | None = None,
                      timeout: float = 300.0) -> dict:
    """Send a message straight to a backend CLI session. No parent model.

    One persistent session per backend (multiplexed on pooled processes).
    Returns {"backend":..., "text":..., "tools":[...]} for direct display.
    """
    import acp

    name = (backend or "opencode").strip().lower()
    if name not in BACKENDS:
        raise ValueError(f"unknown backend {backend!r}. {_describe_backends()}")
    spec = BACKENDS[name]
    if spec["kind"] == "cmd":
        text = await _delegate_cmd("/tmp", timeout, ["--session-id", f"lab-{name}"],
                                   spec["max_concurrency"], message)
        turns = _DIRECT_TURNS.setdefault((name,), [])
        turns.append({"role": "user", "text": message})
        turns.append({"role": name, "text": text, "tools": []})
        return {"backend": name, "text": text, "tools": []}
    if spec["kind"] == "agy-direct":
        from pathlib import Path as _P

        r = await _delegate_agy_direct(_P("/tmp").resolve(), timeout, message)
        turns = _DIRECT_TURNS.setdefault((name,), [])
        turns.append({"role": "user", "text": message})
        turns.append({"role": name, "text": r["text"],
                      "tools": r["tools"], "steps": r["steps"]})
        return {"backend": name, **r}
    root = Path("/tmp").resolve()
    entry = await _pooled_entry(spec["command"], root, spec["permission"])
    conn, driver = entry["conn"], entry["driver"]
    sem = _pool_semaphore(spec["command"], root, spec["permission"],
                          spec["max_concurrency"])
    key = (spec["command"], str(root), spec["permission"])

    async def _turn():
        session_id = _DIRECT_SESSIONS.get(key)
        if session_id is None:
            session = await conn.new_session(cwd=str(root))
            session_id = session.session_id
            _DIRECT_SESSIONS[key] = session_id
            if model:
                try:
                    await conn.set_config_option("model", session_id, model)
                except Exception:
                    pass
        tmark, before = len(driver.transcript), len(driver.text_parts)

        async def _run():
            await conn.prompt(session_id, [acp.text_block(message)])
            return "".join(driver.text_parts[before:]).strip()

        try:
            text = await asyncio.wait_for(_run(), timeout=timeout)
        except Exception:
            _DIRECT_SESSIONS.pop(key, None)
            raise
        tools = sorted({s["detail"][:120] for s in driver.transcript
                        if s["kind"] in ("tool_call", "tool_call_update")})
        steps = [{"kind": s["kind"], "detail": s["detail"][:500]}
                 for s in driver.transcript[tmark:]
                 if s["kind"] not in ("agent_message_chunk", "user_message_chunk")]
        if name == "agy":
            # The ACP bridge streams text only; tool truth lives in agy's
            # conversation DB — same process, multiplexed sessions kept.
            import time as _t
            conv = _agy_conv_for_acp_session(session_id)
            convs = [conv] if conv else []
            if not convs:
                # Bridge didn't record the mapping: newest DBs touched
                # during this turn (verified fallback).
                import glob as _g
                pat = str(Path.home() / ".gemini" / "antigravity-cli"
                          / "conversations" / "*.db")
                cands = [(os.path.getmtime(p), p) for p in _g.glob(pat)]
                convs = [p.split("/")[-1][:-3] for _, p in
                         sorted(cands)[-3:] if _t.time() - os.path.getmtime(p) < 600]
            for c in convs:
                for s in _agy_db_steps(c):
                    steps.append(s)
                    if s["kind"] == "tool_call":
                        tools.append(s["detail"][:120])
            tools = sorted(set(tools))
        turns = _DIRECT_TURNS.setdefault((name,), [])
        turns.append({"role": "user", "text": message})
        turns.append({"role": name, "text": text, "tools": tools, "steps": steps})
        return {"backend": name, "text": text, "tools": tools, "steps": steps}

    try:
        if sem is None:
            return await _turn()
        async with sem:
            return await _turn()
    finally:
        await _release_entry(spec["command"], root, spec["permission"])


def direct_history(backend: str) -> list[dict]:
    """Turn history for a backend this server lifetime."""
    return _DIRECT_TURNS.get(((backend or "").strip().lower(),), [])


async def direct_end(backend: str) -> str:
    """Close a backend's direct session."""
    name = (backend or "").strip().lower()
    spec = BACKENDS.get(name)
    if spec is None:
        raise ValueError(f"unknown backend {backend!r}. {_describe_backends()}")
    if spec["kind"] == "cmd":
        _DIRECT_TURNS.pop((name,), None)
        return f"direct chat with {name} closed (cmd keeps its own session)."
    root = Path("/tmp").resolve()
    for key in list(_DIRECT_SESSIONS):
        if key[0] == spec["command"]:
            entry = await _pooled_entry(spec["command"], root, spec["permission"])
            try:
                await entry["conn"].close_session(_DIRECT_SESSIONS.pop(key))
            except Exception:
                pass
            finally:
                await _release_entry(spec["command"], root, spec["permission"])
            _DIRECT_TURNS.pop((name,), None)
            return f"direct chat with {name} closed."
    _DIRECT_TURNS.pop((name,), None)
    return f"no open direct chat for {name}."


_AGY_CONVS: dict[str, str] = {}


async def _delegate_agy_direct(root, timeout, task) -> dict:
    """Drive `agy` CLI directly via stream-json; parse tool/usage steps.

    Same event source project-tracker uses. One conversation per cwd,
    continued with --resume. Returns {"text","tools","steps"}.
    """
    import json

    key = str(root)
    cmd = ["agy", f"--print={task}", "--output-format", "stream-json"]
    if key in _AGY_CONVS:
        cmd += ["--resume", _AGY_CONVS[key]]
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(root),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"agy run exceeded {timeout}s")
    text_parts, steps, tools = [], [], []
    for line in out.decode(errors="replace").splitlines():
        try:
            obj = json.loads(line.strip())
        except ValueError:
            continue
        ev = obj.get("event")
        if ev == "init":
            cid = (obj.get("init") or {}).get("conversation_id") or obj.get("conversation_id")
            if cid:
                _AGY_CONVS[key] = cid
            continue
        if ev == "result":
            resp = (obj.get("result") or {}).get("response")
            if resp:
                text_parts = [resp]
            u = (obj.get("result") or {}).get("usage") or {}
            if u:
                steps.append({"kind": "usage_update",
                              "detail": f"in={u.get('input_tokens')} out={u.get('output_tokens')}"})
            continue
        su = obj.get("step_update") or {}
        stype = su.get("step_type", "")
        if stype == "agent_response" and su.get("text_delta"):
            text_parts.append(su["text_delta"])
        elif stype == "tool":
            name = su.get("tool_name") or "?"
            tools.append(name)
            steps.append({"kind": "tool_call",
                          "detail": f"{name} {__import__('json').dumps(su.get('args') or su.get('tool_info') or {})[:200]}"})
        elif "usage" in su:
            u = su["usage"]
            steps.append({"kind": "usage_update",
                          "detail": f"in={u.get('input_tokens')} out={u.get('output_tokens')}"})
        elif su.get("text"):
            text_parts.append(su["text"])
    text = "".join(text_parts).strip()
    if proc.returncode != 0 and not text:
        raise RuntimeError(f"agy exited {proc.returncode}")
    return {"text": text, "tools": sorted(set(tools)), "steps": steps}


# ---------------------------------------------------------------------------
# Live turn streaming: run the turn in the background, stream steps as SSE.
# ---------------------------------------------------------------------------
_TURNS: dict[str, dict] = {}


def _turn_emit(turn_id: str, event: dict):
    t = _TURNS.get(turn_id)
    if t is not None:
        t["events"].append(event)


async def _agy_direct_streaming(root, timeout, task, turn_id):
    """agy-cli variant with live stdout parsing -> per-step SSE events."""
    import json

    key = str(root)
    cmd = ["agy", f"--print={task}", "--output-format", "stream-json"]
    if key in _AGY_CONVS:
        cmd += ["--resume", _AGY_CONVS[key]]
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(root),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    text_parts: list[str] = []

    async def _feed():
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                obj = json.loads(line.decode(errors="replace").strip())
            except ValueError:
                continue
            ev, su = obj.get("event"), obj.get("step_update") or {}
            if ev == "init":
                cid = ((obj.get("init") or {}).get("conversation_id")
                       or obj.get("conversation_id"))
                if cid:
                    _AGY_CONVS[key] = cid
            elif ev == "result":
                resp = (obj.get("result") or {}).get("response")
                if resp:
                    text_parts.append(resp)
                u = (obj.get("result") or {}).get("usage") or {}
                if u:
                    _turn_emit(turn_id, {"kind": "usage_update",
                        "detail": f"in={u.get('input_tokens')} out={u.get('output_tokens')}"})
            elif su.get("step_type") == "agent_response" and su.get("text_delta"):
                pass  # text assembled at end; deltas too noisy per-char
            elif su.get("step_type") == "tool":
                name = su.get("tool_name") or "?"
                _turn_emit(turn_id, {"kind": "tool_call",
                    "detail": f"{name} {json.dumps(su.get('args') or {})[:200]}"})

    try:
        await asyncio.wait_for(asyncio.gather(_feed(), proc.wait()), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"agy run exceeded {timeout}s")
    text = "".join(text_parts).strip()
    if proc.returncode != 0 and not text:
        raise RuntimeError(f"agy exited {proc.returncode}")
    return text


async def _bridge_turn_streaming(entry, conn, driver, sem, root, message,
                                 timeout, turn_id, session_id=None):
    """Bridge turn with live transcript polling -> SSE events."""
    import acp

    if session_id is None:
        session = await conn.new_session(cwd=str(root))
        session_id = session.session_id
    mark = len(driver.transcript)
    done = asyncio.Event()

    async def _poll():
        seen = mark
        while not done.is_set():
            await asyncio.sleep(0.3)
            for s in driver.transcript[seen:]:
                if s["kind"] not in ("agent_message_chunk", "user_message_chunk"):
                    _turn_emit(turn_id, {"kind": s["kind"],
                                         "detail": s["detail"][:500]})
            seen = len(driver.transcript)

    async def _run():
        await conn.prompt(session_id, [acp.text_block(message)])

    poller = asyncio.create_task(_poll())
    try:
        if sem is None:
            await asyncio.wait_for(_run(), timeout=timeout)
        else:
            async with sem:
                await asyncio.wait_for(_run(), timeout=timeout)
    finally:
        done.set()
        await poller
    return session_id


async def direct_start(backend: str, message: str, model: str | None = None,
                       timeout: float = 300.0) -> str:
    """Start a turn in the background; stream via turn SSE. Returns turn_id."""
    import uuid

    name = (backend or "opencode").strip().lower()
    if name not in BACKENDS:
        raise ValueError(f"unknown backend {backend!r}. {_describe_backends()}")
    turn_id = uuid.uuid4().hex[:12]
    _TURNS[turn_id] = {"backend": name, "events": [], "done": False,
                       "text": "", "error": "", "tools": []}
    asyncio.get_running_loop().create_task(_direct_bg(
        turn_id, name, message, model, timeout))
    return turn_id


async def _direct_bg(turn_id, name, message, model, timeout):
    spec = BACKENDS[name]
    t = _TURNS[turn_id]
    try:
        if spec["kind"] == "cmd":
            text = await _delegate_cmd("/tmp", timeout,
                                       ["--session-id", f"lab-{name}"],
                                       spec["max_concurrency"], message)
            t["text"] = text
        elif spec["kind"] == "agy-direct":
            from pathlib import Path as _P

            root = _P("/tmp").resolve()
            text = await _agy_direct_streaming(root, timeout, message, turn_id)
            t["text"] = text
            turns = _DIRECT_TURNS.setdefault((name,), [])
            turns.append({"role": "user", "text": message})
            turns.append({"role": name, "text": text, "tools": [], "steps":
                          [e for e in t["events"]]})
        else:
            root = Path("/tmp").resolve()
            entry = await _pooled_entry(spec["command"], root, spec["permission"])
            conn, driver = entry["conn"], entry["driver"]
            sem = _pool_semaphore(spec["command"], root, spec["permission"],
                                  spec["max_concurrency"])
            key = (spec["command"], str(root), spec["permission"])
            try:
                session_id = _DIRECT_SESSIONS.get(key)
                if session_id is None:
                    session = await conn.new_session(cwd=str(root))
                    session_id = session.session_id
                    _DIRECT_SESSIONS[key] = session_id
                    if model:
                        try:
                            await conn.set_config_option("model", session_id, model)
                        except Exception:
                            pass
                before = len(driver.text_parts)
                await _bridge_turn_streaming(entry, conn, driver, sem, root,
                                             message, timeout, turn_id,
                                             session_id)
                text = "".join(driver.text_parts[before:]).strip()
                t["text"] = text
                tools = sorted({s["detail"][:120] for s in driver.transcript
                                if s["kind"] in ("tool_call", "tool_call_update")})
                t["tools"] = tools
                # agy bridge: enrich from conversation DB (text-only wire)
                if name == "agy":
                    conv = _agy_conv_for_acp_session(session_id)
                    convs = [conv] if conv else []
                    if not convs:
                        import glob as _g
                        import time as _t
                        pat = str(Path.home() / ".gemini" / "antigravity-cli"
                                  / "conversations" / "*.db")
                        cands = [(os.path.getmtime(p), p) for p in _g.glob(pat)]
                        convs = [p.split("/")[-1][:-3] for _, p in sorted(cands)[-3:]
                                 if _t.time() - os.path.getmtime(p) < 600]
                    for c in convs:
                        for s in _agy_db_steps(c):
                            _turn_emit(turn_id, {"kind": s["kind"], "detail": s["detail"][:500]})
                            if s["kind"] == "tool_call":
                                tools.append(s["detail"][:120])
                    t["tools"] = sorted(set(tools))
                turns = _DIRECT_TURNS.setdefault((name,), [])
                turns.append({"role": "user", "text": message})
                turns.append({"role": name, "text": text, "tools": t["tools"],
                              "steps": [e for e in t["events"]]})
            finally:
                await _release_entry(spec["command"], root, spec["permission"])
    except asyncio.CancelledError:
        t["error"] = "cancelled"
    except Exception as e:  # noqa: BLE001 - surfaced in chat
        t["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    finally:
        t["done"] = True
