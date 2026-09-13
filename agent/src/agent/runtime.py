"""Background monitor and incident lifecycle coordinator."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime
import logging
import time
import uuid
from typing import Any

import httpx
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.types import Command
from pydantic import BaseModel

from agent.config import Settings
from agent.graph import build_graph
from agent.mcp_tools import load_tool_catalog

LOGGER = logging.getLogger(__name__)


class AgentRuntime:
    """Own monitoring state and serialize incident execution.

    The health checker is intentionally ordinary code. LangGraph is entered only
    after a concrete failure has been detected.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.events: deque[dict[str, str]] = deque(maxlen=250)
        self.node_history: deque[dict[str, str]] = deque(maxlen=80)
        self.graph = None
        self.catalog = None
        self.monitor_task: asyncio.Task | None = None
        self.started_at = time.monotonic()
        self.consecutive_failures = 0
        self.healthy = False
        self.last_http_status: int | None = None
        self.active_incident_id: str | None = None
        self.active_config: dict[str, Any] | None = None
        self.pending_approval: dict[str, Any] | None = None
        self.last_report: str | None = None
        self.incident_latched = False
        self.current_node = "monitoring"
        self.current_state: dict[str, Any] | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Load MCP tools, compile the graph, and start health monitoring."""
        if not self.settings.gemini_api_key:
            self.event("ERROR", "GEMINI_API_KEY is empty. Copy .env.example to .env and set the key.")
        self.catalog = await load_tool_catalog()
        self.graph = build_graph(self.settings, self.catalog, self.event, self.state_trace)
        self.event("INFO", "MCP tools loaded; LangGraph compiled")
        self.event("INFO", f"LangGraph console print mode: {self.settings.langgraph_print_mode}")
        self.monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        """Stop the background task cleanly."""
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass

    def event(self, level: str, message: str) -> None:
        """Append an educational trace event and mirror it to normal logs."""
        LOGGER.log(getattr(logging, level, logging.INFO), message)
        self.events.append(
            {
                "time": datetime.now().strftime("%H:%M:%S"),
                "level": level,
                "message": message,
            }
        )

    def state_trace(self, node: str, state: dict[str, Any]) -> None:
        """Capture the State presented to each node for the training dashboard.

        This is intentionally a display snapshot, not another source of truth.
        LangGraph still owns the real State and checkpoint. Large message bodies
        are shortened so a browser can poll this endpoint comfortably.
        """
        self.current_node = node
        self.current_state = _state_for_ui(state)
        now = datetime.now().strftime("%H:%M:%S")
        last_node = self.node_history[-1]["node"] if self.node_history else None
        if node != last_node or node in {"investigate", "tools", "verify"}:
            self.node_history.append({"time": now, "node": node})

    def _langgraph_print_mode(self):
        """Translate the classroom env setting to LangGraph's native print_mode.

        ``print_mode`` is a LangGraph runtime feature: it prints streamed graph
        information to stdout without changing the graph's normal return value.
        ``updates`` therefore shows each node's partial State update while the UI
        can continue using the final result and checkpoints exactly as before.
        """
        if self.settings.langgraph_print_mode == "off":
            return ()
        return self.settings.langgraph_print_mode

    async def _monitor_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.health_check_interval_seconds)
            await self._health_tick()

    async def _health_tick(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                response = await client.get(f"{self.settings.app_base_url}/api/members")
                self.last_http_status = response.status_code
                current_healthy = response.status_code == 200
        except httpx.HTTPError:
            self.last_http_status = None
            current_healthy = False

        if current_healthy:
            if not self.healthy:
                self.event("INFO", "Health check: OK")
            self.healthy = True
            self.consecutive_failures = 0
            if self.incident_latched and self.active_incident_id is None:
                self.incident_latched = False
                self.event("INFO", "System recovered; incident latch cleared")
            return

        self.healthy = False
        self.consecutive_failures += 1

        if time.monotonic() - self.started_at < self.settings.monitor_startup_grace_seconds:
            return
        if self.consecutive_failures < self.settings.failure_threshold:
            self.event("WARN", f"Health check failed ({self.consecutive_failures}/{self.settings.failure_threshold})")
            return
        if self.incident_latched or self.active_incident_id:
            return

        self.incident_latched = True
        await self.open_incident(
            f"Health checker detected application failure. HTTP status={self.last_http_status!r}"
        )

    async def open_incident(self, incident: str) -> None:
        """Start one LangGraph execution for a newly detected incident."""
        async with self._lock:
            incident_id = str(uuid.uuid4())[:8]
            self.active_incident_id = incident_id
            self.active_config = {"configurable": {"thread_id": incident_id}}
            self.pending_approval = None
            self.node_history.clear()
            self.event("ERROR", f"Incident {incident_id} detected: {incident}")
            initial = {
                "messages": [HumanMessage(content=incident)],
                "incident": incident,
                "diagnosis": None,
                "approval": "not_required",
                "verification": None,
                "verify_attempts": 0,
                "investigation_tool_results": 0,
                "report": None,
            }
            self.current_node = "investigate"
            self.current_state = _state_for_ui(initial)
            try:
                result = await self.graph.ainvoke(
                    initial,
                    config=self.active_config,
                    print_mode=self._langgraph_print_mode(),
                )
                self._consume_graph_result(result)
            except Exception as exc:
                LOGGER.exception("Agent execution failed")
                self.event("ERROR", f"Agent execution failed: {type(exc).__name__}: {exc}")
                self.current_node = "error"
                self._finish_incident()

    async def approve(self, approved: bool) -> None:
        """Resume the interrupted graph with the human decision."""
        async with self._lock:
            if not self.active_incident_id or not self.active_config or not self.pending_approval:
                raise RuntimeError("No incident is waiting for approval")
            self.event("INFO", f"Human decision: {'APPROVE' if approved else 'REJECT'}")
            self.pending_approval = None
            try:
                result = await self.graph.ainvoke(
                    Command(resume=approved),
                    config=self.active_config,
                    print_mode=self._langgraph_print_mode(),
                )
                self._consume_graph_result(result)
            except Exception as exc:
                LOGGER.exception("Agent resume failed")
                self.event("ERROR", f"Agent resume failed: {type(exc).__name__}: {exc}")
                self.current_node = "error"
                self._finish_incident()

    def _consume_graph_result(self, result: dict[str, Any]) -> None:
        interrupts = result.get("__interrupt__", [])
        if interrupts:
            payload = interrupts[0].value
            self.pending_approval = payload
            self.current_node = "approval"
            if self.current_state is not None:
                self.current_state["approval"] = "pending"
            self.event(
                "WARN",
                f"Graph paused for approval: {payload.get('action')} {payload.get('target_service')}",
            )
            return

        self.current_state = _state_for_ui(result)
        self.current_node = "done"
        self.node_history.append({"time": datetime.now().strftime("%H:%M:%S"), "node": "done"})
        report = result.get("report")
        if report:
            self.last_report = report
        self._finish_incident()

    def _finish_incident(self) -> None:
        if self.active_incident_id:
            self.event("INFO", f"Incident {self.active_incident_id} graph execution finished")
        self.active_incident_id = None
        self.active_config = None
        self.pending_approval = None

    def snapshot(self) -> dict[str, Any]:
        """Return JSON-safe UI state."""
        return {
            "healthy": self.healthy,
            "last_http_status": self.last_http_status,
            "active_incident_id": self.active_incident_id,
            "pending_approval": self.pending_approval,
            "last_report": self.last_report,
            "current_node": self.current_node,
            "current_state": self.current_state,
            "node_history": list(self.node_history),
            "events": list(self.events),
        }


def _state_for_ui(state: dict[str, Any]) -> dict[str, Any]:
    """Create a compact JSON-safe view of IncidentState for teaching."""
    result: dict[str, Any] = {}
    for key in (
        "incident",
        "diagnosis",
        "approval",
        "verification",
        "verify_attempts",
        "investigation_tool_results",
        "report",
    ):
        result[key] = _json_safe(state.get(key))

    messages = state.get("messages") or []
    result["messages_count"] = len(messages)
    result["messages"] = [_message_for_ui(message) for message in messages[-8:]]
    return result


def _message_for_ui(message: Any) -> dict[str, Any]:
    if isinstance(message, BaseMessage):
        item: dict[str, Any] = {
            "type": message.type,
            "content": _shorten(message.content, 900),
        }
        name = getattr(message, "name", None)
        if name:
            item["name"] = name
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            item["tool_calls"] = [call.get("name", "unknown") for call in tool_calls]
        return item
    return {"type": type(message).__name__, "content": _shorten(message, 900)}


def _json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, BaseMessage):
        return _message_for_ui(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _shorten(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else str(value)
    text = text.replace("\x00", "")
    return text if len(text) <= limit else text[:limit] + "…"
