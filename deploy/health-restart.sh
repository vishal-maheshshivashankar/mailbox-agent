#!/usr/bin/env bash
# Runs on the host (via cron), not in a container - deliberately avoids
# mounting the Docker socket into any container (e.g. an "autoheal"
# sidecar) just to get restart-on-unhealthy, since that grants whatever's
# in that container root-equivalent control over the whole host's Docker.
# Plain `docker compose` never acts on HEALTHCHECK status by itself
# (restart: unless-stopped only reacts to the process exiting), so this
# script is what actually restarts a hung-but-not-crashed container.
#
# Install: crontab -e, add a line like:
#   */5 * * * * /home/ubuntu/mailbox-agent/deploy/health-restart.sh >> /home/ubuntu/mailbox-agent/health-restart.log 2>&1
set -euo pipefail

CONTAINER=mailbox-agent
COMPOSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

status=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo "missing")

if [ "$status" = "unhealthy" ]; then
    echo "$(date -u +%FT%TZ) $CONTAINER is unhealthy, restarting"
    (cd "$COMPOSE_DIR" && docker compose restart)
fi
