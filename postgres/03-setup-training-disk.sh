#!/usr/bin/env sh
set -eu

TRAINING_DISK_PATH="${TRAINING_DISK_PATH:-/training-disk}"
PGSPACE="$TRAINING_DISK_PATH/pgspace"
ARCHIVE="$TRAINING_DISK_PATH/archive"

mkdir -p "$PGSPACE" "$ARCHIVE"
chmod 700 "$PGSPACE"
chmod 755 "$ARCHIVE"

psql \
  --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --file /docker-entrypoint-initdb.d/03-training-disk.sql
