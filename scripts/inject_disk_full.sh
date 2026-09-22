#!/usr/bin/env bash
set -euo pipefail

TOMCAT_CONTAINER="${TARGET_TOMCAT_CONTAINER:-agent-education-tomcat}"
TRAINING_DISK="/training-disk"
ARCHIVE_DIR="$TRAINING_DISK/archive"
FILLER="$ARCHIVE_DIR/training-old-audit.log"

if ! docker inspect "$TOMCAT_CONTAINER" >/dev/null 2>&1; then
  echo "Tomcat container not found: $TOMCAT_CONTAINER" >&2
  exit 1
fi

if ! docker exec "$TOMCAT_CONTAINER" test -d "$TRAINING_DISK"; then
  echo "$TRAINING_DISK is not mounted in Tomcat." >&2
  echo "Run ./scripts/prepare_disk_full_training.sh first." >&2
  exit 1
fi

echo "==> Disk usage before fault"
docker exec "$TOMCAT_CONTAINER" df -h "$TRAINING_DISK"

echo "==> Simulating overnight audit-log growth"
docker exec "$TOMCAT_CONTAINER" sh -c "
  mkdir -p '$ARCHIVE_DIR' '$TRAINING_DISK/audit'
  # Fill the current audit file's allocated block so the next request needs
  # another filesystem block instead of using slack space in the existing one.
  dd if=/dev/zero of='$TRAINING_DISK/audit/member-audit.log' bs=4096 count=1 conv=notrunc status=none 2>/dev/null || true

  rm -f '$FILLER'
  # Fill in large chunks first, then progressively smaller chunks so tmpfs
  # has no usable space left for the next audit append.
  dd if=/dev/zero of='$FILLER' bs=1M count=128 status=none 2>/dev/null || true
  dd if=/dev/zero of='$FILLER' bs=1K count=2048 oflag=append conv=notrunc status=none 2>/dev/null || true
  dd if=/dev/zero of='$FILLER' bs=1 count=8192 oflag=append conv=notrunc status=none 2>/dev/null || true
"

usage=$(docker exec "$TOMCAT_CONTAINER" df -Pk "$TRAINING_DISK" | awk 'NR==2 {gsub(/%/, "", $5); print $5}')
echo "Training disk usage: ${usage}%"

if [[ -z "$usage" || "$usage" -lt 95 ]]; then
  echo "Failed to fill the training disk sufficiently." >&2
  docker exec "$TOMCAT_CONTAINER" df -h "$TRAINING_DISK" >&2
  exit 1
fi

echo "==> Confirming the application is affected"
status=$(curl -sS --max-time 5 -o /tmp/disk-full-response.json -w '%{http_code}' \
  http://localhost:8088/api/members || true)
echo "HTTP status after disk-full injection: $status"
cat /tmp/disk-full-response.json 2>/dev/null || true
echo

if [[ "$status" == "200" ]]; then
  echo "Expected application failure, but GET /api/members still returned HTTP 200." >&2
  exit 1
fi

echo "Disk-full fault injected."
echo "All service containers should still be running."
echo "The Agent should inspect Tomcat logs and /training-disk, then request approval to clean old training logs."
