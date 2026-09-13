#!/usr/bin/env sh
set -eu

: "${APP_DB_PASSWORD:?APP_DB_PASSWORD is required}"
: "${FAULT_DB_PASSWORD:?FAULT_DB_PASSWORD is required}"

psql \
  --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=app_password="$APP_DB_PASSWORD" \
  --set=fault_password="$FAULT_DB_PASSWORD" <<'EOSQL'
ALTER ROLE memberapp PASSWORD :'app_password';
ALTER ROLE fault_injector PASSWORD :'fault_password';
EOSQL
