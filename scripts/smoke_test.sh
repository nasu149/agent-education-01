#!/usr/bin/env sh
set -eu
echo "App API:"
curl -fsS http://localhost:8088/api/members
echo
echo "Agent API:"
curl -fsS http://localhost:8090/api/status
echo
