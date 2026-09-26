"""障害対応 Agent の State・Prompt・Node 実装をまとめる。

graph.py は LangGraph の配線に集中させ、このファイルでは各 Node が
「何をするか」を定義する。

TODO コメントは研修の問題文なので、基本的に削除せず、その直下へ実装を書く。
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
    remediation_action: str | None
    remediation_args: dict | None
    remediation_result: object | None
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
# TODO D5: disk-full の兆候を見たとき、追加した観測 Tool を選べるよう Prompt を拡張する。
INVESTIGATION_SYSTEM_PROMPT = """\
あなたは、次の構成の研修用 Web システムで障害の初動調査を担当します。
ブラウザー -> httpd -> Tomcat -> PostgreSQL。

提供された読み取り専用ツールだけを使って障害を調査してください。
推測よりも観測した証拠を優先してください。
最初は広く状況を確認し、収集済みの結果に基づいて次に何を観測するか選んでください。
可能な限り、複数の観測結果を照らし合わせてから結論を出してください。
PostgreSQL が稼働中なのにアプリケーションログがデータベース接続の問題を示す場合は、
DB プロセス自体が停止していると決めつけず、PostgreSQL の接続状態を確認してください。
Tomcat ログや HTTP 応答に "No space left on device"、"audit storage unavailable"、
"audit_write_failed" などのファイル書き込み失敗がある場合は、
研修用ディスクの使用率と大きなファイルを確認してください。
障害を診断するのに十分な証拠が集まったら、ツールの呼び出しを止め、
調査結果を簡潔にまとめてください。
状態を変更するツールの実行を求めたり、ツールの出力を捏造したりしないでください。
証拠が十分にそろったら、同じようなツールの呼び出しを繰り返さず、調査を終了してください。
"""


# TODO D5: cleanup_training_logs を判断候補へ追加し、観測事実に基づく選択条件を書く。
JUDGE_SYSTEM_PROMPT = """\
あなたは、障害対応ワークフローの判断段階を担当します。
これまでに収集した会話とツールの実行結果だけを使ってください。
root_cause、evidence の各項目、action_reason の説明文は日本語で記述してください。
JSON のキー、recommended_action、target_service、confidence の選択肢は変更しないでください。
application_name、サービス名、引用するログやエラーなどの識別情報は原文を保持してください。

recommended_action は次のいずれかを選んでください。
- start_container
- restart_container
- terminate_postgres_connections
- cleanup_training_logs
- manual
- none

start_container は、対象コンテナが停止・終了していると観測された場合にだけ選んでください。
restart_container は、稼働中のサービスに明らかに再起動が必要な場合にだけ選んでください。
terminate_postgres_connections は、特定の application_name による異常な PostgreSQL
セッションが観測された場合にだけ選んでください。
terminate_postgres_connections では、観測された application_name を正確に指定してください。
cleanup_training_logs は、Tomcat の /training-disk が高使用率で、
list_large_files に /training-disk/archive/training-*.log が容量を占有していることが
観測された場合にだけ選んでください。その場合 target_service は tomcat にしてください。

復旧に設定変更、認証情報の修正、または許可された状態変更ツールの範囲外の操作が
必要な場合は、manual を選んでください。
証拠、サービス名、PostgreSQL の application_name の値を捏造しないでください。
"""


REMEDIATION_SYSTEM_PROMPT = """\
あなたは、診断結果を実際に実行可能な復旧 Tool Call に変換する担当です。
これまでの観測履歴と Diagnosis だけを根拠にしてください。

状態変更が必要で、提供された mutation Tool のどれかで安全に対応できる場合は、
最小限の Tool を必ず 1 つだけ選び、正しい引数で Tool Call を生成してください。
Tool の名前・説明・入力 schema は bind_tools で提供された定義を使ってください。
推測でサービス名や application_name を作らず、観測済みの値だけを使ってください。

Diagnosis が manual または none を推奨している場合、または利用可能な Tool では
安全に対応できない場合は Tool Call を生成せず、その理由を短く返してください。

ここで生成した Tool Call はまだ実行されません。
次の approval Node が interrupt() で人間に Tool 名と引数を提示し、
承認された場合にだけ ToolNode が実行します。
"""


class IncidentNodes:
    """Graph が利用する Node と、その共通依存関係をまとめる。

    build_graph() の中に大量の nested function を置かず、
    settings / ToolCatalog / LLM / callback をこの class が保持する。

    LangGraph には bound method（例: nodes.investigate）を Node として登録する。
    """

    def __init__(
        self,
        settings: Settings,
        catalog: ToolCatalog,
        emit_event,
        emit_state,
    ):
        self.settings = settings
        self.catalog = catalog
        self.emit_event = emit_event
        self.emit_state = emit_state

        self.llm = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            api_key=settings.gemini_api_key,
            temperature=0.1,
            max_retries=2,
            timeout=settings.gemini_timeout_seconds,
        )

        # LLM に渡してよいのは read-only Tool だけ。
        self.investigator_llm = self.llm.bind_tools(catalog.read_only)

        # judge では自由文ではなく Diagnosis 型へ変換する。
        self.diagnosis_llm = self.llm.with_structured_output(
            Diagnosis,
            method="json_schema",
        )

        # mutation Tool は復旧計画専用 LLM に bind する。
        # bind_tools() は実行せず、Tool の定義を LLM に渡して Tool Call を生成可能にする。
        mutation_tools = list(catalog.mutating.values())
        self.remediation_llm = self.llm.bind_tools(mutation_tools)

        # read-only / mutation の ToolNode を分離する。
        self.raw_tool_node = ToolNode(catalog.read_only)
        self.raw_mutation_tool_node = ToolNode(mutation_tools)
        self.read_tools = {tool.name: tool for tool in catalog.read_only}

    async def starter_placeholder(self, state: IncidentState) -> dict:
        """TODO 実装前でも安全に起動できる placeholder。"""
        self.emit_state("starter", state)
        self.emit_event(
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
    async def investigate(self, state: IncidentState) -> dict:
        """LLM に「次に何を観測するか」を判断させる Node。

        実装の目安は 5〜15 行程度。

        やること:
        1. self.emit_state("investigate", state) で現在Stateを画面に出す
        2. SystemMessage + state["messages"] を LLM へ渡す
        3. self.investigator_llm.ainvoke(...) を呼ぶ
        4. response を {"messages": [response]} で返す

        発展:
        - Tool 回数上限に近づいたら結論を促す
        - 独自の調査方針を HumanMessage として追加する
        - State に独自カウンタを追加する

        注意:
        mutation Tool は investigator_llm に bind してはいけない。
        """
        # ===== 模範解答（TODO 2）=====
        self.emit_state("investigate", state)

        messages = [
            SystemMessage(content=INVESTIGATION_SYSTEM_PROMPT),
            *state["messages"],
        ]

        if (
            state["investigation_tool_results"]
            >= self.settings.max_investigation_tool_results
        ):
            self.emit_event(
                "WARN",
                "Investigation observation budget reached; forcing a conclusion",
            )
            messages.append(
                HumanMessage(
                    content=(
                        "観測回数の上限に達しました。これ以上ツールを呼び出さないでください。"
                        "証拠をまとめて調査を終了してください。"
                    )
                )
            )
            response = await self.llm.ainvoke(messages)
        else:
            response = await self.investigator_llm.ainvoke(messages)

        if isinstance(response, AIMessage) and response.tool_calls:
            names = ", ".join(call["name"] for call in response.tool_calls)
            self.emit_event("INFO", f"LLM selected tool(s): {names}")
        else:
            self.emit_event("INFO", "LLM ended the investigation loop")

        return {"messages": [response]}

        raise NotImplementedError("TODO 2: investigate を実装してください")

    # ------------------------------------------------------------------
    # ToolNode wrapper は講師側で完成済み
    # ------------------------------------------------------------------
    async def tools(self, state: IncidentState) -> dict:
        """LLM が選択した read-only Tool を実行し、結果を State に戻す。"""
        self.emit_state("tools", state)
        result = await self.raw_tool_node.ainvoke(state)
        tool_messages = [
            message
            for message in result.get("messages", [])
            if isinstance(message, ToolMessage)
        ]

        for message in tool_messages:
            preview = str(message.content).replace("\n", " ")[:450]
            self.emit_event("INFO", f"Observation from {message.name}: {preview}")

        return {
            **result,
            "investigation_tool_results": (
                state["investigation_tool_results"] + len(tool_messages)
            ),
        }

    # ------------------------------------------------------------------
    # TODO 3: judge を実装する
    # ------------------------------------------------------------------
    async def judge(self, state: IncidentState) -> dict:
        """観測履歴を Diagnosis に変換する Node。

        実装の目安は 5〜15 行程度。

        やること:
        1. self.emit_state("judge", state) で現在Stateを画面に出す
        2. JUDGE_SYSTEM_PROMPT と state["messages"] をまとめる
        3. self.diagnosis_llm.ainvoke(...) を呼ぶ
        4. {"diagnosis": diagnosis, "investigation_tool_results": 0} を返す

        ポイント:
        「調査」と「判断」を Node として分けることで、
        Agent の自由な探索を Graph の明示的な State に戻す。
        """
        # ===== 模範解答（TODO 3）=====
        self.emit_state("judge", state)

        prompt = [
            SystemMessage(content=JUDGE_SYSTEM_PROMPT),
            *state["messages"],
            HumanMessage(content="これまでの結果から、構造化された Diagnosis を作成してください。"),
        ]

        diagnosis = await self.diagnosis_llm.ainvoke(prompt)

        self.emit_event(
            "INFO",
            (
                f"Diagnosis: {diagnosis.root_cause} | "
                f"action={diagnosis.recommended_action} "
                f"target={diagnosis.target_service} "
                f"application={diagnosis.target_application} "
                f"confidence={diagnosis.confidence}"
            ),
        )

        return {
            "diagnosis": diagnosis,
            "approval": "not_required",
            "investigation_tool_results": 0,
            "remediation_action": None,
            "remediation_args": None,
            "remediation_result": None,
        }

        raise NotImplementedError("TODO 3: judge を実装してください")

    # ------------------------------------------------------------------
    # mutation Tool の選択: bind_tools() で本物の Tool Call を作る
    # ------------------------------------------------------------------
    async def plan_remediation(self, state: IncidentState) -> dict:
        """Diagnosis と観測履歴から、実行候補となる mutation Tool Call を生成する。"""
        self.emit_state("plan_remediation", state)

        diagnosis = state["diagnosis"]
        if diagnosis is None:
            raise RuntimeError("plan_remediation node requires diagnosis")

        if diagnosis.recommended_action in {"manual", "none"}:
            self.emit_event(
                "INFO",
                f"No mutation Tool Call required: {diagnosis.recommended_action}",
            )
            return {
                "messages": [
                    AIMessage(
                        content=(
                            "Diagnosis が "
                            f"{diagnosis.recommended_action} を推奨しているため、"
                            "状態変更 Tool は呼び出しません。"
                        )
                    )
                ]
            }

        prompt = [
            SystemMessage(content=REMEDIATION_SYSTEM_PROMPT),
            *state["messages"],
            HumanMessage(
                content=(
                    "構造化された Diagnosis は次のとおりです。\n"
                    + json.dumps(
                        diagnosis.model_dump(mode="json"),
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\nこの Diagnosis と観測結果に基づき、必要なら mutation Tool を 1 つ選んでください。"
                )
            ),
        ]

        response = await self.remediation_llm.ainvoke(prompt)

        if isinstance(response, AIMessage) and len(response.tool_calls) > 1:
            names = ", ".join(call["name"] for call in response.tool_calls)
            self.emit_event(
                "WARN",
                f"LLM proposed multiple mutation tools ({names}); refusing automatic execution",
            )
            response = AIMessage(
                content=(
                    "複数の状態変更 Tool が同時に提案されたため、安全のため自動実行を中止します。"
                    "人間が手動で確認してください。"
                )
            )
        elif isinstance(response, AIMessage) and response.tool_calls:
            call = response.tool_calls[0]
            self.emit_event(
                "INFO",
                f"LLM proposed mutation Tool Call: {call['name']}({call['args']})",
            )
        else:
            self.emit_event("INFO", "LLM proposed no mutation Tool Call")

        return {"messages": [response]}

    # ------------------------------------------------------------------
    # Tool Call がある場合だけ Human Approval へ進む
    # ------------------------------------------------------------------
    def approval(self, state: IncidentState) -> dict:
        """実際の mutation Tool Call を実行する直前で interrupt() する。"""
        self.emit_state("approval", state)

        diagnosis = state["diagnosis"]
        latest = state["messages"][-1]
        if diagnosis is None:
            raise RuntimeError("approval node requires diagnosis")
        if not isinstance(latest, AIMessage) or len(latest.tool_calls) != 1:
            raise RuntimeError("approval node requires exactly one mutation Tool Call")

        tool_call = latest.tool_calls[0]
        args = dict(tool_call["args"])
        action = tool_call["name"]

        payload = ApprovalRequest(
            action=action,
            tool_args=args,
            target_service=str(args.get("service", "none")),
            target_application=str(args.get("application_name", "none")),
            root_cause=diagnosis.root_cause,
            evidence=diagnosis.evidence,
            reason=(
                diagnosis.action_reason
                + f" / LLM が実行候補として {action} を Tool Call しました。"
            ),
        ).model_dump()

        approved = interrupt(payload)

        return {
            "approval": "approved" if bool(approved) else "rejected",
            "remediation_action": action,
            "remediation_args": args,
        }

    def after_approval(
        self,
        state: IncidentState,
    ) -> Literal["mutation_tools", "report"]:
        return "mutation_tools" if state["approval"] == "approved" else "report"

    # ------------------------------------------------------------------
    # Human Approval 後にだけ mutation ToolNode を実行する
    # ------------------------------------------------------------------
    async def mutation_tools(self, state: IncidentState) -> dict:
        """承認済みの AIMessage.tool_calls を ToolNode でそのまま実行する。"""
        self.emit_state("mutation_tools", state)

        latest = state["messages"][-1]
        if not isinstance(latest, AIMessage) or len(latest.tool_calls) != 1:
            raise RuntimeError("mutation_tools node requires exactly one approved Tool Call")

        tool_call = latest.tool_calls[0]
        action = tool_call["name"]
        args = dict(tool_call["args"])

        self.emit_event("WARN", f"Executing approved Tool Call: {action}({args})")
        result = await self.raw_mutation_tool_node.ainvoke(state)
        tool_messages = [
            message
            for message in result.get("messages", [])
            if isinstance(message, ToolMessage)
        ]

        for message in tool_messages:
            preview = str(message.content).replace("\n", " ")[:450]
            self.emit_event("INFO", f"Mutation result from {message.name}: {preview}")

        return {
            **result,
            "remediation_action": action,
            "remediation_args": args,
            "remediation_result": [message.content for message in tool_messages],
        }

    # ------------------------------------------------------------------
    # verify は講師側で完成済み
    # ------------------------------------------------------------------
    async def verify(self, state: IncidentState) -> dict:
        """状態変更後、ユーザー視点の HTTP で本当に直ったか再観測する。"""
        self.emit_state("verify", state)
        http_tool = self.read_tools["http_request"]
        last_result = None

        for attempt in range(1, 7):
            last_result = await http_tool.ainvoke(
                {"path": "/api/members", "method": "GET"}
            )
            status = status_code(last_result)
            self.emit_event("INFO", f"Verification attempt {attempt}/6: HTTP {status}")

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
                        "承認された復旧操作を実行しましたが、復旧確認には引き続き失敗しています。"
                        f"最新の観測結果: {last_result}。"
                        "現在の環境を再調査してください。"
                    )
                )
            ],
        }

    def after_verify(
        self,
        state: IncidentState,
    ) -> Literal["investigate", "report"]:
        verification = state["verification"] or {}
        if verification.get("success"):
            return "report"
        if state["verify_attempts"] <= self.settings.verify_retry_limit:
            return "investigate"
        return "report"

    # ------------------------------------------------------------------
    # report は講師側で完成済み
    # ------------------------------------------------------------------
    async def report(self, state: IncidentState) -> dict:
        """診断・承認・復旧確認を人間向けの結果にまとめる。"""
        self.emit_state("report", state)
        diagnosis = state["diagnosis"]

        if diagnosis is None:
            text = (
                state.get("report")
                or "調査結果: 診断情報を生成できませんでした。人手で確認してください。"
            )
        else:
            evidence = "\n".join(f"- {item}" for item in diagnosis.evidence)
            verification = state["verification"]

            action = state.get("remediation_action")
            args = state.get("remediation_args") or {}

            if state["approval"] == "rejected":
                outcome = "LLM が生成した Tool Call は人間に却下されたため実行していません。"
            elif verification and verification.get("success"):
                outcome = "承認された Tool Call を実行し、HTTP 200で復旧を確認しました。"
            elif action is None and diagnosis.recommended_action == "manual":
                outcome = (
                    "利用可能な mutation Tool では安全に復旧できないため、"
                    "人間へエスカレーションします。"
                )
            elif action is None and diagnosis.recommended_action == "none":
                outcome = "状態変更は不要と判断しました。"
            elif action is None:
                outcome = (
                    "実行可能な mutation Tool Call が生成されなかったため、"
                    "人間へエスカレーションします。"
                )
            else:
                outcome = (
                    "Tool Call 実行後も正常性を確認できませんでした。"
                    "人間へエスカレーションします。"
                )

            reported_action = action or diagnosis.recommended_action
            target = (
                json.dumps(args, ensure_ascii=False)
                if args
                else diagnosis.target_service
            )

            text = (
                "【一次障害対応レポート】\n"
                f"障害: {state['incident']}\n"
                f"推定原因: {diagnosis.root_cause}\n"
                f"確信度: {diagnosis.confidence}\n"
                f"根拠:\n{evidence}\n"
                f"診断上の推奨: {diagnosis.recommended_action}\n"
                f"Tool Call/実施: {reported_action} -> {target}\n"
                f"結果: {outcome}"
            )

        self.emit_event("INFO", "Incident report created")
        return {"report": text}


def route_after_investigate(
    state: IncidentState,
) -> Literal["tools", "judge"]:
    """LLM が Tool call を返したら tools、それ以外なら judge。"""
    latest = state["messages"][-1]
    if isinstance(latest, AIMessage) and latest.tool_calls:
        return "tools"
    return "judge"


def route_after_remediation_plan(
    state: IncidentState,
) -> Literal["approval", "report"]:
    """mutation Tool Call が 1 件あれば approval、なければ report。"""
    latest = state["messages"][-1]
    if isinstance(latest, AIMessage) and len(latest.tool_calls) == 1:
        return "approval"
    return "report"


def status_code(tool_result) -> int | None:
    """MCP / LangChain の Tool result から HTTP status code を取り出す。"""
    if isinstance(tool_result, ToolMessage):
        if tool_result.artifact:
            status = status_code(tool_result.artifact)
            if status is not None:
                return status
        return status_code(tool_result.content)

    if isinstance(tool_result, dict):
        value = tool_result.get("status_code")
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass

        for key in ("structured_content", "content", "text"):
            if key in tool_result:
                status = status_code(tool_result[key])
                if status is not None:
                    return status
        return None

    if isinstance(tool_result, (list, tuple)):
        for item in tool_result:
            status = status_code(item)
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
        return status_code(parsed)

    return None
