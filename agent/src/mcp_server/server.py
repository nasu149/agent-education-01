"""操作範囲を限定した、運用研修用のツールを公開する MCP サーバー。

LLM が観測結果を組み合わせて原因を調査できるよう、個々のツールは基本的な
操作に分けている。一方で、授業で安全に扱い、動作を理解できるように対象を
限定する。汎用シェル、任意のファイルの読み取り、任意の SQL 実行は公開しない。
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

TRAINING_DB_DISK_SERVICE = "postgres"
TRAINING_DB_DISK_PATH = os.getenv("TRAINING_DB_DISK_PATH", "/training-disk")
TRAINING_DB_EXPORT_PATH = os.getenv(
    "TRAINING_DB_EXPORT_PATH",
    f"{TRAINING_DB_DISK_PATH}/archive/training-overnight-export.bin",
)


def _client():
    """マウントされたローカルの Docker ソケットに接続する SDK クライアントを作成する。"""
    return docker.from_env()


def _container_for_service(service: str):
    """許可されたサービスに対応するコンテナを、Compose または通常の Docker 環境で探す。

    まず Compose のプロジェクト名とサービス名のラベルで検索する。
    見つからなければ、研修で使う ``docker run`` 環境にも対応するため、
    明示的に設定されたコンテナ名で検索する。
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
    """MCP に実装した固定の操作だけに使う、非公開の管理用 DB 接続を開く。

    この教材では、通常のアプリ用接続枠が枯渇してもスーパーユーザー用の
    予約枠で接続できるよう、意図的に PostgreSQL のスーパーユーザーを使う。
    この認証情報は LLM に渡さず、任意の SQL を実行するツールも公開しない。
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
    """研修用 Web アプリにアクセスし、HTTP ステータスとレスポンス本文の先頭を返す。

    Agent と同じネットワークから、アプリが正常に応答するか確認するときに使う。
    path は '/' で始まるアプリ内のパスを指定する（既定値: '/api/members'）。
    観測専用のため method は GET のみ許可し、本文は最大 2000 文字を返す。
    通信に失敗した場合は、エラーの種類と詳細を返す。
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
    """許可されたサービスのコンテナ名、稼働状態、イメージを一覧で返す。

    障害調査の初めに、停止中または見つからないコンテナがないか確認するときに使う。
    対象は TARGET_SERVICES で許可したサービスのみ（既定値: httpd, tomcat, postgres）。
    """
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
    """許可されたサービスを 1 つ指定し、コンテナの稼働状態や接続設定を詳しく確認する。

    service にサービス名を指定する（既定の許可対象: httpd, tomcat, postgres）。
    稼働状態、ヘルスチェック、ポート、ネットワーク、IP アドレス、別名を返す。
    環境変数は DB_HOST, DB_PORT, DB_NAME, DB_USER のみを返し、パスワードは返さない。
    """
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
    """許可されたサービスの直近ログを取得し、エラーや障害の手掛かりを確認する。

    service にサービス名を指定する（既定の許可対象: httpd, tomcat, postgres）。
    tail は末尾から取得する行数で、既定値は 80。LLM に大量のログを渡さないよう、
    実際の取得行数は 1〜200 行に制限する。ログにはタイムスタンプを付ける。
    """
    safe_tail = max(1, min(int(tail), 200))
    LOGGER.info("get_container_logs service=%s tail=%s", service, safe_tail)
    container = _container_for_service(service)
    return container.logs(tail=safe_tail, timestamps=True).decode("utf-8", errors="replace")


@mcp.tool()
def read_config(config_name: str) -> dict[str, Any]:
    """許可された設定を 1 つ読み取り、プロキシや DB 接続先の設定を確認する。

    config_name は httpd_proxy または tomcat_database のみ指定できる。
    httpd_proxy は httpd のプロキシ設定ファイル、tomcat_database は Tomcat の
    DB_HOST, DB_PORT, DB_NAME, DB_USER を返す。DB パスワードは返さない。
    任意のパスを読み取る read_file(path) のような機能は公開しない。
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
    """固定の読み取り専用 SELECT を実行し、PostgreSQL の接続数と使用状況を調べる。

    DB 接続の枯渇が疑われるときに、接続上限と接続元ごとの使用数を確認する。
    max_connections、スーパーユーザー予約枠、通常接続枠、および
    pg_stat_activity を DB 名、ユーザー、application_name、接続元アドレス、
    状態で集計した結果を返す。この MCP 管理接続自身は集計から除外する。
    SQL は実装内に固定されており、LLM から任意の SQL は指定できない。
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


def _require_training_db_disk_service(service: str):
    if service != TRAINING_DB_DISK_SERVICE:
        raise ValueError(
            f"training DB disk tools only permit service={TRAINING_DB_DISK_SERVICE!r}"
        )
    return _container_for_service(service)


def _training_db_disk_usage(service: str) -> dict[str, Any]:
    container = _require_training_db_disk_service(service)
    exit_code, output = container.exec_run(["df", "-Pk", TRAINING_DB_DISK_PATH])
    text = output.decode("utf-8", errors="replace")
    if exit_code != 0:
        return {
            "service": service,
            "path": TRAINING_DB_DISK_PATH,
            "error": text.strip(),
        }

    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return {
            "service": service,
            "path": TRAINING_DB_DISK_PATH,
            "error": f"unexpected df output: {text!r}",
        }

    fields = lines[-1].split()
    if len(fields) < 6:
        return {
            "service": service,
            "path": TRAINING_DB_DISK_PATH,
            "error": f"unexpected df fields: {lines[-1]!r}",
        }

    return {
        "service": service,
        "path": TRAINING_DB_DISK_PATH,
        "filesystem": fields[0],
        "size_kb": int(fields[1]),
        "used_kb": int(fields[2]),
        "available_kb": int(fields[3]),
        "use_percent": int(fields[4].rstrip("%")),
        "mount_point": fields[5],
    }


@mcp.tool()
def get_postgres_training_disk_usage(service: str = "postgres") -> dict[str, Any]:
    """PostgreSQL の研修用ストレージ /training-disk の容量を確認する。

    TODO E1:
    _training_db_disk_usage(service) を利用して、構造化された使用率を返してください。
    任意 path は受け取らず、対象は postgres 固定です。
    """
    # ===== 模範解答（TODO E1）=====
    LOGGER.info(
        "get_postgres_training_disk_usage service=%s path=%s",
        service,
        TRAINING_DB_DISK_PATH,
    )
    return _training_db_disk_usage(service)

    raise NotImplementedError("TODO E1: get_postgres_training_disk_usage を実装してください")


@mcp.tool()
def list_postgres_training_disk_files(
    service: str = "postgres",
    limit: int = 10,
) -> dict[str, Any]:
    """PostgreSQL の /training-disk 配下で容量を使うファイルを確認する。

    TODO E2:
    /training-disk 配下だけを対象に、大きなファイルをサイズ降順で返してください。

    条件:
    - service は postgres 固定
    - limit は 1〜20 に丸める
    - LLM から任意 path / shell command を受け取らない
    - path と size_kb を返す
    """
    # ===== 模範解答（TODO E2）=====
    container = _require_training_db_disk_service(service)
    safe_limit = max(1, min(int(limit), 20))
    LOGGER.info(
        "list_postgres_training_disk_files service=%s path=%s limit=%s",
        service,
        TRAINING_DB_DISK_PATH,
        safe_limit,
    )

    command = (
        f"find '{TRAINING_DB_DISK_PATH}' -type f -exec du -k {{}} + "
        f"2>/dev/null | sort -nr | head -n {safe_limit}"
    )
    exit_code, output = container.exec_run(["sh", "-c", command])
    text = output.decode("utf-8", errors="replace")

    files: list[dict[str, Any]] = []
    if exit_code == 0:
        for line in text.splitlines():
            size_text, separator, path = line.partition("\t")
            if not separator:
                parts = line.split(maxsplit=1)
                if len(parts) != 2:
                    continue
                size_text, path = parts
            try:
                size_kb = int(size_text)
            except ValueError:
                continue
            files.append({"path": path, "size_kb": size_kb})

    return {
        "service": service,
        "path": TRAINING_DB_DISK_PATH,
        "files": files,
        "command_exit_code": exit_code,
    }

    raise NotImplementedError("TODO E2: list_postgres_training_disk_files を実装してください")


@mcp.tool()
def cleanup_postgres_training_exports(
    service: str = "postgres",
) -> dict[str, Any]:
    """人間の承認後、研修用の異常な overnight export だけを削除する。

    TODO E3:
    DB disk-full 復旧用 mutation Tool を実装してください。

    安全条件:
    - service は postgres 固定
    - 削除対象は TRAINING_DB_EXPORT_PATH の完全一致 1 ファイルだけ
    - pgspace や任意 path を削除しない
    - cleanup 前後の disk usage と削除結果を返す
    """
    # ===== 模範解答（TODO E3）=====
    container = _require_training_db_disk_service(service)
    before = _training_db_disk_usage(service)

    LOGGER.warning(
        "MUTATION cleanup_postgres_training_exports service=%s target=%s",
        service,
        TRAINING_DB_EXPORT_PATH,
    )

    exists_code, _ = container.exec_run(["test", "-f", TRAINING_DB_EXPORT_PATH])
    deleted = False
    if exists_code == 0:
        delete_code, _ = container.exec_run(["rm", "-f", TRAINING_DB_EXPORT_PATH])
        deleted = delete_code == 0

    after = _training_db_disk_usage(service)
    return {
        "action": "cleanup_postgres_training_exports",
        "service": service,
        "target": TRAINING_DB_EXPORT_PATH,
        "deleted": deleted,
        "before": before,
        "after": after,
    }

    raise NotImplementedError("TODO E3: cleanup_postgres_training_exports を実装してください")


@mcp.tool()
def start_container(service: str) -> dict[str, str]:
    """Graph が人間の承認を得た後、許可されたサービスのコンテナを 1 つ起動する。

    service に起動するサービス名を指定する（既定の許可対象: httpd, tomcat, postgres）。
    状態を変更する復旧操作であり、観測用ではない。起動後の稼働状態を返す。
    承認の確認は呼び出し元の Graph が行う。
    """
    LOGGER.warning("MUTATION start_container service=%s", service)
    container = _container_for_service(service)
    container.start()
    container.reload()
    return {"service": service, "status": container.status, "action": "start"}


@mcp.tool()
def restart_container(service: str) -> dict[str, str]:
    """人間が復旧方針を承認した後、許可されたサービスのコンテナを 1 つ再起動する。

    service に再起動するサービス名を指定する（既定の許可対象: httpd, tomcat, postgres）。
    状態を変更する復旧操作であり、観測用ではない。再起動後の稼働状態を返す。
    承認の確認は呼び出し元の Graph が行う。
    """
    LOGGER.warning("MUTATION restart_container service=%s", service)
    container = _container_for_service(service)
    container.restart(timeout=10)
    container.reload()
    return {"service": service, "status": container.status, "action": "restart"}


@mcp.tool()
def terminate_postgres_connections(application_name: str) -> dict[str, Any]:
    """明示的に許可された PostgreSQL のクライアント接続だけを切断する。

    接続枯渇からの復旧に使う状態変更操作で、人間の承認を経た復旧ノードから呼び出す。
    承認の確認は呼び出し元の Graph が行う。
    application_name は TERMINABLE_DB_APPLICATIONS の許可リストからのみ選択できる。
    教材の既定値は fault-injector のみで、さらに DB ユーザーが専用の
    fault_injector（FAULT_DB_USER）に一致する接続に限定する。管理接続自身は除外する。
    SQL は固定され、引数はパラメーターとして渡す。対象件数、切断成功件数、
    切断した PID と切断に失敗した PID を返す。
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
