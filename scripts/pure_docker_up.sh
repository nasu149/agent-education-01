#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NETWORK="agent-education-net"
VOLUME="agent-education-postgres-data"
POSTGRES_CONTAINER="agent-education-postgres"
TOMCAT_CONTAINER="agent-education-tomcat"
HTTPD_CONTAINER="agent-education-httpd"
AGENT_CONTAINER="agent-education-agent"
FAULT_CONTAINER="agent-education-fault-injector"

if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  echo "GEMINI_API_KEY is required. Example: export GEMINI_API_KEY=..." >&2
  exit 2
fi

cd "$ROOT_DIR"

for container in "$FAULT_CONTAINER" "$AGENT_CONTAINER" "$HTTPD_CONTAINER" "$TOMCAT_CONTAINER" "$POSTGRES_CONTAINER"; do
  docker rm -f "$container" >/dev/null 2>&1 || true
done

docker network rm "$NETWORK" >/dev/null 2>&1 || true
if [[ "${RESET_DB_DATA:-1}" == "1" ]]; then
  docker volume rm "$VOLUME" >/dev/null 2>&1 || true
fi

echo "==> Building training images"
docker build -t agent-education-postgres ./postgres
docker build -t agent-education-tomcat ./member-app
docker build -t agent-education-httpd ./httpd
docker build -t agent-education-agent ./agent
docker build -t agent-education-fault-injector ./fault-injector

echo "==> Creating network and database volume"
docker network create "$NETWORK" >/dev/null
docker volume create "$VOLUME" >/dev/null

echo "==> Starting PostgreSQL"
docker run -d \
  --name "$POSTGRES_CONTAINER" \
  --network "$NETWORK" \
  --network-alias postgres \
  -e POSTGRES_DB=memberdb \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_HOST_AUTH_METHOD=trust \
  -v "$VOLUME:/var/lib/postgresql/data" \
  agent-education-postgres \
  postgres -c max_connections=20 -c superuser_reserved_connections=3 \
  >/dev/null

for _ in $(seq 1 40); do
  if docker exec "$POSTGRES_CONTAINER" pg_isready -U postgres -d memberdb >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$POSTGRES_CONTAINER" pg_isready -U postgres -d memberdb >/dev/null

echo "==> Starting Tomcat"
docker run -d \
  --name "$TOMCAT_CONTAINER" \
  --network "$NETWORK" \
  --network-alias tomcat \
  -e DB_HOST=postgres \
  -e DB_PORT=5432 \
  -e DB_NAME=memberdb \
  -e DB_USER=memberapp \
  -e DB_PASSWORD=memberapp \
  agent-education-tomcat \
  >/dev/null

echo "==> Starting httpd"
docker run -d \
  --name "$HTTPD_CONTAINER" \
  --network "$NETWORK" \
  --network-alias httpd \
  -p 8088:80 \
  agent-education-httpd \
  >/dev/null

echo "==> Starting incident-response Agent"
docker run -d \
  --name "$AGENT_CONTAINER" \
  --network "$NETWORK" \
  --network-alias agent \
  -p 8090:8090 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  -e GEMINI_MODEL="${GEMINI_MODEL:-gemini-2.5-flash}" \
  -e APP_BASE_URL=http://httpd \
  -e TARGET_SERVICES=httpd,tomcat,postgres \
  -e TARGET_HTTPD_CONTAINER="$HTTPD_CONTAINER" \
  -e TARGET_TOMCAT_CONTAINER="$TOMCAT_CONTAINER" \
  -e TARGET_POSTGRES_CONTAINER="$POSTGRES_CONTAINER" \
  -e DB_ADMIN_HOST=postgres \
  -e DB_ADMIN_PORT=5432 \
  -e DB_ADMIN_NAME=memberdb \
  -e DB_ADMIN_USER=postgres \
  -e DB_ADMIN_PASSWORD=postgres \
  -e TERMINABLE_DB_APPLICATIONS=fault-injector \
  -e FAULT_DB_USER=fault_injector \
  -e HEALTH_CHECK_INTERVAL_SECONDS="${HEALTH_CHECK_INTERVAL_SECONDS:-5}" \
  -e MONITOR_STARTUP_GRACE_SECONDS="${MONITOR_STARTUP_GRACE_SECONDS:-20}" \
  -e FAILURE_THRESHOLD="${FAILURE_THRESHOLD:-2}" \
  -e MAX_INVESTIGATION_TOOL_RESULTS="${MAX_INVESTIGATION_TOOL_RESULTS:-8}" \
  -e VERIFY_RETRY_LIMIT="${VERIFY_RETRY_LIMIT:-1}" \
  -e LOG_LEVEL="${LOG_LEVEL:-INFO}" \
  agent-education-agent \
  >/dev/null

echo
echo "Started with plain Docker commands only."
echo "Application: http://localhost:8088"
echo "Agent UI:    http://localhost:8090"
echo
echo "Inject the incident with:"
echo "  ./scripts/inject_db_connection_exhaustion.sh"
