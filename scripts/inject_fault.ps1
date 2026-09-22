param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("tomcat-stop","postgres-stop","proxy-port","db-password","db-connections","db-lock")]
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
        docker compose exec -T postgres psql -U postgres -d memberdb -c "ALTER USER memberapp WITH PASSWORD 'broken-training-password';"
    }
    "db-connections" {
        docker compose --profile fault up -d --build fault-injector
    }
    "db-lock" {
        docker compose --profile fault up -d --build lock-injector
    }
}

Write-Host "Injected fault: $Fault"
