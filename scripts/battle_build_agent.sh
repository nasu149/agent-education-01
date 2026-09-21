#!/usr/bin/env bash
set -euo pipefail

TEAM_ID="${1:-}"

if [[ -z "$TEAM_ID" ]]; then
  echo "Usage: $0 <team-id>" >&2
  echo "Example: $0 team-a" >&2
  exit 2
fi

if [[ ! "$TEAM_ID" =~ ^[a-zA-Z0-9._-]+$ ]]; then
  echo "team-id may contain only letters, numbers, dot, underscore and hyphen." >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="agent-education-agent:$TEAM_ID"

cd "$ROOT_DIR"

echo "==> Building $IMAGE from this team's current source"
docker build -t "$IMAGE" ./agent

echo
echo "Built: $IMAGE"
echo "Instructor can start it with:"
echo "  ./scripts/battle_start_agent.sh $TEAM_ID"
