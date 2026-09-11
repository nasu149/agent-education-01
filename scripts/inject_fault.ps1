param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("tomcat-stop","postgres-stop","proxy-port","db-password")]
    [string]$Fault
)

$ErrorActionPreference = "Stop"

switch ($Fault) {
    "tomcat-stop" {
        docker compose stop tomcat
    }
    "postgres-stop" {
        docker compose stop postgres
    }
    "proxy-port" {
        docker compose exec -T httpd sh -c "sed -i 's/tomcat:8080/tomcat:18080/g' /usr/local/apache2/conf/extra/member-app.conf && httpd -k graceful"
    }
    "db-password" {
        docker compose exec -T postgres psql -U memberapp -d memberdb -c "ALTER USER memberapp WITH PASSWORD 'broken-training-password';"
    }
}

Write-Host "Injected fault: $Fault"
