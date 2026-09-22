$ErrorActionPreference = "Stop"

$AgentContainer = "agent-education-agent"
$FaultContainer = "agent-education-fault-injector"
$HttpdContainer = "agent-education-httpd"
$TomcatContainer = "agent-education-tomcat"
$PostgresContainer = "agent-education-postgres"

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

Write-Host "==> Stopping current Agent so it cannot interfere with reset"
[void](Invoke-DockerBestEffort @("rm", "-f", $AgentContainer))

Write-Host "==> Removing fault injector"
[void](Invoke-DockerBestEffort @("rm", "-f", $FaultContainer))

Write-Host "==> Restoring service containers"
foreach ($container in @($PostgresContainer, $TomcatContainer, $HttpdContainer)) {
    if (-not (Invoke-DockerBestEffort @("inspect", $container))) {
        throw "Required container is missing: $container. Recreate the shared system with scripts\pure_docker_up.ps1."
    }
    [void](Invoke-DockerBestEffort @("start", $container))
}

Write-Host "==> Waiting for PostgreSQL"
$postgresReady = $false
for ($i = 0; $i -lt 30; $i++) {
    if (Invoke-DockerBestEffort @("exec", $PostgresContainer, "pg_isready", "-U", "postgres", "-d", "memberdb")) {
        $postgresReady = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $postgresReady) {
    throw "PostgreSQL did not become ready during reset."
}

Write-Host "==> Removing disk-full training archives"
if (Invoke-DockerBestEffort @("exec", $TomcatContainer, "test", "-d", "/training-disk")) {
    & docker exec $TomcatContainer sh -c "rm -f /training-disk/archive/training-*.log 2>/dev/null || true"
}

Write-Host "==> Restoring DB password"
& docker exec $PostgresContainer psql -U postgres -d memberdb -c "ALTER USER memberapp WITH PASSWORD 'memberapp';" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Failed to restore memberapp password." }

Write-Host "==> Restoring httpd proxy destination"
& docker exec $HttpdContainer sh -c "sed -i 's/tomcat:18080/tomcat:8080/g' /usr/local/apache2/conf/extra/member-app.conf && httpd -k graceful"
if ($LASTEXITCODE -ne 0) { throw "Failed to restore httpd proxy destination." }

Write-Host "==> Waiting for application HTTP 200"
$healthy = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8088/api/members" -TimeoutSec 3
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            break
        }
    } catch {
        # Expected while services recover.
    }
    Start-Sleep -Seconds 1
}

if (-not $healthy) {
    throw "Application did not recover to HTTP 200. Inspect Tomcat/PostgreSQL logs or rebuild with scripts\pure_docker_up.ps1."
}

Write-Host "Battle environment is clean and healthy."
