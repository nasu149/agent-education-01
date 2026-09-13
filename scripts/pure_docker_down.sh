#!/usr/bin/env bash
set -euo pipefail

NETWORK="agent-education-net"
VOLUME="agent-education-postgres-data"

for container in \
  agent-education-fault-injector \
  agent-education-agent \
  agent-education-httpd \
  agent-education-tomcat \
  agent-education-postgres; do
  docker rm -f "$container" >/dev/null 2>&1 || true
done

docker network rm "$NETWORK" >/dev/null 2>&1 || true

if [[ "${KEEP_DB_DATA:-0}" != "1" ]]; then
  docker volume rm "$VOLUME" >/dev/null 2>&1 || true
fi

echo "Plain Docker demo stopped."
