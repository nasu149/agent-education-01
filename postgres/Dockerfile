FROM postgres:17-alpine

COPY init.sql /docker-entrypoint-initdb.d/01-init.sql
COPY 02-set-role-passwords.sh /docker-entrypoint-initdb.d/02-set-role-passwords.sh
