$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
$Network = if ($env:TRAINING_DOCKER_NETWORK) { $env:TRAINING_DOCKER_NETWORK } else { "agent-education-net" }
$Volume = if ($env:TRAINING_POSTGRES_VOLUME) { $env:TRAINING_POSTGRES_VOLUME } else { "agent-education-postgres-data" }
$PostgresContainer = if ($env:TARGET_POSTGRES_CONTAINER) { $env:TARGET_POSTGRES_CONTAINER } else { "agent-education-postgres" }
$TrainingDiskSize = if ($env:TRAINING_DB_DISK_SIZE) { $env:TRAINING_DB_DISK_SIZE } else { "32m" }

function Invoke-Docker {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Invoke-DockerBestEffort {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $old = $ErrorActionPreference
    try {
        $ErrorActionPreference = "SilentlyContinue"
        & docker @Arguments *> $null
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $old
    }
    return ($code -eq 0)
}

Push-Location $RootDir
try {
    if (-not (Invoke-DockerBestEffort @("network", "inspect", $Network))) {
        throw "Docker network not found: $Network. Start the previous-day training system first."
    }
    if (-not (Invoke-DockerBestEffort @("volume", "inspect", $Volume))) {
        throw "PostgreSQL volume not found: $Volume"
    }
    if (-not (Invoke-DockerBestEffort @("image", "inspect", "agent-education-postgres"))) {
        throw "PostgreSQL image not found: agent-education-postgres"
    }

    Write-Host "==> Removing a previous training tablespace definition if present"
    if (Invoke-DockerBestEffort @("inspect", $PostgresContainer)) {
        [void](Invoke-DockerBestEffort @("start", $PostgresContainer))
        for ($i = 0; $i -lt 20; $i++) {
            if (Invoke-DockerBestEffort @("exec", $PostgresContainer, "pg_isready", "-U", "postgres", "-d", "memberdb")) { break }
            Start-Sleep -Seconds 1
        }

        $dropObjects = @"
DROP TRIGGER IF EXISTS training_member_insert_audit ON members;
DROP FUNCTION IF EXISTS training_capture_member_insert();
DROP TABLE IF EXISTS training_write_audit;
"@
        & docker exec $PostgresContainer psql -U postgres -d memberdb -v ON_ERROR_STOP=0 -c $dropObjects *> $null
        & docker exec $PostgresContainer psql -U postgres -d memberdb -v ON_ERROR_STOP=0 -c "DROP TABLESPACE IF EXISTS training_disk_ts;" *> $null
    }

    Write-Host "==> Recreating only PostgreSQL with a bounded training filesystem"
    [void](Invoke-DockerBestEffort @("rm", "-f", $PostgresContainer))

    $volumeArg = "$($Volume):/var/lib/postgresql/data"
    Invoke-Docker @(
        "run", "-d",
        "--name", $PostgresContainer,
        "--network", $Network,
        "--network-alias", "postgres",
        "-e", "POSTGRES_DB=memberdb",
        "-e", "POSTGRES_USER=postgres",
        "-e", "POSTGRES_PASSWORD=postgres",
        "-e", "APP_DB_PASSWORD=memberapp",
        "-e", "FAULT_DB_PASSWORD=fault_injector",
        "-v", $volumeArg,
        "--tmpfs", "/training-disk:rw,size=$TrainingDiskSize,mode=1777",
        "agent-education-postgres",
        "postgres", "-c", "max_connections=20", "-c", "superuser_reserved_connections=3"
    ) | Out-Null

    Write-Host "==> Waiting for PostgreSQL"
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        if (Invoke-DockerBestEffort @("exec", $PostgresContainer, "pg_isready", "-U", "postgres", "-d", "memberdb")) {
            $ready = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) {
        & docker logs $PostgresContainer
        throw "PostgreSQL did not become ready."
    }

    Write-Host "==> Creating training tablespace and DB-side audit trigger"
    Invoke-Docker @(
        "exec", $PostgresContainer, "sh", "-c",
        "mkdir -p /training-disk/pgspace /training-disk/archive && chown postgres:postgres /training-disk/pgspace /training-disk/archive && chmod 700 /training-disk/pgspace && chmod 755 /training-disk/archive"
    )

    Get-Content -Raw "postgres/training_disk_setup.sql" | & docker exec -i $PostgresContainer psql -U postgres -d memberdb
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the training tablespace."
    }

    Write-Host "==> Verifying the unchanged application can still write"
    & docker exec $PostgresContainer psql -U postgres -d memberdb -Atc "DELETE FROM members WHERE email='training-preflight@example.local'; TRUNCATE training_write_audit;" *> $null

    $payload = @{
        name = "Training Preflight"
        department = "training"
        email = "training-preflight@example.local"
    } | ConvertTo-Json -Compress

    $created = Invoke-RestMethod -Method Post -Uri "http://localhost:8088/api/members" -ContentType "application/json" -Body $payload -TimeoutSec 5
    if (-not $created.id) {
        throw "Synthetic write preflight did not return an id."
    }

    Invoke-RestMethod -Method Delete -Uri "http://localhost:8088/api/members/$($created.id)" -TimeoutSec 5 | Out-Null
    & docker exec $PostgresContainer psql -U postgres -d memberdb -Atc "TRUNCATE training_write_audit;" *> $null

    Write-Host "PostgreSQL training storage prepared successfully."
    Write-Host "Java/Tomcat application image was not rebuilt or modified."
    & docker exec $PostgresContainer df -h /training-disk
}
finally {
    Pop-Location
}
