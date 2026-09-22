#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NETWORK="${TRAINING_DOCKER_NETWORK:-agent-education-net}"
VOLUME="${TRAINING_POSTGRES_VOLUME:-agent-education-postgres-data}"
POSTGRES_CONTAINER="${TARGET_POSTGRES_CONTAINER:-agent-education-postgres}"
TRAINING_DISK_SIZE="${TRAINING_DB_DISK_SIZE:-32m}"

cd "$ROOT_DIR"

if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
  echo "Docker network not found: $NETWORK" >&2
  echo "Start the previous-day training system first." >&2
  exit 1
fi

if ! docker volume inspect "$VOLUME" >/dev/null 2>&1; then
  echo "PostgreSQL volume not found: $VOLUME" >&2
  exit 1
fi

if ! docker image inspect agent-education-postgres >/dev/null 2>&1; then
  echo "PostgreSQL image not found: agent-education-postgres" >&2
  exit 1
fi

echo "==> Removing a previous training tablespace definition if present"
if docker inspect "$POSTGRES_CONTAINER" >/dev/null 2>&1; then
  docker start "$POSTGRES_CONTAINER" >/dev/null 2>&1 || true
  for _ in $(seq 1 20); do
    if docker exec "$POSTGRES_CONTAINER" pg_isready -U postgres -d memberdb >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  docker exec "$POSTGRES_CONTAINER" psql -U postgres -d memberdb -v ON_ERROR_STOP=0 -c "
    DROP TRIGGER IF EXISTS training_member_insert_audit ON members;
    DROP FUNCTION IF EXISTS training_capture_member_insert();
    DROP TABLE IF EXISTS training_write_audit;
  " >/dev/null 2>&1 || true
  docker exec "$POSTGRES_CONTAINER" psql -U postgres -d memberdb -v ON_ERROR_STOP=0     -c "DROP TABLESPACE IF EXISTS training_disk_ts;" >/dev/null 2>&1 || true
fi

echo "==> Recreating only PostgreSQL with a bounded training filesystem"
docker rm -f "$POSTGRES_CONTAINER" >/dev/null 2>&1 || true

docker run -d   --name "$POSTGRES_CONTAINER"   --network "$NETWORK"   --network-alias postgres   -e POSTGRES_DB=memberdb   -e POSTGRES_USER=postgres   -e POSTGRES_PASSWORD=postgres   -e APP_DB_PASSWORD=memberapp   -e FAULT_DB_PASSWORD=fault_injector   -v "$VOLUME:/var/lib/postgresql/data"   --tmpfs "/training-disk:rw,size=$TRAINING_DISK_SIZE,mode=1777"   agent-education-postgres   postgres -c max_connections=20 -c superuser_reserved_connections=3   >/dev/null

echo "==> Waiting for PostgreSQL"
for _ in $(seq 1 40); do
  if docker exec "$POSTGRES_CONTAINER" pg_isready -U postgres -d memberdb >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$POSTGRES_CONTAINER" pg_isready -U postgres -d memberdb >/dev/null

echo "==> Creating training tablespace and DB-side audit trigger"
docker exec "$POSTGRES_CONTAINER" sh -c "
  mkdir -p /training-disk/pgspace /training-disk/archive
  chown postgres:postgres /training-disk/pgspace /training-disk/archive
  chmod 700 /training-disk/pgspace
  chmod 755 /training-disk/archive
"
docker exec -i "$POSTGRES_CONTAINER" psql -U postgres -d memberdb   < postgres/training_disk_setup.sql

echo "==> Verifying the unchanged application can still write"
docker exec "$POSTGRES_CONTAINER" psql -U postgres -d memberdb -Atc   "DELETE FROM members WHERE email='training-preflight@example.local'; TRUNCATE training_write_audit;"   >/dev/null

body_file="$(mktemp)"
trap 'rm -f "$body_file"' EXIT
status=$(curl -sS --max-time 5 -o "$body_file" -w '%{http_code}'   -X POST   -H 'Content-Type: application/json'   -d '{"name":"Training Preflight","department":"training","email":"training-preflight@example.local"}'   http://localhost:8088/api/members || true)

if [[ "$status" != "201" ]]; then
  echo "Synthetic write preflight failed: HTTP $status" >&2
  cat "$body_file" >&2 || true
  exit 1
fi

member_id=$(sed -n 's/.*"id"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$body_file")
if [[ -z "$member_id" ]]; then
  echo "Could not parse member id from preflight response." >&2
  cat "$body_file" >&2
  exit 1
fi

curl -fsS --max-time 5 -X DELETE   "http://localhost:8088/api/members/$member_id" >/dev/null

docker exec "$POSTGRES_CONTAINER" psql -U postgres -d memberdb -Atc   "TRUNCATE training_write_audit;" >/dev/null

echo "PostgreSQL training storage prepared successfully."
echo "Java/Tomcat application image was not rebuilt or modified."
docker exec "$POSTGRES_CONTAINER" df -h /training-disk
