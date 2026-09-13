$ErrorActionPreference = "Stop"

$Network = "agent-education-net"
$Volume = "agent-education-postgres-data"
$Containers = @(
    "agent-education-fault-injector",
    "agent-education-agent",
    "agent-education-httpd",
    "agent-education-tomcat",
    "agent-education-postgres"
)

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

foreach ($container in $Containers) {
    [void](Invoke-DockerBestEffort @("rm", "-f", $container))
}

[void](Invoke-DockerBestEffort @("network", "rm", $Network))

if ($env:KEEP_DB_DATA -ne "1") {
    [void](Invoke-DockerBestEffort @("volume", "rm", $Volume))
}

Write-Host "Plain Docker demo stopped."
