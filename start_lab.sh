#!/bin/bash
# Start the Pydantic AI Lab stack for the Service Dashboard's single
# "Pydantic AI Lab" card: chat UIs + unified hub (hub foreground, dashboard
# tracks this script). Phoenix telemetry is NOT auto-started (cold boot pegs
# a core for minutes): the hub Telemetry tab starts/stops it on demand via
# /api/telemetry/*. SearXNG is a separate dashboard entry — only ensure it
# here, never stop it.
cd /home/ubu/opencode-work/pydantic-ai-lab || exit 1
UV=/home/ubu/.local/bin/uv
# Dashboard launches with a minimal PATH: harness CLIs live in these dirs,
# and bridges (agy-acp -> agy) inherit this environment when spawning.
export PATH="/home/ubu/.local/bin:/home/ubu/.opencode/bin:/usr/local/bin:/usr/bin:/bin"

docker start searxng-lab >/dev/null 2>&1

cleanup() {
  kill $P_RESEARCH $P_PLAN $P_EXEC $P_FLOW $P_APPROVAL $P_ACPTEST 2>/dev/null
  exit 0
}
trap cleanup TERM INT

SERVE_AGENT=researcher $UV run uvicorn serve_web:app --host 0.0.0.0 --port 7933 >/tmp/lab-7933.log 2>&1 & P_RESEARCH=$!
SERVE_AGENT=researchplan $UV run uvicorn serve_web:app --host 0.0.0.0 --port 7934 >/tmp/lab-7934.log 2>&1 & P_PLAN=$!
SERVE_AGENT=researchexecute $UV run uvicorn serve_web:app --host 0.0.0.0 --port 7935 >/tmp/lab-7935.log 2>&1 & P_EXEC=$!
SERVE_AGENT=researchflow $UV run uvicorn serve_web:app --host 0.0.0.0 --port 7936 >/tmp/lab-7936.log 2>&1 & P_FLOW=$!
SERVE_AGENT=approval $UV run uvicorn serve_web:app --host 0.0.0.0 --port 7932 >/tmp/lab-7932.log 2>&1 & P_APPROVAL=$!
SERVE_AGENT=acptest $UV run uvicorn serve_web:app --host 0.0.0.0 --port 7941 >/tmp/lab-7941.log 2>&1 & P_ACPTEST=$!

# Hub in the foreground: dashboard stop signals THIS script -> trap cleans up.
$UV run uvicorn serve_unified:app --host 0.0.0.0 --port 7940
cleanup
