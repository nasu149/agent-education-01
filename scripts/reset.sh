#!/usr/bin/env sh
set -eu
docker compose down -v --remove-orphans
docker compose up -d --build
echo "Environment reset. App: http://localhost:8088  Agent: http://localhost:8090"
