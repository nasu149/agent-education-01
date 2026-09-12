#!/usr/bin/env bash
set -euo pipefail

NETWORK="${TRAINING_DOCKER_NETWORK:-agent-education-net}"
FAULT_CONTAINER="${FAULT_CONTAINER_NAME:-agent-education-fault-injector}"
FAULT_IMAGE="${FAULT_IMAGE_NAME:-agent-education-fault-injector}"

docker rm -f "$FAULT_CONTAINER" >/dev/null 2>&1 || true

echo "Starting connection-exhaustion injector..."
docker run -d \
  --name "$FAULT_CONTAINER" \
  --network "$NETWORK" \
  -e DB_HOST=postgres \
  -e DB_PORT=5432 \
  -e DB_NAME=memberdb \
  -e DB_USER=fault_injector \
  -e DB_PASSWORD=unused-in-training-trust-mode \
  -e DB_APPLICATION_NAME=fault-injector \
  -e FAULT_MAX_CONNECTIONS=100 \
  "$FAULT_IMAGE" \
  >/dev/null

for _ in $(seq 1 40); do
  if docker logs "$FAULT_CONTAINER" 2>&1 | grep -q "Fault active:"; then
    break
  fi
  if ! docker inspect -f '{{.State.Running}}' "$FAULT_CONTAINER" 2>/dev/null | grep -q true; then
    echo "Fault injector exited unexpectedly:" >&2
    docker logs "$FAULT_CONTAINER" >&2 || true
    exit 1
  fi
  sleep 1
done

echo "Connection-exhaustion fault injected."
echo "Injector logs: docker logs $FAULT_CONTAINER"
echo "The Agent should detect HTTP failures, inspect PostgreSQL, and ask for approval."
