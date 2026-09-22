#!/usr/bin/env bash
set -euo pipefail

AGENT_CONTAINER="agent-education-agent"
FAULT_CONTAINER="agent-education-fault-injector"
LOCK_CONTAINER="agent-education-lock-injector"
HTTPD_CONTAINER="agent-education-httpd"
TOMCAT_CONTAINER="agent-education-tomcat"
POSTGRES_CONTAINER="agent-education-postgres"

echo "==> Stopping current Agent so it cannot interfere with reset"
docker rm -f "$AGENT_CONTAINER" >/dev/null 2>&1 || true

echo "==> Removing fault injectors"
docker rm -f "$FAULT_CONTAINER" >/dev/null 2>&1 || true
docker rm -f "$LOCK_CONTAINER" >/dev/null 2>&1 || true

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

echo "==> Waiting for application HTTP 200"
for _ in $(seq 1 30); do
  if curl -fsS http://localhost:8088/api/members >/dev/null 2>&1; then
    echo "Battle environment is clean and healthy."
    exit 0
  fi
  sleep 1
done

echo "Application did not recover to HTTP 200." >&2
echo "Inspect Tomcat/PostgreSQL logs or rebuild with scripts/pure_docker_up.sh." >&2
exit 1
