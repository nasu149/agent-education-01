#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NETWORK="${TRAINING_DOCKER_NETWORK:-agent-education-net}"
TOMCAT_CONTAINER="${TARGET_TOMCAT_CONTAINER:-agent-education-tomcat}"
TRAINING_DISK_SIZE="${TRAINING_DISK_SIZE:-16m}"

cd "$ROOT_DIR"

echo "==> Building the training Tomcat image"
docker build -t agent-education-tomcat ./member-app

if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
  echo "Docker network not found: $NETWORK" >&2
  echo "Start the previous-day training system first." >&2
  exit 1
fi

echo "==> Recreating only Tomcat with a small dedicated training filesystem"
docker rm -f "$TOMCAT_CONTAINER" >/dev/null 2>&1 || true

docker run -d \
  --name "$TOMCAT_CONTAINER" \
  --network "$NETWORK" \
  --network-alias tomcat \
  -e DB_HOST=postgres \
  -e DB_PORT=5432 \
  -e DB_NAME=memberdb \
  -e DB_USER=memberapp \
  -e DB_PASSWORD=memberapp \
  -e AUDIT_LOG_PATH=/training-disk/audit/member-audit.log \
  --tmpfs "/training-disk:rw,size=$TRAINING_DISK_SIZE,mode=1777" \
  agent-education-tomcat \
  >/dev/null

echo "==> Waiting for the application to recover"
for _ in $(seq 1 40); do
  if curl -fsS http://localhost:8088/api/members >/dev/null 2>&1; then
    echo "Tomcat recreated successfully."
    echo "Training filesystem: /training-disk ($TRAINING_DISK_SIZE)"
    docker exec "$TOMCAT_CONTAINER" df -h /training-disk
    exit 0
  fi
  sleep 1
done

echo "Application did not recover after recreating Tomcat." >&2
docker logs "$TOMCAT_CONTAINER" >&2 || true
exit 1
