param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("tomcat-stop","postgres-stop","db-connections","disk-full","proxy-port","db-password")]
    [string]$Fault
)

$ErrorActionPreference = "Stop"
$HttpdContainer = "agent-education-httpd"
$TomcatContainer = "agent-education-tomcat"
$PostgresContainer = "agent-education-postgres"

switch ($Fault) {
    "tomcat-stop" {
        docker stop $TomcatContainer | Out-Null
    }
    "postgres-stop" {
        docker stop $PostgresContainer | Out-Null
    }
    "db-connections" {
        & (Join-Path $PSScriptRoot "inject_db_connection_exhaustion.ps1")
    }
    "disk-full" {
        & (Join-Path $PSScriptRoot "inject_disk_full.ps1")
    }
    "proxy-port" {
        docker exec $HttpdContainer sh -c "sed -i 's/tomcat:8080/tomcat:18080/g' /usr/local/apache2/conf/extra/member-app.conf && httpd -k graceful"
    }
    "db-password" {
        docker exec $PostgresContainer psql -U postgres -d memberdb -c "ALTER USER memberapp WITH PASSWORD 'broken-training-password';" | Out-Null
    }
}

if ($LASTEXITCODE -ne 0) {
    throw "Failed to inject battle fault: $Fault"
}

Write-Host "Injected battle fault: $Fault"
