param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("tomcat-stop","postgres-stop","proxy-port","db-password","db-connections","disk-full")]
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
    "db-connections" {
        docker compose --profile fault up -d --build fault-injector
    }
    "disk-full" {
        docker compose exec -T tomcat sh -c @'
mkdir -p /training-disk/archive /training-disk/audit
dd if=/dev/zero of=/training-disk/audit/member-audit.log bs=4096 count=1 conv=notrunc status=none 2>/dev/null || true
rm -f /training-disk/archive/training-old-audit.log
dd if=/dev/zero of=/training-disk/archive/training-old-audit.log bs=1M count=128 status=none 2>/dev/null || true
dd if=/dev/zero of=/training-disk/archive/training-old-audit.log bs=1K count=2048 oflag=append conv=notrunc status=none 2>/dev/null || true
dd if=/dev/zero of=/training-disk/archive/training-old-audit.log bs=1 count=8192 oflag=append conv=notrunc status=none 2>/dev/null || true
'@
    }
}

Write-Host "Injected fault: $Fault"
