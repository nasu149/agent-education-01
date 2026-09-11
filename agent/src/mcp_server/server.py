"""MCP server exposing deliberately constrained operations tools.

The tools are low-level enough that the LLM must investigate, but constrained
enough to be safe and understandable in a classroom. The server never exposes a
generic shell or arbitrary file-read capability.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urljoin

import docker
import httpx
from docker.errors import DockerException, NotFound
from mcp.server.fastmcp import FastMCP

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

CONFIG_TARGETS = {
    "httpd_proxy": ("httpd", "/usr/local/apache2/conf/extra/member-app.conf"),
    "tomcat_database": (
        "tomcat",
        "__ENV__:DB_HOST,DB_PORT,DB_NAME,DB_USER",
    ),
}


def _client():
    """Create a Docker SDK client through the mounted local Docker socket."""
    return docker.from_env()


def _container_for_service(service: str):
    """Resolve one allow-listed Compose service to its current container."""
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
    if not containers:
        raise NotFound(f"container for service '{service}' was not found")
    return containers[0]


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


if __name__ == "__main__":
    mcp.run(transport="stdio")
