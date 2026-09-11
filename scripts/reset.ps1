$ErrorActionPreference = "Stop"
docker compose down -v --remove-orphans
docker compose up -d --build
Write-Host "Environment reset. App: http://localhost:8088  Agent: http://localhost:8090"
