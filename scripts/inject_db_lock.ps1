$ErrorActionPreference = "Stop"

$Network = if ($env:TRAINING_DOCKER_NETWORK) { $env:TRAINING_DOCKER_NETWORK } else { "agent-education-net" }
$LockContainer = if ($env:LOCK_CONTAINER_NAME) { $env:LOCK_CONTAINER_NAME } else { "agent-education-lock-injector" }
$FaultImage = if ($env:FAULT_IMAGE_NAME) { $env:FAULT_IMAGE_NAME } else { "agent-education-fault-injector" }

function Invoke-DockerBestEffort {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "SilentlyContinue"
        & docker @Arguments *> $null
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }

    return ($exitCode -eq 0)
}

[void](Invoke-DockerBestEffort @("rm", "-f", $LockContainer))

Write-Host "Starting PostgreSQL lock injector..."
& docker run -d `
    --name $LockContainer `
    --network $Network `
    -e DB_HOST=postgres `
    -e DB_PORT=5432 `
    -e DB_NAME=memberdb `
    -e DB_USER=fault_injector `
    -e DB_PASSWORD=fault_injector `
    -e DB_APPLICATION_NAME=fault-locker `
    $FaultImage `
    python -u /app/hold_table_lock.py | Out-Null

if ($LASTEXITCODE -ne 0) {
    throw "Failed to start the lock injector container."
}

$faultActive = $false
for ($i = 0; $i -lt 30; $i++) {
    $logs = (& docker logs $LockContainer 2>&1) -join "`n"
    if ($logs -match "Fault active:") {
        $faultActive = $true
        break
    }

    $running = (& docker inspect -f "{{.State.Running}}" $LockContainer) -join ""
    if ($LASTEXITCODE -ne 0 -or $running -ne "true") {
        Write-Host "Lock injector exited unexpectedly:" -ForegroundColor Red
        & docker logs $LockContainer
        exit 1
    }

    Start-Sleep -Seconds 1
}

if (-not $faultActive) {
    throw "Lock injector did not report an active fault within 30 seconds."
}

Write-Host "DB lock fault injected."
Write-Host "Injector logs: docker logs $LockContainer"
Write-Host "Expected symptom: /api/members times out while all service containers stay running."
