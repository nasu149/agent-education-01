"""Hold a PostgreSQL table lock to create a deterministic blocking incident.

The injector uses the dedicated non-superuser training role and acquires an
ACCESS EXCLUSIVE lock on the members table inside one transaction. Normal
application SELECT statements then wait while PostgreSQL itself remains healthy.

If an administrator terminates this backend, PostgreSQL rolls the transaction
back and releases the lock. This process intentionally does not reconnect, so
one approved remediation is enough to recover the application.
"""

from __future__ import annotations

import os
import signal
import sys
import time

import psycopg

HOST = os.getenv("DB_HOST", "postgres")
PORT = int(os.getenv("DB_PORT", "5432"))
DBNAME = os.getenv("DB_NAME", "memberdb")
USER = os.getenv("DB_USER", "fault_injector")
PASSWORD = os.getenv("DB_PASSWORD", "")
APPLICATION_NAME = os.getenv("DB_APPLICATION_NAME", "fault-locker")

running = True
connection: psycopg.Connection | None = None


def _shutdown(signum: int, _frame) -> None:
    global running
    print(f"Received signal {signum}; stopping lock injector.", flush=True)
    running = False


def main() -> int:
    global connection

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    print(
        f"Connecting to {HOST}:{PORT}/{DBNAME} as {USER} "
        f"with application_name={APPLICATION_NAME!r}",
        flush=True,
    )

    try:
        connection = psycopg.connect(
            host=HOST,
            port=PORT,
            dbname=DBNAME,
            user=USER,
            password=PASSWORD,
            application_name=APPLICATION_NAME,
            connect_timeout=3,
            autocommit=False,
        )
        with connection.cursor() as cur:
            cur.execute("LOCK TABLE members IN ACCESS EXCLUSIVE MODE")

        print(
            "Fault active: ACCESS EXCLUSIVE lock held on members table. "
            "The injector will not reconnect if an administrator terminates this session.",
            flush=True,
        )

        while running:
            time.sleep(2)

    except psycopg.Error as exc:
        print(f"Lock injection failed: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
            try:
                connection.close()
            except Exception:
                pass
        print("Lock injector stopped.", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
