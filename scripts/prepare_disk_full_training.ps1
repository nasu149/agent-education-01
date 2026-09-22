$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
$Network = if ($env:TRAINING_DOCKER_NETWORK) { $env:TRAINING_DOCKER_NETWORK } else { "agent-education-net" }
$TomcatContainer = if ($env:TARGET_TOMCAT_CONTAINER) { $env:TARGET_TOMCAT_CONTAINER } else { "agent-education-tomcat" }
$TrainingDiskSize = if ($env:TRAINING_DISK_SIZE) { $env:TRAINING_DISK_SIZE } else { "16m" }

function Invoke-Docker {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Invoke-DockerBestEffort {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "SilentlyContinue"
        & docker @Arguments *> $null
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    return ($exitCode -eq 0)
}

Push-Location $RootDir
try {
    Write-Host "==> Building the training Tomcat image"
    Invoke-Docker @("build", "-t", "agent-education-tomcat", "./member-app")

    if (-not (Invoke-DockerBestEffort @("network", "inspect", $Network))) {
        throw "Docker network not found: $Network. Start the previous-day training system first."
    }

    Write-Host "==> Recreating only Tomcat with a small dedicated training filesystem"
    [void](Invoke-DockerBestEffort @("rm", "-f", $TomcatContainer))

    Invoke-Docker @(
        "run", "-d",
        "--name", $TomcatContainer,
        "--network", $Network,
        "--network-alias", "tomcat",
        "-e", "DB_HOST=postgres",
        "-e", "DB_PORT=5432",
        "-e", "DB_NAME=memberdb",
        "-e", "DB_USER=memberapp",
        "-e", "DB_PASSWORD=memberapp",
        "-e", "AUDIT_LOG_PATH=/training-disk/audit/member-audit.log",
        "--tmpfs", "/training-disk:rw,size=$TrainingDiskSize,mode=1777",
        "agent-education-tomcat"
    ) | Out-Null

    Write-Host "==> Waiting for the application to recover"
    $healthy = $false
    for ($i = 0; $i -lt 40; $i++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8088/api/members" -TimeoutSec 3
            if ($response.StatusCode -eq 200) {
                $healthy = $true
                break
            }
        } catch {
            # Expected while Tomcat is starting.
        }
        Start-Sleep -Seconds 1
    }

    if (-not $healthy) {
        Write-Host "Tomcat logs:" -ForegroundColor Yellow
        & docker logs $TomcatContainer
        throw "Application did not recover after recreating Tomcat."
    }

    Write-Host "Tomcat recreated successfully."
    Write-Host "Training filesystem: /training-disk ($TrainingDiskSize)"
    & docker exec $TomcatContainer df -h /training-disk
}
finally {
    Pop-Location
}
