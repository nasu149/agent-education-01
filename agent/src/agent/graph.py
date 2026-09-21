"""一次障害対応の「調査 → 診断 → 承認 → 復旧 → 確認 → 報告」を定義する。

Graph は処理単位であるノードと、その間の遷移で構成する。次に何を調べるかは
LLM に任せるが、承認の要否や再試行の条件は Python の分岐で決める。
LLM が直接選べるツールは観測用に限定し、状態変更は interrupt() による
人間の判断を挟んだ後、復旧ノードから実行する。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
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
    """各ノードが読み取り、処理結果を追記・更新する共有状態の型定義。

    messages は LLM・利用者・ツールの会話履歴で、add_messages が新しいメッセージを
    既存履歴に統合する。同じ ID のメッセージは更新される。ほかの項目はノードが返した
    値で置き換えるため、各ノードは State 全体ではなく変更する項目だけを返せる。

    incident は障害の説明、diagnosis は構造化した診断、approval は承認状態。
    verification は復旧確認の結果、verify_attempts は確認ノードを実行した回数、
    investigation_tool_results は調査で受け取ったツール結果数、report は最終報告。
    TypedDict は辞書の形を型として示すもので、生成時の実行時検証は行わない。
    """

    messages: Annotated[list[BaseMessage], add_messages]
    incident: str
    diagnosis: Diagnosis | None
    approval: Literal["not_required", "pending", "approved", "rejected"]
    verification: dict | None
    verify_attempts: int
    investigation_tool_results: int
    report: str | None


INVESTIGATION_SYSTEM_PROMPT = """\
You are the first-response investigator for a small training web system:
Browser -> httpd -> Tomcat(Java Servlet) -> PostgreSQL.

Your goal is NOT to guess quickly. Your goal is to gather enough evidence to
identify the most likely root cause.

Rules:
1. Use only the read-only tools you were given.
2. Prefer observations over assumptions.
3. Correlate at least two pieces of evidence before concluding when possible.
4. Start broad (application response / container status), then inspect logs,
   configuration, or PostgreSQL connection state based on what you observed.
5. If application logs suggest database connection refusal/exhaustion while the
   PostgreSQL container is running, use get_postgres_connection_summary rather
   than assuming the database itself is down.
6. Do not ask to run mutation tools. You do not have them.
7. Do not invent tool output.
8. When you have enough evidence, stop calling tools and write a short sentence
   beginning with "INVESTIGATION_COMPLETE:".
"""


def build_graph(settings: Settings, catalog: ToolCatalog, emit_event, emit_state):
    """設定とツールを受け取り、実行可能な障害対応 Graph を組み立てて返す。

    settings はモデル名や調査回数の上限、catalog は観測用・復旧用の MCP ツール。
    emit_event(level, message) は出来事を記録し、emit_state(node, state) は
    各ノードの開始時点の状態を画面に表示するためのコールバックとして使う。

    調査用 LLM には観測ツールだけを渡し、診断用には Diagnosis の出力形式を指定する。
    内部関数として各ノードと分岐を定義し、最後に接続してコンパイルする。
    InMemorySaver は承認待ちの状態をメモリーに保存する。再開には同じ thread_id が
    必要で、プロセスが終了すると保存内容は失われる。この関数自体は調査を開始しない。
    """

    llm = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        api_key=settings.gemini_api_key,
        temperature=0.1,
        max_retries=2,
        timeout=40,
    )
    investigator_llm = llm.bind_tools(catalog.read_only)
    diagnosis_llm = llm.with_structured_output(Diagnosis, method="json_schema")
    raw_tool_node = ToolNode(catalog.read_only)
    read_tools = {tool.name: tool for tool in catalog.read_only}

    async def investigate(state: IncidentState) -> dict:
        """現在の観測履歴を LLM に渡し、追加調査か調査終了かを判断させる。

        state の messages に調査方針のシステムメッセージを添えて問い合わせる。
        ツール結果数が上限未満なら観測ツールを選べる LLM を使い、上限に達していれば
        ツールを渡さない LLM で結論を求める。ここではツールそのものは実行しない。

        戻り値は最新の応答を含む messages の部分更新。応答に tool_calls があれば
        後続の分岐で tools に進み、なければ judge に進む。
        """
        emit_state("investigate", state)
        tool_results_seen = state["investigation_tool_results"]
        messages = [SystemMessage(content=INVESTIGATION_SYSTEM_PROMPT), *state["messages"]]

        if tool_results_seen >= settings.max_investigation_tool_results:
            emit_event("WARN", "Investigation observation budget reached; forcing a conclusion")
            messages.append(
                HumanMessage(
                    content=(
                        "The investigation observation budget is exhausted. "
                        "Do not call more tools. Summarize the evidence now and begin "
                        "with INVESTIGATION_COMPLETE:"
                    )
                )
            )
            response = await llm.ainvoke(messages)
        else:
            response = await investigator_llm.ainvoke(messages)

        if isinstance(response, AIMessage) and response.tool_calls:
            names = ", ".join(call["name"] for call in response.tool_calls)
            emit_event("INFO", f"LLM selected tool(s): {names}")
        else:
            emit_event("INFO", "LLM ended the flexible investigation loop")
        return {"messages": [response]}

    async def tools(state: IncidentState) -> dict:
        """LLM が要求した観測ツールを ToolNode から実行し、結果を State に追加する。

        入力はツール呼び出し要求を含む state。ToolNode には観測用ツールだけを登録して
        いるため、復旧ツールはこのノードから利用できない。
        得られた ToolMessage の先頭部分をイベントに記録し、その件数を
        investigation_tool_results に加えた部分更新を返す。その後は再び investigate に戻る。
        """
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
            "investigation_tool_results": state["investigation_tool_results"] + len(tool_messages),
        }

    async def judge(state: IncidentState) -> dict:
        """調査履歴を基に、原因・根拠・復旧案を Diagnosis の形式に整理する。

        LLM に会話とツール結果だけを根拠にするよう指示し、起動・再起動・DB 接続切断・
        手動対応・操作不要から復旧案を選ばせる。ここでは追加ツールや復旧操作を実行しない。
        戻り値には診断結果と、ゼロに戻した調査ツール結果数を含める。
        カウンターを戻すことで、復旧確認に失敗した後の再調査で新たに観測できる。
        """
        emit_state("judge", state)
        prompt = [
            SystemMessage(
                content=(
                    "You are the decision stage of an incident-response workflow. "
                    "Use ONLY the supplied conversation and tool results. Produce a Diagnosis. "
                    "Choose start_container only when a target container is observed stopped/exited. "
                    "Choose restart_container only when a running service clearly needs a restart "
                    "and restart is sufficient. Choose terminate_postgres_connections only when "
                    "get_postgres_connection_summary shows an abnormal number of sessions from a "
                    "specific application_name and the evidence indicates PostgreSQL connection "
                    "exhaustion. For that action set target_service='postgres' and set "
                    "target_application to the exact observed application_name. Choose manual when "
                    "the required repair is configuration change, credential repair, or anything "
                    "outside the safe actions. Choose none when no action is required. Never invent "
                    "evidence or an application_name."
                )
            ),
            *state["messages"],
            HumanMessage(content="Produce the structured diagnosis now."),
        ]
        diagnosis = await diagnosis_llm.ainvoke(prompt)
        emit_event(
            "INFO",
            (
                f"Diagnosis: {diagnosis.root_cause} | action="
                f"{diagnosis.recommended_action} target={diagnosis.target_service} "
                f"application={diagnosis.target_application} confidence={diagnosis.confidence}"
            ),
        )
        return {
            "diagnosis": diagnosis,
            "investigation_tool_results": 0,
        }

    def after_judge(state: IncidentState) -> Literal["approval", "report"]:
        """診断の提案内容から、承認依頼へ進むか、そのまま報告するかを決める。

        コンテナ起動・再起動・DB 接続切断の提案は状態変更を伴うため approval を返す。
        手動対応・操作不要、または診断がない場合は report を返す。
        LLM を呼ばず、診断済みの値に対する固定の条件で遷移先を選ぶ。
        """
        diagnosis = state["diagnosis"]
        if diagnosis and diagnosis.recommended_action in {
            "start_container",
            "restart_container",
            "terminate_postgres_connections",
        }:
            return "approval"
        return "report"

    def approval(state: IncidentState) -> dict:
        """復旧案と根拠を人間に提示し、判断が届くまで Graph を一時停止する。

        診断から ApprovalRequest を作り、その辞書を interrupt() に渡す。
        呼び出し側が Command(resume=判断値) で同じ実行を再開すると、その値が
        interrupt() の戻り値になり、approved または rejected を State に返す。

        診断がなければ RuntimeError。再開時はノードの先頭から処理が再実行されるため、
        interrupt() より前にコンテナ再起動などの状態変更を置かないこと。
        """
        emit_state("approval", state)
        diagnosis = state["diagnosis"]
        if diagnosis is None:
            raise RuntimeError("approval node requires diagnosis")

        payload = ApprovalRequest(
            action=diagnosis.recommended_action,
            target_service=diagnosis.target_service,
            target_application=diagnosis.target_application,
            root_cause=diagnosis.root_cause,
            evidence=diagnosis.evidence,
            reason=diagnosis.action_reason,
        ).model_dump()
        approved = interrupt(payload)
        return {"approval": "approved" if bool(approved) else "rejected"}

    def after_approval(state: IncidentState) -> Literal["remediate", "report"]:
        """承認された場合だけ復旧へ進め、それ以外は報告へ進める。

        state['approval'] が approved と完全に一致すれば remediate を返す。
        rejected など、ほかの状態では report を返し、復旧操作を呼び出さない。
        """
        return "remediate" if state["approval"] == "approved" else "report"

    async def remediate(state: IncidentState) -> dict:
        """承認された診断内容に対応する MCP の復旧ツールを 1 回呼び出す。

        診断の recommended_action を catalog.mutating から引き、DB 接続切断なら
        application_name、それ以外なら service を引数として渡す。新たな操作を
        LLM に選ばせる処理ではない。診断・対応ツール・必要な対象がなければ RuntimeError。

        戻り値は実行した操作と結果を記した HumanMessage の部分更新。
        承認済みであることは直前の after_approval の分岐で保証する構成なので、
        このノードを呼ぶ新しい経路を作る場合も承認を迂回させないこと。
        """
        emit_state("remediate", state)
        diagnosis = state["diagnosis"]
        if diagnosis is None:
            raise RuntimeError("remediate node requires diagnosis")
        if diagnosis.recommended_action not in catalog.mutating:
            raise RuntimeError(f"unsupported remediation: {diagnosis.recommended_action}")

        action = diagnosis.recommended_action
        if action == "terminate_postgres_connections":
            if not diagnosis.target_application or diagnosis.target_application == "none":
                raise RuntimeError("PostgreSQL connection termination requires target_application")
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

    async def verify(state: IncidentState) -> dict:
        """復旧操作後に HTTP を再観測し、アプリが正常に応答するかを確認する。

        http_request で /api/members を最大 6 回確認し、HTTP 200 なら成功として返す。
        失敗した回の後は 2 秒待機し、サービスの起動に時間がかかる場合に対応する。
        全回失敗した場合は、最新の観測と再調査を促すメッセージを返す。

        verification に成功・失敗と観測結果を入れ、verify_attempts を 1 増やす。
        このカウンターは HTTP の個別リクエスト数ではなく、確認ノードの実行回数である。
        再調査に進むかどうかは after_verify が決める。
        """
        emit_state("verify", state)
        http_tool = read_tools["http_request"]
        last_result = None

        for attempt in range(1, 7):
            last_result = await http_tool.ainvoke({"path": "/api/members", "method": "GET"})
            status = _status_code(last_result)
            emit_event("INFO", f"Verification attempt {attempt}/6: HTTP {status}")
            if status == 200:
                return {
                    "verification": {"success": True, "observation": last_result},
                    "verify_attempts": state["verify_attempts"] + 1,
                }
            await asyncio.sleep(2)

        return {
            "verification": {"success": False, "observation": last_result},
            "verify_attempts": state["verify_attempts"] + 1,
            "messages": [
                HumanMessage(
                    content=(
                        "The approved remediation was executed, but verification still "
                        f"failed. Latest observation: {last_result}. Re-investigate using "
                        "the current environment; do not assume the previous diagnosis "
                        "is still sufficient."
                    )
                )
            ],
        }

    def after_verify(state: IncidentState) -> Literal["investigate", "report"]:
        """復旧確認の結果と実行回数から、再調査または報告へ振り分ける。

        成功なら report。失敗していても verify_attempts が verify_retry_limit 以下なら
        investigate に戻る。それを超えた場合は report に進み、無制限の再調査を防ぐ。
        例えば上限が 1 なら、最初の確認失敗後に 1 回だけ再調査を許可する。
        """
        verification = state["verification"] or {}
        if verification.get("success"):
            return "report"
        if state["verify_attempts"] <= settings.verify_retry_limit:
            return "investigate"
        return "report"

    async def report(state: IncidentState) -> dict:
        """診断・承認・復旧確認の結果を、日本語の最終報告にまとめる。

        原因、確信度、根拠、提案した操作と対象、復旧結果を固定の書式で組み立てる。
        却下、復旧成功、手動対応、操作不要、復旧未確認を分けて説明し、診断がなければ
        人手での確認を案内する。追加の LLM 呼び出しや復旧操作は行わない。
        戻り値は report の部分更新で、このノードの後に Graph を終了する。
        """
        emit_state("report", state)
        diagnosis = state["diagnosis"]
        if diagnosis is None:
            text = "調査結果: 診断情報を生成できませんでした。人手で確認してください。"
        else:
            evidence = "\n".join(f"- {item}" for item in diagnosis.evidence)
            verification = state["verification"]
            if state["approval"] == "rejected":
                outcome = "復旧操作は人間に却下されたため実行していません。"
            elif verification and verification.get("success"):
                outcome = "承認された復旧操作を実行し、HTTP 200で復旧を確認しました。"
            elif diagnosis.recommended_action == "manual":
                outcome = "Agentの許可された操作範囲では復旧できないため、人間へエスカレーションします。"
            elif diagnosis.recommended_action == "none":
                outcome = "状態変更は不要と判断しました。"
            else:
                outcome = "自動復旧後も正常性を確認できませんでした。人間へエスカレーションします。"

            target = diagnosis.target_service
            if diagnosis.target_application != "none":
                target += f" / application={diagnosis.target_application}"

            text = (
                f"【一次障害対応レポート】\n"
                f"障害: {state['incident']}\n"
                f"推定原因: {diagnosis.root_cause}\n"
                f"確信度: {diagnosis.confidence}\n"
                f"根拠:\n{evidence}\n"
                f"提案/実施: {diagnosis.recommended_action} -> {target}\n"
                f"結果: {outcome}"
            )
        emit_event("INFO", "Incident report created")
        return {"report": text}

    builder = StateGraph(IncidentState)
    builder.add_node("investigate", investigate)
    builder.add_node("tools", tools)
    builder.add_node("judge", judge)
    builder.add_node("approval", approval)
    builder.add_node("remediate", remediate)
    builder.add_node("verify", verify)
    builder.add_node("report", report)

    builder.add_edge(START, "investigate")
    builder.add_conditional_edges(
        "investigate",
        _route_after_investigate,
        {"tools": "tools", "judge": "judge"},
    )
    builder.add_edge("tools", "investigate")
    builder.add_conditional_edges(
        "judge",
        after_judge,
        {"approval": "approval", "report": "report"},
    )
    builder.add_conditional_edges(
        "approval",
        after_approval,
        {"remediate": "remediate", "report": "report"},
    )
    builder.add_edge("remediate", "verify")
    builder.add_conditional_edges(
        "verify",
        after_verify,
        {"investigate": "investigate", "report": "report"},
    )
    builder.add_edge("report", END)

    return builder.compile(checkpointer=InMemorySaver())


def _route_after_investigate(state: IncidentState) -> Literal["tools", "judge"]:
    """調査 LLM の最新応答を見て、観測ツールの実行か診断へ進むかを決める。

    state の末尾メッセージが AIMessage で、tool_calls があれば tools を返す。
    それ以外は judge を返す。本文の完了宣言ではなく、ツール呼び出し要求の有無で
    判断する。messages に少なくとも 1 件の応答があることを前提にする。
    """
    latest = state["messages"][-1]
    if isinstance(latest, AIMessage) and latest.tool_calls:
        return "tools"
    return "judge"


def _status_code(tool_result) -> int | None:
    """形式が異なる MCP / LangChain のツール結果から、HTTP ステータスを取り出す。

    ToolMessage は artifact を優先し、見つからなければ content を調べる。
    辞書は status_code と構造化データ・本文、リストやタプルは各要素を再帰的に探す。
    文字列はまず JSON として読み、JSON でなければ status_code=500 のような表記を探す。

    最初に見つかった整数のステータスを返し、取得できなければ None を返す。
    通信そのものを行う関数ではなく、取得済みの結果の形式差を吸収するために使う。
    """
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
            match = __import__("re").search(r"status_code['\"]?\s*[:=]\s*(\d+)", tool_result)
            return int(match.group(1)) if match else None
        return _status_code(parsed)

    return None
