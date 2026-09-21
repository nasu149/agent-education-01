"""環境変数から、研修用 Agent の動作設定を組み立てる。

監視間隔や調査回数の上限をコードから分離し、実行環境に合わせて変更できるようにする。
このモジュール自身は .env ファイルを読まず、起動スクリプトや Docker Compose が
プロセスに渡した環境変数を参照する。
"""

from __future__ import annotations

from dataclasses import dataclass
import os


_LANGGRAPH_PRINT_MODES = {"off", "updates", "values", "debug"}


@dataclass(frozen=True)
class Settings:
    """Agent の起動時に確定する設定をまとめた、変更不可のデータクラス。

    Gemini の接続情報、監視先 URL、監視間隔、連続失敗のしきい値、調査・復旧確認の
    上限、ログ出力方法を保持する。frozen=True により、生成後のフィールドへの
    再代入を防ぐ。各処理にはこのオブジェクトを渡し、同じ設定を共有する。

    通常は from_env() で生成する。既定値は研修用のローカル Docker 環境を想定する。
    gemini_api_key には秘密情報が入るため、設定全体をそのままログに出さないこと。
    """

    gemini_api_key: str
    gemini_model: str
    app_base_url: str
    target_compose_project: str
    target_services: tuple[str, ...]
    health_check_interval_seconds: float
    monitor_startup_grace_seconds: float
    failure_threshold: int
    max_investigation_tool_results: int
    verify_retry_limit: int
    langgraph_print_mode: str
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        """プロセスの環境変数を読み、型を変換して Settings を返す。

        TARGET_SERVICES はカンマ区切りの文字列から空要素を除いたタプルにする。
        時間は float、回数は int に変換し、APP_BASE_URL 末尾の '/' を取り除く。
        未設定の変数には、このメソッド内で定めた既定値を使う。

        LANGGRAPH_PRINT_MODE は小文字にそろえ、空文字・none・false・0 を off として
        扱う。許可したモード以外の値や、数値に変換できない設定値は ValueError になる。
        .env の読み込みや、数値の大小・API キーの有効性の検証はここでは行わない。
        """
        services = tuple(
            item.strip()
            for item in os.getenv("TARGET_SERVICES", "httpd,tomcat,postgres").split(",")
            if item.strip()
        )
        langgraph_print_mode = os.getenv("LANGGRAPH_PRINT_MODE", "updates").strip().lower()
        if langgraph_print_mode in {"", "none", "false", "0"}:
            langgraph_print_mode = "off"
        if langgraph_print_mode not in _LANGGRAPH_PRINT_MODES:
            allowed = ", ".join(sorted(_LANGGRAPH_PRINT_MODES))
            raise ValueError(
                f"LANGGRAPH_PRINT_MODE must be one of {allowed}; got {langgraph_print_mode!r}"
            )

        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
            app_base_url=os.getenv("APP_BASE_URL", "http://httpd").rstrip("/"),
            target_compose_project=os.getenv("TARGET_COMPOSE_PROJECT", "agent-education"),
            target_services=services,
            health_check_interval_seconds=float(os.getenv("HEALTH_CHECK_INTERVAL_SECONDS", "5")),
            monitor_startup_grace_seconds=float(os.getenv("MONITOR_STARTUP_GRACE_SECONDS", "20")),
            failure_threshold=int(os.getenv("FAILURE_THRESHOLD", "2")),
            max_investigation_tool_results=int(os.getenv("MAX_INVESTIGATION_TOOL_RESULTS", "6")),
            verify_retry_limit=int(os.getenv("VERIFY_RETRY_LIMIT", "1")),
            langgraph_print_mode=langgraph_print_mode,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
