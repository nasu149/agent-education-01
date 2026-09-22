$ErrorActionPreference = "Stop"

$PostgresContainer = if ($env:TARGET_POSTGRES_CONTAINER) { $env:TARGET_POSTGRES_CONTAINER } else { "agent-education-postgres" }
$TrainingDisk = "/training-disk"
$Archive = "$TrainingDisk/archive"
$Filler = "$Archive/training-overnight-export.bin"

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

if (-not (Invoke-DockerBestEffort @("inspect", $PostgresContainer))) {
    throw "PostgreSQL container not found: $PostgresContainer"
}
if (-not (Invoke-DockerBestEffort @("exec", $PostgresContainer, "test", "-d", $TrainingDisk))) {
    throw "$TrainingDisk is not mounted in PostgreSQL. Run .\scripts\prepare_db_disk_full_training.ps1 first."
}

Write-Host "==> Ensuring the training audit table is empty before filling the filesystem"
& docker exec $PostgresContainer psql -U postgres -d memberdb -v ON_ERROR_STOP=1 -c "TRUNCATE training_write_audit;" *> $null
if ($LASTEXITCODE -ne 0) { throw "Failed to truncate training_write_audit." }

Write-Host "==> Disk usage before fault"
& docker exec $PostgresContainer df -h $TrainingDisk

Write-Host "==> Simulating a runaway overnight DB export on the same storage"
$fillScript = @"
mkdir -p '$Archive'
rm -f '$Filler'
dd if=/dev/zero of='$Filler' bs=1M count=128 status=none 2>/dev/null || true
dd if=/dev/zero of='$Filler' bs=1K count=4096 oflag=append conv=notrunc status=none 2>/dev/null || true
dd if=/dev/zero of='$Filler' bs=1 count=16384 oflag=append conv=notrunc status=none 2>/dev/null || true
"@
& docker exec $PostgresContainer sh -c $fillScript
if ($LASTEXITCODE -ne 0) { throw "Failed to inject disk-full data." }

$df = (& docker exec $PostgresContainer df -Pk $TrainingDisk) -join [Environment]::NewLine
$line = ($df -split "\r?\n" | Where-Object { $_ -match "^\S+\s+\d+" } | Select-Object -Last 1)
if (-not $line) { throw "Unexpected df output: $df" }
$fields = $line -split "\s+"
$usePercent = [int]($fields[4].TrimEnd("%"))
Write-Host "Training DB disk usage: $usePercent%"
if ($usePercent -lt 95) { throw "Failed to fill the training DB disk sufficiently." }

Write-Host "==> Confirming reads still work"
$response = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8088/api/members" -TimeoutSec 5
if ($response.StatusCode -ne 200) { throw "Expected GET /api/members to remain readable." }

Write-Host "==> Confirming an existing application write now fails"
& docker exec $PostgresContainer psql -U postgres -d memberdb -Atc "DELETE FROM members WHERE email='disk-full-probe@example.local';" *> $null

$payload = @{
    name = "Disk Full Probe"
    department = "training"
    email = "disk-full-probe@example.local"
} | ConvertTo-Json -Compress

$statusCode = 0
$body = ""
try {
    $result = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "http://localhost:8088/api/members" -ContentType "application/json" -Body $payload -TimeoutSec 5
    $statusCode = [int]$result.StatusCode
    $body = $result.Content
}
catch {
    if ($_.Exception.Response) {
        $statusCode = [int]$_.Exception.Response.StatusCode
    }
    $body = $_.Exception.Message
}

Write-Host "Synthetic write HTTP status: $statusCode"
if ($body) { Write-Host $body }

if ($statusCode -eq 200 -or $statusCode -eq 201) {
    throw "Expected the write path to fail, but it succeeded."
}

Write-Host "DB disk-full fault injected."
Write-Host "GET /api/members remains readable, but POST now fails because the DB-side audit tablespace cannot extend."
