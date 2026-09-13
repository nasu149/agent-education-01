"""Open and hold ordinary PostgreSQL sessions until normal slots are exhausted.

This process intentionally uses a non-superuser role. PostgreSQL therefore
stops it before the superuser-reserved slots are consumed, leaving a small
management path for the incident-response MCP server.
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
APPLICATION_NAME = os.getenv("DB_APPLICATION_NAME", "fault-injector")
MAX_CONNECTIONS = int(os.getenv("FAULT_MAX_CONNECTIONS", "100"))
MAX_CONSECUTIVE_FAILURES = int(os.getenv("FAULT_MAX_CONSECUTIVE_FAILURES", "20"))

connections: list[psycopg.Connection] = []
running = True


def _shutdown(signum: int, _frame) -> None:
    global running
    print(f"Received signal {signum}; releasing {len(connections)} held connections.", flush=True)
    running = False


def _close_all() -> None:
    for conn in connections:
        try:
            conn.close()
        except Exception:
            pass


def main() -> int:
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    print(
        f"Connecting to {HOST}:{PORT}/{DBNAME} as {USER} "
        f"with application_name={APPLICATION_NAME!r}",
        flush=True,
    )

    consecutive_failures = 0
    while running and len(connections) < MAX_CONNECTIONS:
        try:
            conn = psycopg.connect(
                host=HOST,
                port=PORT,
                dbname=DBNAME,
                user=USER,
                password=PASSWORD,
                application_name=APPLICATION_NAME,
                connect_timeout=3,
                autocommit=True,
            )
            connections.append(conn)
            consecutive_failures = 0
            if len(connections) == 1 or len(connections) % 5 == 0:
                print(f"Holding {len(connections)} connections.", flush=True)
        except psycopg.OperationalError as exc:
            consecutive_failures += 1
            print(
                f"Connection attempt blocked ({consecutive_failures}/"
                f"{MAX_CONSECUTIVE_FAILURES}): {exc}",
                flush=True,
            )
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                break
            time.sleep(0.25)

    if not connections:
        print("No connections could be opened; fault injection failed.", file=sys.stderr, flush=True)
        return 1

    print(
        f"Fault active: holding {len(connections)} ordinary PostgreSQL sessions. "
        "The injector will not reconnect if an administrator terminates them.",
        flush=True,
    )

    try:
        while running:
            time.sleep(2)
    finally:
        _close_all()
        print("Fault injector stopped.", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
