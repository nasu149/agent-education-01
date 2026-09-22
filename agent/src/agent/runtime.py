"""定期監視と、障害検知から承認・報告までの実行管理を担当する。

HTTP の正常・異常判定は通常の Python コードで行い、障害が続いたときに LangGraph を
起動する。Graph の一時停止・再開に必要な情報と、研修画面に見せる履歴を保持する。
"""

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
    """監視状態と障害対応の進行状況を保持する、アプリ内の実行管理オブジェクト。

    settings は起動設定、graph は障害対応の手順、catalog は利用可能な MCP ツール。
    active_config の thread_id で Graph の実行を識別し、承認時に同じ実行を再開する。
    pending_approval は人間の判断待ちの情報、last_report は直近の報告を保持する。

    asyncio.Lock で Graph の開始と再開の同時実行を防ぐ。HTTP の監視自体に LLM は
    使わず、連続失敗を確認したとき、または手動調査を依頼されたときに Graph を使う。
    状態はプロセス内のメモリーに保持するため、再起動をまたいで保存されない。
    """

    def __init__(self, settings: Settings):
        """起動設定を受け取り、監視・履歴・承認待ちの初期状態を用意する。

        イベントは直近 250 件、ノード履歴は直近 80 件に制限する。
        started_at は起動直後の猶予時間を測るための単調増加時計の値。
        この時点では監視タスクや Graph は起動せず、start() に準備を委ねる。
        """
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
        """MCP ツール取得、Graph の構築、バックグラウンド監視の開始を順に行う。

        Graph にイベント記録と状態表示用のコールバックを渡し、各ノードの進行を
        研修画面で追えるようにする。最後に _monitor_loop() を非同期タスクとして起動する。
        API キーが空ならエラーを記録するが、その場では処理を打ち切らない。
        ツール取得や Graph 構築時の例外は呼び出し元に伝わる。
        """
        if not self.settings.gemini_api_key:
            self.event("ERROR", "GEMINI_API_KEY is empty. Copy .env.example to .env and set the key.")
        self.catalog = await load_tool_catalog()
        self.graph = build_graph(self.settings, self.catalog, self.event, self.state_trace)
        self.event("INFO", "MCP tools loaded; LangGraph compiled")
        self.event(
            "INFO",
            (
                "Health checker settings: "
                f"interval={self.settings.health_check_interval_seconds}s, "
                f"startup_grace={self.settings.monitor_startup_grace_seconds}s, "
                f"failure_threshold={self.settings.failure_threshold}"
            ),
        )
        self.event(
            "INFO",
            (
                f"Gemini settings: model={self.settings.gemini_model}, "
                f"timeout={self.settings.gemini_timeout_seconds}s"
            ),
        )
        self.event("INFO", f"LangGraph console print mode: {self.settings.langgraph_print_mode}")
        self.monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        """監視タスクへキャンセルを要求し、終了するまで待つ。

        start() でタスクを作成済みの場合だけ処理する。キャンセルによる通常の
        CancelledError はここで受け止め、アプリ終了時のエラーとして扱わない。
        監視ループ内で Graph を実行中なら、その待機にもキャンセルが伝わる。
        """
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass

    def event(self, level: str, message: str) -> None:
        """出来事を通常のログと、研修画面用のイベント履歴の両方に記録する。

        level は INFO・WARN・ERROR など、message は表示する説明文を受け取る。
        履歴には時刻・レベル・本文の辞書を追加し、上限を超えた古い履歴は自動で落とす。
        戻り値はなく、ロガーへの出力と self.events の更新を行う。
        """
        LOGGER.log(getattr(logging, level, logging.INFO), message)
        self.events.append(
            {
                "time": datetime.now().strftime("%H:%M:%S"),
                "level": level,
                "message": message,
            }
        )

    def state_trace(self, node: str, state: dict[str, Any]) -> None:
        """各ノードの開始時点の State を、研修画面用のスナップショットとして保存する。

        node は実行するノード名、state はそのノードに渡された共有状態。
        表示用にメッセージを短縮し、現在のノードと時刻付きの遷移履歴を更新する。
        調査・ツール実行・復旧確認は繰り返しも学習対象なので、同じノードでも記録する。

        ここで保存するのは表示用の情報であり、Graph の実行状態そのものではない。
        再開に使う本来の State とチェックポイントは LangGraph が管理する。
        """
        self.current_node = node
        self.current_state = _state_for_ui(state)
        now = datetime.now().strftime("%H:%M:%S")
        last_node = self.node_history[-1]["node"] if self.node_history else None
        if node != last_node or node in {"investigate", "tools", "verify"}:
            self.node_history.append({"time": now, "node": node})

    def _langgraph_print_mode(self):
        """設定値を、Graph 実行時の print_mode に渡せる値へ変換する。

        off は空のタプルに変換し、それ以外は設定されたモード名を返す。
        updates はノードが返す部分更新、values は状態、debug は詳細な実行情報の
        確認に使う。標準出力への表示を制御する設定で、Graph の戻り値や画面用の
        スナップショットの取得方法は変更しない。
        """
        if self.settings.langgraph_print_mode == "off":
            return ()
        return self.settings.langgraph_print_mode

    async def _monitor_loop(self) -> None:
        """設定された間隔で待機し、HTTP の監視処理を繰り返す。

        asyncio.sleep() により、待機中はほかの非同期処理に実行機会を渡す。
        各回の _health_tick() が終わってから次の待機に進むため、Graph を実行している
        時間は次回の監視開始も遅れる。stop() によるキャンセルでループを終了する。
        """
        while True:
            await asyncio.sleep(self.settings.health_check_interval_seconds)
            await self._health_tick()

    async def _health_tick(self) -> None:
        """HTTP 監視を 1 回行い、必要な場合だけ障害対応を開始する。

        /api/members の HTTP 200 を正常とし、別のステータスや通信エラーを失敗とする。
        正常なら連続失敗回数をゼロに戻す。異常なら回数を増やし、起動猶予時間と
        連続失敗のしきい値を両方満たした時点で open_incident() を呼ぶ。

        incident_latched は、同じ障害を監視のたびに起票しないためのフラグ。
        既に起票済み・対応中なら新規起票を抑制し、対応終了後に正常応答が得られると
        フラグを解除する。このメソッドの判断には LLM を使わない。
        """
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
            f"ヘルスチェックでアプリケーションの異常を検知しました。HTTP ステータス={self.last_http_status!r}"
        )

    async def open_incident(self, incident: str) -> None:
        """障害の説明文を受け取り、新しい State と実行 ID で Graph を開始する。

        incident は監視結果または手動開始の説明。これを最初の HumanMessage にし、
        診断・承認・復旧確認の初期値を設定する。短い UUID を thread_id として使い、
        後から同じチェックポイントを指定して再開できるようにする。

        ロックを保持して Graph が一時停止または終了するまで待ち、結果を取り込む。
        実行時の例外はログに記録し、表示状態を error にして実行中の情報を片付ける。
        戻り値はなく、結果や承認待ちはこのオブジェクトの状態から参照する。
        """
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
        """承認待ちで止まっている Graph に、人間の判断を渡して再開する。

        approved=True は承認、False は却下。実行 ID・設定・承認依頼がそろって
        いなければ RuntimeError を送出する。同じ thread_id の設定を使って
        Command(resume=approved) を渡し、interrupt() の戻り値に判断を届ける。

        ロックでほかの開始・再開処理との同時実行を防ぎ、次の停止または終了まで待つ。
        Graph 再開中の例外は記録して実行中の情報を片付ける。
        """
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
        """Graph の戻り値を読み、承認待ちと実行完了を区別して管理状態に反映する。

        __interrupt__ があれば先頭の依頼を pending_approval に保存し、実行 ID は
        再開のために残す。画面用 State の approval も pending にする。
        中断がなければ最終 State と報告を保存し、done の履歴を追加して対応を終了する。
        """
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
        """実行中の障害 ID・Graph 設定・承認待ち情報を消し、対応を終了する。

        最終報告、イベント、表示用 State は振り返りのために残す。
        incident_latched はここでは解除しない。監視で正常応答を確認してから解除し、
        未復旧の同じ障害に対して調査を繰り返し起動することを避ける。
        """
        if self.active_incident_id:
            self.event("INFO", f"Incident {self.active_incident_id} graph execution finished")
        self.active_incident_id = None
        self.active_config = None
        self.pending_approval = None

    def snapshot(self) -> dict[str, Any]:
        """研修画面が表示する現在の状態を、JSON に変換できる辞書で返す。

        正常性、直近の HTTP ステータス、実行中 ID、承認待ち、報告、State、履歴を含む。
        deque の履歴はリストに変換する。Graph の実行や HTTP の再監視は行わず、
        既に保持している値をまとめる。入れ子の辞書まで深くコピーする処理ではない。
        """
        return {
            "healthy": self.healthy,
            "last_http_status": self.last_http_status,
            "monitoring": {
                "health_check_interval_seconds": self.settings.health_check_interval_seconds,
                "startup_grace_seconds": self.settings.monitor_startup_grace_seconds,
                "failure_threshold": self.settings.failure_threshold,
            },
            "active_incident_id": self.active_incident_id,
            "pending_approval": self.pending_approval,
            "last_report": self.last_report,
            "current_node": self.current_node,
            "current_state": self.current_state,
            "node_history": list(self.node_history),
            "events": list(self.events),
        }


def _state_for_ui(state: dict[str, Any]) -> dict[str, Any]:
    """IncidentState から、研修画面に必要な項目を取り出して辞書にする。

    診断や承認などの値を _json_safe() で変換する。メッセージは全件数を残しつつ、
    本文の表示は直近 8 件だけに絞る。元の State のメッセージ履歴は切り詰めないため、
    LLM の調査に使う履歴と、画面を軽くするための表示制限を分けられる。
    """
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
    """メッセージ 1 件を、種類・短縮本文・ツール名が分かる表示用の辞書にする。

    LangChain の BaseMessage なら type、content と、存在する場合は name を取り出す。
    tool_calls は呼び出し名だけを残し、引数全体は表示しない。本文は 900 文字までに
    短縮する。別の型の値は Python の型名と、その値を文字列化した本文を返す。
    """
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
    """モデルやメッセージを再帰的に変換し、JSON で表せる値を返す。

    Pydantic モデルは model_dump(mode='json')、LangChain メッセージは表示用の辞書に
    変換する。辞書のキーは文字列にし、リスト・タプルの各要素も同じ手順で変換する。
    None・文字列・数値・真偽値はそのまま返し、未知の型は str() で文字列にする。
    表示用の変換なので、元の Python オブジェクトへ完全に戻すことは目的としない。
    """
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
    """値を文字列にし、NUL 文字を除去してから表示用の長さに短縮する。

    limit は残す本文の文字数。制限を超えた場合は先頭 limit 文字に省略記号を付ける。
    そのため返す文字列は最大で limit + 1 文字になる。短い本文は省略せず返す。
    """
    text = value if isinstance(value, str) else str(value)
    text = text.replace("\x00", "")
    return text if len(text) <= limit else text[:limit] + "…"
