#!/usr/bin/env bash
set -euo pipefail

AGENT_CONTAINER="agent-education-agent"
FAULT_CONTAINER="agent-education-fault-injector"
HTTPD_CONTAINER="agent-education-httpd"
TOMCAT_CONTAINER="agent-education-tomcat"
POSTGRES_CONTAINER="agent-education-postgres"

echo "==> Stopping current Agent so it cannot interfere with reset"
docker rm -f "$AGENT_CONTAINER" >/dev/null 2>&1 || true

echo "==> Removing fault injector"
docker rm -f "$FAULT_CONTAINER" >/dev/null 2>&1 || true

echo "==> Restoring service containers"
for container in "$POSTGRES_CONTAINER" "$TOMCAT_CONTAINER" "$HTTPD_CONTAINER"; do
  if docker inspect "$container" >/dev/null 2>&1; then
    docker start "$container" >/dev/null 2>&1 || true
  else
    echo "Required container is missing: $container" >&2
    echo "Recreate the shared system with scripts/pure_docker_up.sh." >&2
    exit 1
  fi
done

echo "==> Waiting for PostgreSQL"
for _ in $(seq 1 30); do
  if docker exec "$POSTGRES_CONTAINER" pg_isready -U postgres -d memberdb >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$POSTGRES_CONTAINER" pg_isready -U postgres -d memberdb >/dev/null

echo "==> Restoring DB password"
docker exec "$POSTGRES_CONTAINER" \
  psql -U postgres -d memberdb \
  -c "ALTER USER memberapp WITH PASSWORD 'memberapp';" \
  >/dev/null

echo "==> Restoring httpd proxy destination"
docker exec "$HTTPD_CONTAINER" sh -c \
  "sed -i 's/tomcat:18080/tomcat:8080/g' /usr/local/apache2/conf/extra/member-app.conf && httpd -k graceful"

echo "==> Waiting for application read path"
for _ in $(seq 1 30); do
  if curl -fsS http://localhost:8088/api/members >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl -fsS http://localhost:8088/api/members >/dev/null

echo "==> Verifying application write path"
docker exec "$POSTGRES_CONTAINER" psql -U postgres -d memberdb -Atc   "DELETE FROM members WHERE email='battle-reset-check@example.local';" >/dev/null

body_file="$(mktemp)"
trap 'rm -f "$body_file"' EXIT
status=$(curl -sS --max-time 5 -o "$body_file" -w '%{http_code}'   -X POST   -H 'Content-Type: application/json'   -d '{"name":"Battle Reset Check","department":"training","email":"battle-reset-check@example.local"}'   http://localhost:8088/api/members || true)

if [[ "$status" != "201" ]]; then
  echo "Application write path did not recover. HTTP $status" >&2
  cat "$body_file" >&2 || true
  exit 1
fi

member_id=$(sed -n 's/.*"id"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$body_file")
if [[ -z "$member_id" ]]; then
  echo "Could not parse reset-check member id." >&2
  exit 1
fi

curl -fsS --max-time 5 -X DELETE   "http://localhost:8088/api/members/$member_id" >/dev/null

echo "Battle environment is clean and healthy."
