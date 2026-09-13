$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
$Network = "agent-education-net"
$Volume = "agent-education-postgres-data"
$PostgresContainer = "agent-education-postgres"
$TomcatContainer = "agent-education-tomcat"
$HttpdContainer = "agent-education-httpd"
$AgentContainer = "agent-education-agent"
$FaultContainer = "agent-education-fault-injector"

if ([string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY)) {
    throw "GEMINI_API_KEY is required. Example: `$env:GEMINI_API_KEY='...'"
}

function Invoke-Docker {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

# Windows PowerShell can convert stderr from native commands into a
# NativeCommandError when ErrorActionPreference is Stop. Some Docker commands
# below are intentionally allowed to fail (for example removing a container
# that does not exist yet, or pg_isready while PostgreSQL is still starting).
# Run those commands with errors suppressed and return only success/failure.
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

$GeminiModel = if ($env:GEMINI_MODEL) { $env:GEMINI_MODEL } else { "gemini-3.5-flash-lite" }
if ($GeminiModel -eq "gemini-2.5-flash-lite") {
    Write-Warning "GEMINI_MODEL=gemini-2.5-flash-lite is no longer available to new users. Using gemini-3.5-flash-lite instead."
    $GeminiModel = "gemini-3.5-flash-lite"
}
$LangGraphPrintMode = if ($env:LANGGRAPH_PRINT_MODE) { $env:LANGGRAPH_PRINT_MODE } else { "updates" }
Write-Host "==> Gemini model: $GeminiModel"
Write-Host "==> LangGraph console print mode: $LangGraphPrintMode"

$HealthCheckInterval = if ($env:HEALTH_CHECK_INTERVAL_SECONDS) { $env:HEALTH_CHECK_INTERVAL_SECONDS } else { "5" }
$MonitorStartupGrace = if ($env:MONITOR_STARTUP_GRACE_SECONDS) { $env:MONITOR_STARTUP_GRACE_SECONDS } else { "20" }
$FailureThreshold = if ($env:FAILURE_THRESHOLD) { $env:FAILURE_THRESHOLD } else { "2" }
$MaxInvestigationToolResults = if ($env:MAX_INVESTIGATION_TOOL_RESULTS) { $env:MAX_INVESTIGATION_TOOL_RESULTS } else { "8" }
$VerifyRetryLimit = if ($env:VERIFY_RETRY_LIMIT) { $env:VERIFY_RETRY_LIMIT } else { "1" }
$LogLevel = if ($env:LOG_LEVEL) { $env:LOG_LEVEL } else { "INFO" }

Push-Location $RootDir
try {
    foreach ($container in @($FaultContainer, $AgentContainer, $HttpdContainer, $TomcatContainer, $PostgresContainer)) {
        [void](Invoke-DockerBestEffort @("rm", "-f", $container))
    }

    [void](Invoke-DockerBestEffort @("network", "rm", $Network))
    if ($env:RESET_DB_DATA -ne "0") {
        [void](Invoke-DockerBestEffort @("volume", "rm", $Volume))
    }

    Write-Host "==> Building training images"
    Invoke-Docker @("build", "-t", "agent-education-postgres", "./postgres")
    Invoke-Docker @("build", "-t", "agent-education-tomcat", "./member-app")
    Invoke-Docker @("build", "-t", "agent-education-httpd", "./httpd")
    Invoke-Docker @("build", "-t", "agent-education-agent", "./agent")
    Invoke-Docker @("build", "-t", "agent-education-fault-injector", "./fault-injector")

    Write-Host "==> Creating network and database volume"
    Invoke-Docker @("network", "create", $Network)
    Invoke-Docker @("volume", "create", $Volume)

    Write-Host "==> Starting PostgreSQL"
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
        "-v", "${Volume}:/var/lib/postgresql/data",
        "agent-education-postgres",
        "postgres", "-c", "max_connections=20", "-c", "superuser_reserved_connections=3"
    ) | Out-Null

    $postgresReady = $false
    for ($i = 0; $i -lt 40; $i++) {
        if (Invoke-DockerBestEffort @("exec", $PostgresContainer, "pg_isready", "-U", "postgres", "-d", "memberdb")) {
            $postgresReady = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $postgresReady) {
        Write-Host "PostgreSQL logs:" -ForegroundColor Yellow
        & docker logs $PostgresContainer
        throw "PostgreSQL did not become ready within 40 seconds."
    }

    Write-Host "==> Starting Tomcat"
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
        "agent-education-tomcat"
    ) | Out-Null

    Write-Host "==> Starting httpd"
    Invoke-Docker @(
        "run", "-d",
        "--name", $HttpdContainer,
        "--network", $Network,
        "--network-alias", "httpd",
        "-p", "8088:80",
        "agent-education-httpd"
    ) | Out-Null

    Write-Host "==> Starting incident-response Agent"
    Invoke-Docker @(
        "run", "-d",
        "--name", $AgentContainer,
        "--network", $Network,
        "--network-alias", "agent",
        "-p", "8090:8090",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "-e", "GEMINI_API_KEY=$($env:GEMINI_API_KEY)",
        "-e", "GEMINI_MODEL=$GeminiModel",
        "-e", "LANGGRAPH_PRINT_MODE=$LangGraphPrintMode",
        "-e", "APP_BASE_URL=http://httpd",
        "-e", "TARGET_SERVICES=httpd,tomcat,postgres",
        "-e", "TARGET_HTTPD_CONTAINER=$HttpdContainer",
        "-e", "TARGET_TOMCAT_CONTAINER=$TomcatContainer",
        "-e", "TARGET_POSTGRES_CONTAINER=$PostgresContainer",
        "-e", "DB_ADMIN_HOST=postgres",
        "-e", "DB_ADMIN_PORT=5432",
        "-e", "DB_ADMIN_NAME=memberdb",
        "-e", "DB_ADMIN_USER=postgres",
        "-e", "DB_ADMIN_PASSWORD=postgres",
        "-e", "TERMINABLE_DB_APPLICATIONS=fault-injector",
        "-e", "FAULT_DB_USER=fault_injector",
        "-e", "HEALTH_CHECK_INTERVAL_SECONDS=$HealthCheckInterval",
        "-e", "MONITOR_STARTUP_GRACE_SECONDS=$MonitorStartupGrace",
        "-e", "FAILURE_THRESHOLD=$FailureThreshold",
        "-e", "MAX_INVESTIGATION_TOOL_RESULTS=$MaxInvestigationToolResults",
        "-e", "VERIFY_RETRY_LIMIT=$VerifyRetryLimit",
        "-e", "LOG_LEVEL=$LogLevel",
        "agent-education-agent"
    ) | Out-Null

    Write-Host ""
    Write-Host "Started with plain Docker commands only."
    Write-Host "Application: http://localhost:8088"
    Write-Host "Agent UI:    http://localhost:8090"
    Write-Host ""
    Write-Host "Agent log / LangGraph State updates:"
    Write-Host "  docker logs -f agent-education-agent"
    Write-Host ""
    Write-Host "Inject the incident with:"
    Write-Host "  .\scripts\inject_db_connection_exhaustion.ps1"
}
finally {
    Pop-Location
}