#!/usr/bin/env bash
set -euo pipefail

NETWORK="${TRAINING_DOCKER_NETWORK:-agent-education-net}"
LOCK_CONTAINER="${LOCK_CONTAINER_NAME:-agent-education-lock-injector}"
FAULT_IMAGE="${FAULT_IMAGE_NAME:-agent-education-fault-injector}"

docker rm -f "$LOCK_CONTAINER" >/dev/null 2>&1 || true

echo "Starting PostgreSQL lock injector..."
docker run -d \
  --name "$LOCK_CONTAINER" \
  --network "$NETWORK" \
  -e DB_HOST=postgres \
  -e DB_PORT=5432 \
  -e DB_NAME=memberdb \
  -e DB_USER=fault_injector \
  -e DB_PASSWORD=fault_injector \
  -e DB_APPLICATION_NAME=fault-locker \
  "$FAULT_IMAGE" \
  python -u /app/hold_table_lock.py \
  >/dev/null

for _ in $(seq 1 30); do
  if docker logs "$LOCK_CONTAINER" 2>&1 | grep -q "Fault active:"; then
    echo "DB lock fault injected."
    echo "Injector logs: docker logs $LOCK_CONTAINER"
    echo "Expected symptom: /api/members times out while all service containers stay running."
    exit 0
  fi
  if ! docker inspect -f '{{.State.Running}}' "$LOCK_CONTAINER" 2>/dev/null | grep -q true; then
    echo "Lock injector exited unexpectedly:" >&2
    docker logs "$LOCK_CONTAINER" >&2 || true
    exit 1
  fi
  sleep 1
done

echo "Lock injector did not become active." >&2
docker logs "$LOCK_CONTAINER" >&2 || true
exit 1
