"""MCP サーバーからツールを取得し、観測用と状態変更用に分ける。

LLM には観測用だけを渡し、状態変更用は人間の承認後に決められた処理から呼び出す。
プロンプトによる注意書きだけに頼らず、渡すツール自体を分けることで権限を限定する。
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
from dataclasses import dataclass

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient


READ_ONLY_TOOL_NAMES = {
    "http_request",
    "list_containers",
    "inspect_container",
    "get_container_logs",
    "read_config",
    "get_postgres_connection_summary",
    "get_disk_usage",
    "list_large_files",
}
MUTATING_TOOL_NAMES = {
    "start_container",
    "restart_container",
    "terminate_postgres_connections",
    "cleanup_training_logs",
}


@dataclass
class ToolCatalog:
    """用途と権限に応じて分類した、MCP ツールの受け渡し用データ。

    read_only は LLM が選択できる観測ツールのリスト。
    mutating はツール名をキーにした復旧ツールの辞書で、承認後の remediate ノードが
    使用する。このクラス自体が承認を判定するのではなく、呼び出し元が分離を守る。
    """

    read_only: list[BaseTool]
    mutating: dict[str, BaseTool]


def _mcp_subprocess_environment() -> tuple[str, dict[str, str]]:
    """MCP サーバーの子プロセスに渡す作業ディレクトリと環境変数を返す。

    戻り値は (src の絶対パス, 環境変数の辞書) の組。
    このファイルの位置から src を求め、コピーした環境変数の PYTHONPATH の先頭に
    追加する。既存の PYTHONPATH は残し、親プロセスの環境変数は変更しない。

    相対パスだけに頼ると IDE や CI の起動場所によって mcp_server を import できなく
    なるため、子プロセスの作業場所と検索パスを明示的にそろえる。
    """

    src_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(src_root)
        if not existing_pythonpath
        else os.pathsep.join((str(src_root), existing_pythonpath))
    )
    return str(src_root), env


async def load_tool_catalog() -> ToolCatalog:
    """ローカルの MCP サーバーからツール定義を取得し、分類した ToolCatalog を返す。

    現在の Python 実行環境で mcp_server.server を子プロセスとして起動し、
    stdio（標準入出力）でツール名・説明・引数の定義を取得する。
    必要なツール名がすべてそろっているか確認し、不足があれば RuntimeError にする。

    READ_ONLY_TOOL_NAMES のツールは名前順のリスト、MUTATING_TOOL_NAMES のツールは
    名前で引ける辞書にする。リストにない未知のツールは戻り値に含めない。
    取得した観測ツールだけを LLM に公開し、復旧ツールは承認後の処理に限定する。
    """

    cwd, env = _mcp_subprocess_environment()
    client = MultiServerMCPClient(
        {
            "operations": {
                "transport": "stdio",
                "command": sys.executable,
                "args": ["-m", "mcp_server.server"],
                "cwd": cwd,
                "env": env,
            }
        }
    )
    tools = await client.get_tools()
    by_name = {tool.name: tool for tool in tools}

    missing = (READ_ONLY_TOOL_NAMES | MUTATING_TOOL_NAMES) - by_name.keys()
    if missing:
        raise RuntimeError(f"MCP server is missing required tools: {sorted(missing)}")

    return ToolCatalog(
        read_only=[by_name[name] for name in sorted(READ_ONLY_TOOL_NAMES)],
        mutating={name: by_name[name] for name in MUTATING_TOOL_NAMES},
    )
