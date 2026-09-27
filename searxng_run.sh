#!/bin/bash
# Lifecycle wrapper so the Service Dashboard can actually start/stop the
# local SearXNG docker container. The dashboard tracks THIS script's PID;
# plain `docker start` exits immediately (dashboard reports failure) and
# `stop` then has nothing to kill (container keeps running).
# Here: start the container, then wait; on SIGTERM/SIGINT stop it.
docker start searxng-lab >/dev/null 2>&1
cleanup() {
  docker stop searxng-lab >/dev/null 2>&1
  exit 0
}
trap cleanup TERM INT
while [ "$(docker inspect searxng-lab --format '{{.State.Status}}' 2>/dev/null)" = "running" ]; do
  sleep 2
done
