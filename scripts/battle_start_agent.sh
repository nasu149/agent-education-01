#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Keep Battle startup consistent with docker compose / pure_docker_up.sh.
if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

TEAM_ID="${1:-}"
NETWORK="agent-education-net"
AGENT_CONTAINER="agent-education-agent"

if [[ -z "$TEAM_ID" ]]; then
  echo "Usage: $0 <team-id>" >&2
  echo "Example: $0 team-a" >&2
  exit 2
fi

IMAGE="agent-education-agent:$TEAM_ID"

if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  echo "GEMINI_API_KEY is required." >&2
  exit 2
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Image not found: $IMAGE" >&2
  echo "Build it first with ./scripts/battle_build_agent.sh $TEAM_ID" >&2
  exit 2
fi

if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
  echo "Docker network $NETWORK does not exist." >&2
  echo "Prepare the shared system first with scripts/pure_docker_up.sh." >&2
  exit 2
fi

GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.5-flash-lite}"
GEMINI_TIMEOUT_SECONDS="${GEMINI_TIMEOUT_SECONDS:-90}"
LANGGRAPH_PRINT_MODE="${LANGGRAPH_PRINT_MODE:-updates}"
HEALTH_CHECK_INTERVAL_SECONDS="${HEALTH_CHECK_INTERVAL_SECONDS:-5}"
MONITOR_STARTUP_GRACE_SECONDS="${MONITOR_STARTUP_GRACE_SECONDS:-20}"
FAILURE_THRESHOLD="${FAILURE_THRESHOLD:-2}"
MAX_INVESTIGATION_TOOL_RESULTS="${MAX_INVESTIGATION_TOOL_RESULTS:-8}"
VERIFY_RETRY_LIMIT="${VERIFY_RETRY_LIMIT:-1}"

docker rm -f "$AGENT_CONTAINER" >/dev/null 2>&1 || true

echo "==> Starting $TEAM_ID Agent"
echo "==> Gemini timeout: ${GEMINI_TIMEOUT_SECONDS}s"
echo "==> Health check: every ${HEALTH_CHECK_INTERVAL_SECONDS}s, startup grace ${MONITOR_STARTUP_GRACE_SECONDS}s, failure threshold ${FAILURE_THRESHOLD}"
docker run -d \
  --name "$AGENT_CONTAINER" \
  --network "$NETWORK" \
  --network-alias agent \
  -p 8090:8090 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  -e GEMINI_MODEL="$GEMINI_MODEL" \
  -e GEMINI_TIMEOUT_SECONDS="$GEMINI_TIMEOUT_SECONDS" \
  -e LANGGRAPH_PRINT_MODE="$LANGGRAPH_PRINT_MODE" \
  -e APP_BASE_URL=http://httpd \
  -e TARGET_SERVICES=httpd,tomcat,postgres \
  -e TARGET_HTTPD_CONTAINER=agent-education-httpd \
  -e TARGET_TOMCAT_CONTAINER=agent-education-tomcat \
  -e TARGET_POSTGRES_CONTAINER=agent-education-postgres \
  -e DB_ADMIN_HOST=postgres \
  -e DB_ADMIN_PORT=5432 \
  -e DB_ADMIN_NAME=memberdb \
  -e DB_ADMIN_USER=postgres \
  -e DB_ADMIN_PASSWORD=postgres \
  -e TERMINABLE_DB_APPLICATIONS=fault-injector,fault-locker \
  -e FAULT_DB_USER=fault_injector \
  -e HEALTH_CHECK_INTERVAL_SECONDS="$HEALTH_CHECK_INTERVAL_SECONDS" \
  -e MONITOR_STARTUP_GRACE_SECONDS="$MONITOR_STARTUP_GRACE_SECONDS" \
  -e FAILURE_THRESHOLD="$FAILURE_THRESHOLD" \
  -e MAX_INVESTIGATION_TOOL_RESULTS="$MAX_INVESTIGATION_TOOL_RESULTS" \
  -e VERIFY_RETRY_LIMIT="$VERIFY_RETRY_LIMIT" \
  -e LOG_LEVEL="${LOG_LEVEL:-INFO}" \
  "$IMAGE" \
  >/dev/null

echo "Agent started: $TEAM_ID"
echo "Dashboard: http://localhost:8090"
echo "Logs: docker logs -f $AGENT_CONTAINER"
