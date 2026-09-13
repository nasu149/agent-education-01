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

foreach ($container in $Containers) {
    & docker rm -f $container 2>$null | Out-Null
}

& docker network rm $Network 2>$null | Out-Null

if ($env:KEEP_DB_DATA -ne "1") {
    & docker volume rm $Volume 2>$null | Out-Null
}

Write-Host "Plain Docker demo stopped."
