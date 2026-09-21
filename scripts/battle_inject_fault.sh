#!/usr/bin/env bash
set -euo pipefail

FAULT="${1:-}"
HTTPD_CONTAINER="agent-education-httpd"
TOMCAT_CONTAINER="agent-education-tomcat"
POSTGRES_CONTAINER="agent-education-postgres"

case "$FAULT" in
  tomcat-stop)
    docker stop "$TOMCAT_CONTAINER" >/dev/null
    ;;

  postgres-stop)
    docker stop "$POSTGRES_CONTAINER" >/dev/null
    ;;

  db-connections)
    "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/inject_db_connection_exhaustion.sh"
    ;;

  proxy-port)
    docker exec "$HTTPD_CONTAINER" sh -c \
      "sed -i 's/tomcat:8080/tomcat:18080/g' /usr/local/apache2/conf/extra/member-app.conf && httpd -k graceful"
    ;;

  db-password)
    docker exec "$POSTGRES_CONTAINER" \
      psql -U postgres -d memberdb \
      -c "ALTER USER memberapp WITH PASSWORD 'broken-training-password';" \
      >/dev/null
    ;;

  *)
    echo "Usage: $0 {tomcat-stop|postgres-stop|db-connections|proxy-port|db-password}" >&2
    exit 2
    ;;
esac

echo "Injected battle fault: $FAULT"
