$ErrorActionPreference = "Stop"

$AgentContainer = "agent-education-agent"
$FaultContainer = "agent-education-fault-injector"
$HttpdContainer = "agent-education-httpd"
$TomcatContainer = "agent-education-tomcat"
$PostgresContainer = "agent-education-postgres"

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

Write-Host "==> Stopping current Agent so it cannot interfere with reset"
[void](Invoke-DockerBestEffort @("rm", "-f", $AgentContainer))

Write-Host "==> Removing fault injector"
[void](Invoke-DockerBestEffort @("rm", "-f", $FaultContainer))

Write-Host "==> Restoring service containers"
foreach ($container in @($PostgresContainer, $TomcatContainer, $HttpdContainer)) {
    if (-not (Invoke-DockerBestEffort @("inspect", $container))) {
        throw "Required container is missing: $container"
    }
    [void](Invoke-DockerBestEffort @("start", $container))
}

Write-Host "==> Waiting for PostgreSQL"
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    if (Invoke-DockerBestEffort @("exec", $PostgresContainer, "pg_isready", "-U", "postgres", "-d", "memberdb")) {
        $ready = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $ready) { throw "PostgreSQL did not become ready." }

Write-Host "==> Clearing DB disk-full training artifacts"
if (Invoke-DockerBestEffort @("exec", $PostgresContainer, "test", "-d", "/training-disk")) {
    [void](Invoke-DockerBestEffort @("exec", $PostgresContainer, "rm", "-f", "/training-disk/archive/training-overnight-export.bin"))
    & docker exec $PostgresContainer psql -U postgres -d memberdb -v ON_ERROR_STOP=0 -c "TRUNCATE training_write_audit;" *> $null
}

Write-Host "==> Restoring DB password"
& docker exec $PostgresContainer psql -U postgres -d memberdb -c "ALTER USER memberapp WITH PASSWORD 'memberapp';" *> $null
if ($LASTEXITCODE -ne 0) { throw "Failed to restore DB password." }

Write-Host "==> Restoring httpd proxy destination"
& docker exec $HttpdContainer sh -c "sed -i 's/tomcat:18080/tomcat:8080/g' /usr/local/apache2/conf/extra/member-app.conf && httpd -k graceful"
if ($LASTEXITCODE -ne 0) { throw "Failed to restore httpd proxy destination." }

Write-Host "==> Waiting for application read path"
$readHealthy = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8088/api/members" -TimeoutSec 3
        if ($r.StatusCode -eq 200) {
            $readHealthy = $true
            break
        }
    }
    catch {
    }
    Start-Sleep -Seconds 1
}
if (-not $readHealthy) { throw "Application read path did not recover." }

Write-Host "==> Verifying application write path"
& docker exec $PostgresContainer psql -U postgres -d memberdb -Atc "DELETE FROM members WHERE email='battle-reset-check@example.local';" *> $null

$payload = @{
    name = "Battle Reset Check"
    department = "training"
    email = "battle-reset-check@example.local"
} | ConvertTo-Json -Compress

$created = Invoke-RestMethod -Method Post -Uri "http://localhost:8088/api/members" -ContentType "application/json" -Body $payload -TimeoutSec 5
if (-not $created.id) { throw "Write path did not return a member id." }

Invoke-RestMethod -Method Delete -Uri "http://localhost:8088/api/members/$($created.id)" -TimeoutSec 5 | Out-Null
Write-Host "Battle environment is clean and healthy."
