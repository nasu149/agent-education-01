"""MCP server exposing deliberately constrained operations tools.

The tools are low-level enough that the LLM must investigate, but constrained
enough to be safe and understandable in a classroom. The server never exposes a
generic shell, arbitrary file-read capability, or arbitrary SQL execution.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urljoin

import docker
import httpx
import psycopg
from docker.errors import DockerException, NotFound
from mcp.server.fastmcp import FastMCP
from psycopg.rows import dict_row

LOGGER = logging.getLogger("mcp.operations")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
mcp = FastMCP("operations-training-server", log_level=os.getenv("LOG_LEVEL", "INFO"))

PROJECT = os.getenv("TARGET_COMPOSE_PROJECT", "agent-education")
ALLOWED_SERVICES = {
    item.strip()
    for item in os.getenv("TARGET_SERVICES", "httpd,tomcat,postgres").split(",")
    if item.strip()
}
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://httpd").rstrip("/")

CONTAINER_NAMES = {
    "httpd": os.getenv("TARGET_HTTPD_CONTAINER", "agent-education-httpd"),
    "tomcat": os.getenv("TARGET_TOMCAT_CONTAINER", "agent-education-tomcat"),
    "postgres": os.getenv("TARGET_POSTGRES_CONTAINER", "agent-education-postgres"),
}

CONFIG_TARGETS = {
    "httpd_proxy": ("httpd", "/usr/local/apache2/conf/extra/member-app.conf"),
    "tomcat_database": (
        "tomcat",
        "__ENV__:DB_HOST,DB_PORT,DB_NAME,DB_USER",
    ),
}

DB_ADMIN_HOST = os.getenv("DB_ADMIN_HOST", "postgres")
DB_ADMIN_PORT = int(os.getenv("DB_ADMIN_PORT", "5432"))
DB_ADMIN_NAME = os.getenv("DB_ADMIN_NAME", "memberdb")
DB_ADMIN_USER = os.getenv("DB_ADMIN_USER", "postgres")
DB_ADMIN_PASSWORD = os.getenv("DB_ADMIN_PASSWORD", "postgres")
FAULT_DB_USER = os.getenv("FAULT_DB_USER", "fault_injector")
TERMINABLE_DB_APPLICATIONS = {
    item.strip()
    for item in os.getenv("TERMINABLE_DB_APPLICATIONS", "fault-injector").split(",")
    if item.strip()
}


def _client():
    """Create a Docker SDK client through the mounted local Docker socket."""
    return docker.from_env()


def _container_for_service(service: str):
    """Resolve one allow-listed service for Compose or plain ``docker run``.

    Compose containers are discovered by labels. For the real training flow,
    where trainees use plain Docker commands, the MCP server falls back to an
    explicitly configured container name.
    """
    if service not in ALLOWED_SERVICES:
        raise ValueError(f"service must be one of {sorted(ALLOWED_SERVICES)}")

    containers = _client().containers.list(
        all=True,
        filters={
            "label": [
                f"com.docker.compose.project={PROJECT}",
                f"com.docker.compose.service={service}",
            ]
        },
    )
    if containers:
        return containers[0]

    configured_name = CONTAINER_NAMES.get(service)
    if configured_name:
        try:
            return _client().containers.get(configured_name)
        except NotFound:
            pass

    raise NotFound(
        f"container for service '{service}' was not found by Compose labels "
        f"or configured name {configured_name!r}"
    )


def _postgres_connection():
    """Open the private management connection used only by fixed MCP operations.

    The demo intentionally uses the PostgreSQL superuser here so this connection
    can use PostgreSQL's superuser-reserved slots after normal application slots
    are exhausted. The LLM never receives these credentials and never receives
    an arbitrary SQL tool.
    """
    return psycopg.connect(
        host=DB_ADMIN_HOST,
        port=DB_ADMIN_PORT,
        dbname=DB_ADMIN_NAME,
        user=DB_ADMIN_USER,
        password=DB_ADMIN_PASSWORD,
        application_name="incident-agent-mcp",
        connect_timeout=3,
        autocommit=True,
        row_factory=dict_row,
    )


@mcp.tool()
async def http_request(path: str = "/api/members", method: str = "GET") -> dict[str, Any]:
    """Call the training web application and return status plus a short body.

    Use this to observe the application from the same network as the Agent.
    Only GET is allowed because this is an observation tool.
    """
    if method.upper() != "GET":
        raise ValueError("observation tool only permits GET")
    if not path.startswith("/"):
        raise ValueError("path must start with '/'")
    url = urljoin(APP_BASE_URL + "/", path.lstrip("/"))
    LOGGER.info("http_request GET %s", url)
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            response = await client.get(url)
            return {
                "url": url,
                "status_code": response.status_code,
                "body": response.text[:2000],
            }
        except httpx.HTTPError as exc:
            return {"url": url, "error": type(exc).__name__, "detail": str(exc)}


@mcp.tool()
def list_containers() -> list[dict[str, Any]]:
    """List status for the httpd, tomcat and postgres services only."""
    LOGGER.info("list_containers project=%s", PROJECT)
    results: list[dict[str, Any]] = []
    for service in sorted(ALLOWED_SERVICES):
        try:
            container = _container_for_service(service)
            results.append(
                {
                    "service": service,
                    "name": container.name,
                    "status": container.status,
                    "image": container.image.tags[:1],
                }
            )
        except (DockerException, NotFound) as exc:
            results.append({"service": service, "status": "not_found", "detail": str(exc)})
    return results


@mcp.tool()
def inspect_container(service: str) -> dict[str, Any]:
    """Inspect one allowed service and return operationally useful metadata."""
    LOGGER.info("inspect_container service=%s", service)
    container = _container_for_service(service)
    container.reload()
    attrs = container.attrs
    networks = attrs.get("NetworkSettings", {}).get("Networks", {})
    return {
        "service": service,
        "status": attrs.get("State", {}).get("Status"),
        "health": attrs.get("State", {}).get("Health", {}).get("Status", "not-configured"),
        "ports": attrs.get("NetworkSettings", {}).get("Ports", {}),
        "networks": {
            name: {
                "ip_address": value.get("IPAddress"),
                "aliases": value.get("Aliases", []),
            }
            for name, value in networks.items()
        },
        "environment": [
            item
            for item in attrs.get("Config", {}).get("Env", [])
            if item.split("=", 1)[0] in {"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER"}
        ],
    }


@mcp.tool()
def get_container_logs(service: str, tail: int = 80) -> str:
    """Return recent logs for one allowed service.

    `tail` is clamped to 200 so a model cannot accidentally flood its context.
    """
    safe_tail = max(1, min(int(tail), 200))
    LOGGER.info("get_container_logs service=%s tail=%s", service, safe_tail)
    container = _container_for_service(service)
    return container.logs(tail=safe_tail, timestamps=True).decode("utf-8", errors="replace")


@mcp.tool()
def read_config(config_name: str) -> dict[str, Any]:
    """Read one whitelisted configuration view.

    Allowed names are `httpd_proxy` and `tomcat_database`. There is deliberately
    no arbitrary `read_file(path)` tool.
    """
    if config_name not in CONFIG_TARGETS:
        raise ValueError(f"config_name must be one of {sorted(CONFIG_TARGETS)}")
    service, target = CONFIG_TARGETS[config_name]
    container = _container_for_service(service)
    LOGGER.info("read_config config=%s service=%s", config_name, service)

    if target.startswith("__ENV__:"):
        container.reload()
        keys = set(target.removeprefix("__ENV__:").split(","))
        env = {}
        for item in container.attrs.get("Config", {}).get("Env", []):
            key, _, value = item.partition("=")
            if key in keys:
                env[key] = value
        return {"config_name": config_name, "service": service, "values": env}

    exit_code, output = container.exec_run(["cat", target])
    if exit_code != 0:
        return {
            "config_name": config_name,
            "service": service,
            "error": output.decode("utf-8", errors="replace"),
        }
    return {
        "config_name": config_name,
        "service": service,
        "content": output.decode("utf-8", errors="replace"),
    }


@mcp.tool()
def get_postgres_connection_summary() -> dict[str, Any]:
    """Run fixed read-only SELECTs that summarize PostgreSQL connection usage.

    This is intentionally *not* an arbitrary SQL tool. The SQL text is defined
    in the MCP implementation and cannot be supplied by the model. It returns
    max_connections, superuser-reserved slots, and pg_stat_activity grouped by
    database user, application_name, client address and state.
    """
    LOGGER.info("get_postgres_connection_summary")
    with _postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    current_setting('max_connections')::int AS max_connections,
                    current_setting('superuser_reserved_connections')::int
                        AS superuser_reserved_connections
                """
            )
            limits = cur.fetchone() or {}

            cur.execute(
                """
                SELECT
                    COALESCE(datname, '') AS database,
                    COALESCE(usename, '') AS username,
                    COALESCE(application_name, '') AS application_name,
                    COALESCE(client_addr::text, 'local') AS client_addr,
                    COALESCE(state, '') AS state,
                    COUNT(*)::int AS connections
                FROM pg_stat_activity
                WHERE pid <> pg_backend_pid()
                GROUP BY datname, usename, application_name, client_addr, state
                ORDER BY connections DESC, username, application_name, state
                """
            )
            activity = [dict(row) for row in cur.fetchall()]

    max_connections = int(limits.get("max_connections", 0))
    superuser_reserved = int(limits.get("superuser_reserved_connections", 0))
    observed_connections = sum(int(row["connections"]) for row in activity)
    ordinary_capacity = max(0, max_connections - superuser_reserved)

    return {
        "max_connections": max_connections,
        "superuser_reserved_connections": superuser_reserved,
        "ordinary_connection_capacity": ordinary_capacity,
        "observed_connections_excluding_this_mcp_session": observed_connections,
        "activity": activity,
    }


@mcp.tool()
def start_container(service: str) -> dict[str, str]:
    """Start one allowed service after the Graph has obtained human approval."""
    LOGGER.warning("MUTATION start_container service=%s", service)
    container = _container_for_service(service)
    container.start()
    container.reload()
    return {"service": service, "status": container.status, "action": "start"}


@mcp.tool()
def restart_container(service: str) -> dict[str, str]:
    """Restart one allowed service after a human-approved remediation decision."""
    LOGGER.warning("MUTATION restart_container service=%s", service)
    container = _container_for_service(service)
    container.restart(timeout=10)
    container.reload()
    return {"service": service, "status": container.status, "action": "restart"}


@mcp.tool()
def terminate_postgres_connections(application_name: str) -> dict[str, Any]:
    """Terminate only explicitly allow-listed PostgreSQL client sessions.

    This mutation is intended for the Human-in-the-loop remediation node. The
    caller may choose only an application_name from TERMINABLE_DB_APPLICATIONS;
    the SQL itself is fixed and parameterized. The training default allows only
    `fault-injector`, and the query additionally requires the dedicated
    `fault_injector` database role.
    """
    if application_name not in TERMINABLE_DB_APPLICATIONS:
        raise ValueError(
            f"application_name must be one of {sorted(TERMINABLE_DB_APPLICATIONS)}"
        )

    LOGGER.warning(
        "MUTATION terminate_postgres_connections application_name=%s user=%s",
        application_name,
        FAULT_DB_USER,
    )

    with _postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pid
                FROM pg_stat_activity
                WHERE application_name = %s
                  AND usename = %s
                  AND pid <> pg_backend_pid()
                ORDER BY pid
                """,
                (application_name, FAULT_DB_USER),
            )
            target_pids = [int(row["pid"]) for row in cur.fetchall()]

            terminated: list[int] = []
            failed: list[int] = []
            for pid in target_pids:
                cur.execute("SELECT pg_terminate_backend(%s) AS terminated", (pid,))
                row = cur.fetchone() or {}
                if bool(row.get("terminated")):
                    terminated.append(pid)
                else:
                    failed.append(pid)

    return {
        "action": "terminate_postgres_connections",
        "application_name": application_name,
        "database_user": FAULT_DB_USER,
        "matched_sessions": len(target_pids),
        "terminated_sessions": len(terminated),
        "terminated_pids": terminated,
        "failed_pids": failed,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
