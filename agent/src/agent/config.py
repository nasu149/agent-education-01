"""Environment-backed configuration for the training Agent."""

from __future__ import annotations

from dataclasses import dataclass
import os


_LANGGRAPH_PRINT_MODES = {"off", "updates", "values", "debug"}


@dataclass(frozen=True)
class Settings:
    """Runtime configuration.

    Defaults favor a classroom laptop: short monitoring intervals, local Docker,
    and the Gemini Developer API. Every value can be overridden from `.env`.
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
