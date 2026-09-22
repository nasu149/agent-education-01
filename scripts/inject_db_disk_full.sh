#!/usr/bin/env bash
set -euo pipefail

POSTGRES_CONTAINER="${TARGET_POSTGRES_CONTAINER:-agent-education-postgres}"
TRAINING_DISK="/training-disk"
ARCHIVE="$TRAINING_DISK/archive"
FILLER="$ARCHIVE/training-overnight-export.bin"

if ! docker inspect "$POSTGRES_CONTAINER" >/dev/null 2>&1; then
  echo "PostgreSQL container not found: $POSTGRES_CONTAINER" >&2
  exit 1
fi

if ! docker exec "$POSTGRES_CONTAINER" test -d "$TRAINING_DISK"; then
  echo "$TRAINING_DISK is not mounted in PostgreSQL." >&2
  echo "Run ./scripts/prepare_db_disk_full_training.sh first." >&2
  exit 1
fi

echo "==> Ensuring the training audit table is empty before filling the filesystem"
docker exec "$POSTGRES_CONTAINER" psql -U postgres -d memberdb -v ON_ERROR_STOP=1   -c "TRUNCATE training_write_audit;" >/dev/null

echo "==> Disk usage before fault"
docker exec "$POSTGRES_CONTAINER" df -h "$TRAINING_DISK"

echo "==> Simulating a runaway overnight DB export on the same storage"
docker exec "$POSTGRES_CONTAINER" sh -c "
  mkdir -p '$ARCHIVE'
  rm -f '$FILLER'
  dd if=/dev/zero of='$FILLER' bs=1M count=128 status=none 2>/dev/null || true
  dd if=/dev/zero of='$FILLER' bs=1K count=4096 oflag=append conv=notrunc status=none 2>/dev/null || true
  dd if=/dev/zero of='$FILLER' bs=1 count=16384 oflag=append conv=notrunc status=none 2>/dev/null || true
"

usage=$(docker exec "$POSTGRES_CONTAINER" df -Pk "$TRAINING_DISK" | awk 'NR==2 {gsub(/%/, "", $5); print $5}')
echo "Training DB disk usage: ${usage}%"

if [[ -z "$usage" || "$usage" -lt 95 ]]; then
  echo "Failed to fill the training DB disk sufficiently." >&2
  docker exec "$POSTGRES_CONTAINER" df -h "$TRAINING_DISK" >&2
  exit 1
fi

echo "==> Confirming reads still work"
curl -fsS --max-time 5 http://localhost:8088/api/members >/dev/null

echo "==> Confirming an existing application write now fails"
docker exec "$POSTGRES_CONTAINER" psql -U postgres -d memberdb -Atc   "DELETE FROM members WHERE email='disk-full-probe@example.local';" >/dev/null

response_file="$(mktemp)"
trap 'rm -f "$response_file"' EXIT
status=$(curl -sS --max-time 5 -o "$response_file" -w '%{http_code}'   -X POST   -H 'Content-Type: application/json'   -d '{"name":"Disk Full Probe","department":"training","email":"disk-full-probe@example.local"}'   http://localhost:8088/api/members || true)

echo "Synthetic write HTTP status: $status"
cat "$response_file" || true
echo

if [[ "$status" == "201" || "$status" == "200" ]]; then
  echo "Expected the write path to fail, but it succeeded." >&2
  exit 1
fi

echo "DB disk-full fault injected."
echo "GET /api/members remains readable, but POST now fails because the DB-side audit tablespace cannot extend."
