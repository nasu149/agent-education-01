$ErrorActionPreference = "Stop"

$TomcatContainer = if ($env:TARGET_TOMCAT_CONTAINER) { $env:TARGET_TOMCAT_CONTAINER } else { "agent-education-tomcat" }
$TrainingDisk = "/training-disk"
$ArchiveDir = "$TrainingDisk/archive"
$Filler = "$ArchiveDir/training-old-audit.log"

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

if (-not (Invoke-DockerBestEffort @("inspect", $TomcatContainer))) {
    throw "Tomcat container not found: $TomcatContainer"
}

if (-not (Invoke-DockerBestEffort @("exec", $TomcatContainer, "test", "-d", $TrainingDisk))) {
    throw "$TrainingDisk is not mounted in Tomcat. Run .\scripts\prepare_disk_full_training.ps1 first."
}

Write-Host "==> Disk usage before fault"
& docker exec $TomcatContainer df -h $TrainingDisk

Write-Host "==> Simulating overnight audit-log growth"
$fillScript = @"
mkdir -p '$ArchiveDir' '$TrainingDisk/audit'
dd if=/dev/zero of='$TrainingDisk/audit/member-audit.log' bs=4096 count=1 conv=notrunc status=none 2>/dev/null || true
rm -f '$Filler'
dd if=/dev/zero of='$Filler' bs=1M count=128 status=none 2>/dev/null || true
dd if=/dev/zero of='$Filler' bs=1K count=2048 oflag=append conv=notrunc status=none 2>/dev/null || true
dd if=/dev/zero of='$Filler' bs=1 count=8192 oflag=append conv=notrunc status=none 2>/dev/null || true
"@
& docker exec $TomcatContainer sh -c $fillScript
if ($LASTEXITCODE -ne 0) {
    throw "Failed to inject disk-full data."
}

$usageText = (& docker exec $TomcatContainer df -Pk $TrainingDisk) -join "`n"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to read training disk usage."
}
$usageLine = ($usageText -split "`r?`n" | Where-Object { $_ -match "^\S+\s+\d+" } | Select-Object -Last 1)
if (-not $usageLine) {
    throw "Unexpected df output: $usageText"
}
$fields = $usageLine -split "\s+"
$usePercent = [int]($fields[4].TrimEnd("%"))
Write-Host "Training disk usage: $usePercent%"
if ($usePercent -lt 95) {
    & docker exec $TomcatContainer df -h $TrainingDisk
    throw "Failed to fill the training disk sufficiently."
}

Write-Host "==> Confirming the application is affected"
$statusCode = 0
$body = ""
try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8088/api/members" -TimeoutSec 5
    $statusCode = [int]$response.StatusCode
    $body = $response.Content
} catch {
    if ($_.Exception.Response) {
        $statusCode = [int]$_.Exception.Response.StatusCode
        try {
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $body = $reader.ReadToEnd()
            $reader.Dispose()
        } catch {
            $body = $_.Exception.Message
        }
    } else {
        $body = $_.Exception.Message
    }
}

Write-Host "HTTP status after disk-full injection: $statusCode"
if ($body) { Write-Host $body }
if ($statusCode -eq 200) {
    throw "Expected application failure, but GET /api/members still returned HTTP 200."
}

Write-Host "Disk-full fault injected."
Write-Host "All service containers should still be running."
Write-Host "The Agent should inspect Tomcat logs and /training-disk, then request approval to clean old training logs."
