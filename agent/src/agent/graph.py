"""3チーム対抗研修用の LangGraph starter。

このファイルだけを受講者の主な編集対象にする。
Docker / MCP Server / Tool 実装 / 監視 / Dashboard は講師側で準備済み。

開始時点では安全な placeholder graph が動く。
受講者は TODO 1〜4 を実装し、最後に TODO 5 で本番 graph へ配線する。

TODO コメントは「問題文」なので、基本的に削除せず、その直下へ実装を書く。

競技では各チームが同じ MCP Tool・同じ Gemini model・同じ障害条件を使う。
差を出してよいのは Prompt、調査戦略、State の追加項目、routing、
レポートの見せ方など。ただし mutation Tool の安全境界は変更しない。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from agent.config import Settings
from agent.mcp_tools import ToolCatalog
from agent.models import ApprovalRequest, Diagnosis

LOGGER = logging.getLogger(__name__)


class IncidentState(TypedDict):
    """障害対応中に各 Node が共有する State。

    必須項目は runtime / Dashboard と連携しているため削除しないこと。
    チーム独自の項目を追加するのは OK。
    """

    messages: Annotated[list[BaseMessage], add_messages]
    incident: str
    diagnosis: Diagnosis | None
    approval: Literal["not_required", "pending", "approved", "rejected"]
    verification: dict | None
    verify_attempts: int
    investigation_tool_results: int
    report: str | None


# ---------------------------------------------------------------------------
# TEAM CUSTOMIZATION ZONE
# ---------------------------------------------------------------------------
# TODO 1（必須ではないが推奨）:
# 自分たちの Agent の調査方針を Prompt に表現する。
#
# 例:
# - まず広く観測してから深掘りする
# - 推測より観測事実を優先する
# - 1つの証拠だけで断定しない
# - PostgreSQL が running でも DB 利用不能はあり得る
# - 必要な情報が揃ったら Tool 呼び出しを止める
#
# 禁止:
# - 「今回の障害は connection exhaustion だ」と答えを埋め込む
# - 特定の競技問題だけを直接判定する hard-code
#
# 下は最低限動く baseline。チームごとに改善してよい。
INVESTIGATION_SYSTEM_PROMPT = """\
You are the first-response investigator for a training web system:
Browser -> httpd -> Tomcat -> PostgreSQL.

Investigate the incident using only the read-only tools provided to you.
Prefer observed evidence over guesses.
Start broad, then choose the next observation based on the results already collected.
Correlate multiple observations before concluding when possible.
If application logs suggest a database connection problem while PostgreSQL is
still running, inspect PostgreSQL connection state instead of assuming the DB
process itself is down.
When enough evidence exists to diagnose the incident, stop calling tools and
summarize the investigation briefly.
"""


JUDGE_SYSTEM_PROMPT = """\
You are the decision stage of an incident-response workflow.
Use only the conversation and tool results already collected.

Choose one recommended_action:
- start_container
- restart_container
- terminate_postgres_connections
- manual
- none

Choose start_container only when a target container is observed stopped/exited.
Choose restart_container only when a running service clearly needs a restart.
Choose terminate_postgres_connections only when the observations show abnormal
PostgreSQL sessions from a specific application_name.
For terminate_postgres_connections, use the exact observed application_name.

Use manual when the repair requires a configuration change, credential repair,
or another action outside the allowed mutation tools.
Do not invent evidence, service names, or PostgreSQL application_name values.
"""


def build_graph(
    settings: Settings,
    catalog: ToolCatalog,
    emit_event,
    emit_state,
):
    """研修用 Graph を構築する。

    受講者が編集する主要ポイント:
    - TODO 2: investigate
    - TODO 3: judge
    - TODO 4: approval
    - TODO 5: StateGraph の配線

    講師側で完成済み:
    - MCP Tool の取得と read-only / mutation 分離
    - ToolNode 実行ラッパー
    - mutation Tool の実行処理
    - verify
    - report
    - Dashboard / runtime
    """

    llm = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        api_key=settings.gemini_api_key,
        temperature=0.1,
        max_retries=2,
        timeout=settings.gemini_timeout_seconds,
    )

    # LLM に渡してよいのは read-only Tool だけ。
    investigator_llm = llm.bind_tools(catalog.read_only)

    # judge では自由文ではなく Diagnosis 型へ変換する。
    diagnosis_llm = llm.with_structured_output(Diagnosis, method="json_schema")

    # ToolNode 自体は講師側で生成済み。受講者は Graph に組み込む。
    raw_tool_node = ToolNode(catalog.read_only)
    read_tools = {tool.name: tool for tool in catalog.read_only}

    async def starter_placeholder(state: IncidentState) -> dict:
        """TODO 実装前でも安全に起動できる placeholder。"""
        emit_state("starter", state)
        emit_event(
            "WARN",
            "Starter Agent detected an incident. Student TODOs are not connected yet.",
        )
        return {
            "report": (
                "【Starter Agent】障害を検知しました。"
                "investigate / judge / approval / Graph wiring はハンズオンで実装します。"
            )
        }

    # ------------------------------------------------------------------
    # TODO 2: investigate を実装する
    # ------------------------------------------------------------------
    async def investigate(state: IncidentState) -> dict:
        """LLM に「次に何を観測するか」を判断させる Node。

        実装の目安は 5〜15 行程度。

        やること:
        1. emit_state("investigate", state) で現在Stateを画面に出す
        2. SystemMessage + state["messages"] を LLM へ渡す
        3. investigator_llm.ainvoke(...) を呼ぶ
        4. response を {"messages": [response]} で返す

        発展:
        - Tool 回数上限に近づいたら結論を促す
        - 独自の調査方針を HumanMessage として追加する
        - State に独自カウンタを追加する

        注意:
        mutation Tool は investigator_llm に bind してはいけない。
        """
        raise NotImplementedError("TODO 2: investigate を実装してください")

    # ------------------------------------------------------------------
    # ToolNode wrapper は講師側で完成済み
    # ------------------------------------------------------------------
    async def tools(state: IncidentState) -> dict:
        """LLM が選択した read-only Tool を実行し、結果を State に戻す。"""
        emit_state("tools", state)
        result = await raw_tool_node.ainvoke(state)
        tool_messages = [
            message
            for message in result.get("messages", [])
            if isinstance(message, ToolMessage)
        ]

        for message in tool_messages:
            preview = str(message.content).replace("\n", " ")[:450]
            emit_event("INFO", f"Observation from {message.name}: {preview}")

        return {
            **result,
            "investigation_tool_results": (
                state["investigation_tool_results"] + len(tool_messages)
            ),
        }

    # ------------------------------------------------------------------
    # TODO 3: judge を実装する
    # ------------------------------------------------------------------
    async def judge(state: IncidentState) -> dict:
        """観測履歴を Diagnosis に変換する Node。

        実装の目安は 5〜15 行程度。

        やること:
        1. emit_state("judge", state) で現在Stateを画面に出す
        2. JUDGE_SYSTEM_PROMPT と state["messages"] をまとめる
        3. diagnosis_llm.ainvoke(...) を呼ぶ
        4. {"diagnosis": diagnosis, "investigation_tool_results": 0} を返す

        ポイント:
        「調査」と「判断」を Node として分けることで、
        Agent の自由な探索を Graph の明示的な State に戻す。
        """
        raise NotImplementedError("TODO 3: judge を実装してください")

    # ------------------------------------------------------------------
    # routing helper は講師側で用意
    # ------------------------------------------------------------------
    def after_judge(state: IncidentState) -> Literal["approval", "report"]:
        """状態変更を提案している場合だけ Human Approval へ進む。"""
        diagnosis = state["diagnosis"]
        if diagnosis and diagnosis.recommended_action in {
            "start_container",
            "restart_container",
            "terminate_postgres_connections",
        }:
            return "approval"
        return "report"

    # ------------------------------------------------------------------
    # TODO 4: approval を実装する
    # ------------------------------------------------------------------
    def approval(state: IncidentState) -> dict:
        """状態変更の直前で interrupt() し、人間の判断を待つ。

        実装の目安は 10〜20 行程度。

        やること:
        1. emit_state("approval", state) で現在Stateを画面に出す
        2. state["diagnosis"] を取得
        3. ApprovalRequest を作成して model_dump()
        4. approved = interrupt(payload)
        5. approved / rejected を State に返す

        安全ルール:
        - interrupt() より前に mutation Tool を実行しない
        - LLM に mutation Tool を直接渡さない
        """
        raise NotImplementedError("TODO 4: approval を実装してください")

    def after_approval(state: IncidentState) -> Literal["remediate", "report"]:
        return "remediate" if state["approval"] == "approved" else "report"

    # ------------------------------------------------------------------
    # remediate は講師側で完成済み
    # ------------------------------------------------------------------
    async def remediate(state: IncidentState) -> dict:
        """Human が承認した Diagnosis に対応する mutation Tool だけを実行する。"""
        emit_state("remediate", state)
        diagnosis = state["diagnosis"]
        if diagnosis is None:
            raise RuntimeError("remediate node requires diagnosis")

        action = diagnosis.recommended_action
        if action not in catalog.mutating:
            raise RuntimeError(f"unsupported remediation: {action}")

        if action == "terminate_postgres_connections":
            if not diagnosis.target_application or diagnosis.target_application == "none":
                raise RuntimeError(
                    "PostgreSQL connection termination requires target_application"
                )
            args = {"application_name": diagnosis.target_application}
            target_text = f"postgres application={diagnosis.target_application}"
        else:
            if diagnosis.target_service == "none":
                raise RuntimeError("container remediation requires a target service")
            args = {"service": diagnosis.target_service}
            target_text = diagnosis.target_service

        emit_event("WARN", f"Executing approved action: {action}({target_text})")
        result = await catalog.mutating[action].ainvoke(args)
        emit_event("INFO", f"Remediation result: {str(result)[:450]}")

        return {
            "messages": [
                HumanMessage(
                    content=(
                        "Human-approved remediation executed: "
                        f"{action}({target_text}). Tool result: {result}"
                    )
                )
            ]
        }

    # ------------------------------------------------------------------
    # verify は講師側で完成済み
    # ------------------------------------------------------------------
    async def verify(state: IncidentState) -> dict:
        """状態変更後、ユーザー視点の HTTP で本当に直ったか再観測する。"""
        emit_state("verify", state)
        http_tool = read_tools["http_request"]
        last_result = None

        for attempt in range(1, 7):
            last_result = await http_tool.ainvoke(
                {"path": "/api/members", "method": "GET"}
            )
            status = _status_code(last_result)
            emit_event("INFO", f"Verification attempt {attempt}/6: HTTP {status}")

            if status == 200:
                return {
                    "verification": {
                        "success": True,
                        "observation": last_result,
                    },
                    "verify_attempts": state["verify_attempts"] + 1,
                }

            await asyncio.sleep(2)

        return {
            "verification": {
                "success": False,
                "observation": last_result,
            },
            "verify_attempts": state["verify_attempts"] + 1,
            "messages": [
                HumanMessage(
                    content=(
                        "The approved remediation was executed, but verification "
                        f"still failed. Latest observation: {last_result}. "
                        "Re-investigate the current environment."
                    )
                )
            ],
        }

    def after_verify(state: IncidentState) -> Literal["investigate", "report"]:
        verification = state["verification"] or {}
        if verification.get("success"):
            return "report"
        if state["verify_attempts"] <= settings.verify_retry_limit:
            return "investigate"
        return "report"

    # ------------------------------------------------------------------
    # report は講師側で完成済み
    # ------------------------------------------------------------------
    async def report(state: IncidentState) -> dict:
        """診断・承認・復旧確認を人間向けの結果にまとめる。"""
        emit_state("report", state)
        diagnosis = state["diagnosis"]

        if diagnosis is None:
            text = (
                state.get("report")
                or "調査結果: 診断情報を生成できませんでした。人手で確認してください。"
            )
        else:
            evidence = "\n".join(f"- {item}" for item in diagnosis.evidence)
            verification = state["verification"]

            if state["approval"] == "rejected":
                outcome = "復旧操作は人間に却下されたため実行していません。"
            elif verification and verification.get("success"):
                outcome = "承認された復旧操作を実行し、HTTP 200で復旧を確認しました。"
            elif diagnosis.recommended_action == "manual":
                outcome = (
                    "Agentの許可された操作範囲では復旧できないため、"
                    "人間へエスカレーションします。"
                )
            elif diagnosis.recommended_action == "none":
                outcome = "状態変更は不要と判断しました。"
            else:
                outcome = (
                    "自動復旧後も正常性を確認できませんでした。"
                    "人間へエスカレーションします。"
                )

            target = diagnosis.target_service
            if diagnosis.target_application != "none":
                target += f" / application={diagnosis.target_application}"

            text = (
                "【一次障害対応レポート】\n"
                f"障害: {state['incident']}\n"
                f"推定原因: {diagnosis.root_cause}\n"
                f"確信度: {diagnosis.confidence}\n"
                f"根拠:\n{evidence}\n"
                f"提案/実施: {diagnosis.recommended_action} -> {target}\n"
                f"結果: {outcome}"
            )

        emit_event("INFO", "Incident report created")
        return {"report": text}

    # ------------------------------------------------------------------
    # TODO 5: ここを完成 Graph に置き換える
    # ------------------------------------------------------------------
    #
    # 研修開始時点は、障害を検知しても何も変更せず終了する安全な Graph。
    #
    # 最終的には次の構造にする:
    #
    # START
    #   |
    #   v
    # investigate <------ tools
    #   |                  |
    #   +------------------+
    #   |
    #   v
    # judge
    #   |
    #   +---- manual / none ------> report
    #   |
    #   v
    # approval
    #   |
    #   +---- reject --------------> report
    #   |
    #   v
    # remediate
    #   |
    #   v
    # verify ---- failure ---------> investigate
    #   |
    #   v
    # report -> END
    #
    # 必須:
    # - investigate の後は _route_after_investigate で tools / judge を分岐
    # - tools -> investigate の loop
    # - judge の後は after_judge
    # - approval の後は after_approval
    # - remediate -> verify
    # - verify の後は after_verify
    #
    # オリジナリティを出してよい:
    # - Prompt
    # - State の追加項目
    # - read-only Tool を使う調査戦略
    # - LLM と決定論的処理の役割分担
    # - report の内容
    #
    # 変更禁止:
    # - catalog.mutating を LLM へ bind する
    # - approval を迂回して mutation Tool を呼ぶ
    # - MCP Server / fault injector を競技用に改造する
    # - 障害の答えを hard-code する
    #
    builder = StateGraph(IncidentState)
    builder.add_node("starter", starter_placeholder)
    builder.add_edge(START, "starter")
    builder.add_edge("starter", END)

    return builder.compile(checkpointer=InMemorySaver())


def _route_after_investigate(
    state: IncidentState,
) -> Literal["tools", "judge"]:
    """LLM が Tool call を返したら tools、それ以外なら judge。"""
    latest = state["messages"][-1]
    if isinstance(latest, AIMessage) and latest.tool_calls:
        return "tools"
    return "judge"


def _status_code(tool_result) -> int | None:
    """MCP / LangChain の Tool result から HTTP status code を取り出す。"""
    if isinstance(tool_result, ToolMessage):
        if tool_result.artifact:
            status = _status_code(tool_result.artifact)
            if status is not None:
                return status
        return _status_code(tool_result.content)

    if isinstance(tool_result, dict):
        value = tool_result.get("status_code")
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass

        for key in ("structured_content", "content", "text"):
            if key in tool_result:
                status = _status_code(tool_result[key])
                if status is not None:
                    return status
        return None

    if isinstance(tool_result, (list, tuple)):
        for item in tool_result:
            status = _status_code(item)
            if status is not None:
                return status
        return None

    if isinstance(tool_result, str):
        try:
            parsed = json.loads(tool_result)
        except json.JSONDecodeError:
            match = re.search(
                r"status_code['\"]?\s*[:=]\s*(\d+)",
                tool_result,
            )
            return int(match.group(1)) if match else None
        return _status_code(parsed)

    return None
