FROM postgres:17-alpine

COPY init.sql /docker-entrypoint-initdb.d/01-init.sql
COPY 02-set-role-passwords.sh /docker-entrypoint-initdb.d/02-set-role-passwords.sh
COPY training_disk_setup.sql /docker-entrypoint-initdb.d/03-training-disk.sql
COPY 03-setup-training-disk.sh /docker-entrypoint-initdb.d/03-setup-training-disk.sh

# Windows checkout may convert shell scripts to CRLF. Normalize inside the
# image as a second line of defense so PostgreSQL's entrypoint can execute it.
RUN sed -i 's/\r$//' /docker-entrypoint-initdb.d/02-set-role-passwords.sh /docker-entrypoint-initdb.d/03-setup-training-disk.sh \
    && chmod +x /docker-entrypoint-initdb.d/02-set-role-passwords.sh /docker-entrypoint-initdb.d/03-setup-training-disk.sh
