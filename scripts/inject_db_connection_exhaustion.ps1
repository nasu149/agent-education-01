$ErrorActionPreference = "Stop"

$Network = if ($env:TRAINING_DOCKER_NETWORK) { $env:TRAINING_DOCKER_NETWORK } else { "agent-education-net" }
$FaultContainer = if ($env:FAULT_CONTAINER_NAME) { $env:FAULT_CONTAINER_NAME } else { "agent-education-fault-injector" }
$FaultImage = if ($env:FAULT_IMAGE_NAME) { $env:FAULT_IMAGE_NAME } else { "agent-education-fault-injector" }

& docker rm -f $FaultContainer 2>$null | Out-Null

Write-Host "Starting connection-exhaustion injector..."
& docker run -d `
    --name $FaultContainer `
    --network $Network `
    -e DB_HOST=postgres `
    -e DB_PORT=5432 `
    -e DB_NAME=memberdb `
    -e DB_USER=fault_injector `
    -e DB_PASSWORD=fault_injector `
    -e DB_APPLICATION_NAME=fault-injector `
    -e FAULT_MAX_CONNECTIONS=100 `
    $FaultImage | Out-Null

if ($LASTEXITCODE -ne 0) {
    throw "Failed to start the fault injector container."
}

$faultActive = $false
for ($i = 0; $i -lt 40; $i++) {
    $logs = (& docker logs $FaultContainer 2>&1) -join "`n"
    if ($logs -match "Fault active:") {
        $faultActive = $true
        break
    }

    $running = (& docker inspect -f "{{.State.Running}}" $FaultContainer 2>$null) -join ""
    if ($running -ne "true") {
        Write-Error "Fault injector exited unexpectedly:"
        & docker logs $FaultContainer
        exit 1
    }

    Start-Sleep -Seconds 1
}

if (-not $faultActive) {
    throw "Fault injector did not report an active fault within 40 seconds."
}

Write-Host "Connection-exhaustion fault injected."
Write-Host "Injector logs: docker logs $FaultContainer"
Write-Host "The Agent should detect HTTP failures, inspect PostgreSQL, and ask for approval."
