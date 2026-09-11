"""Completed LangGraph for the incident-response workshop.

The graph deliberately combines deterministic workflow control with one
agentic investigation loop. Read-only tools are model-selectable. Mutating tools
are available only to the remediation node after a LangGraph interrupt.
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
    """Shared work record carried between LangGraph nodes."""

    messages: Annotated[list[BaseMessage], add_messages]
    incident: str
    diagnosis: Diagnosis | None
    approval: Literal["not_required", "pending", "approved", "rejected"]
    verification: dict | None
    verify_attempts: int
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
4. Start broad (application response / container status), then inspect logs or
   configuration based on what you observed.
5. Do not ask to run start/restart commands. You do not have mutation tools.
6. Do not invent tool output.
7. When you have enough evidence, stop calling tools and write a short sentence
   beginning with "INVESTIGATION_COMPLETE:".
"""


def build_graph(settings: Settings, catalog: ToolCatalog, emit_event):
    """Compile and return the completed educational incident graph."""

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
        """Let the LLM choose the next read-only observation or finish investigation."""
        tool_results_seen = sum(isinstance(message, ToolMessage) for message in state["messages"])
        messages = [SystemMessage(content=INVESTIGATION_SYSTEM_PROMPT), *state["messages"]]

        # Bound exploration: once enough observations exist, remove tools and force
        # the model to summarize what it already knows instead of looping forever.
        if tool_results_seen >= settings.max_investigation_tool_results:
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
        """Execute the LLM's selected read-only tools through LangGraph ToolNode."""
        result = await raw_tool_node.ainvoke(state)
        for message in result.get("messages", []):
            if isinstance(message, ToolMessage):
                preview = str(message.content).replace("\n", " ")[:450]
                emit_event("INFO", f"Observation from {message.name}: {preview}")
        return result

    async def judge(state: IncidentState) -> dict:
        """Convert free-form observations into a strict, inspectable decision."""
        prompt = [
            SystemMessage(
                content=(
                    "You are the decision stage of an incident-response workflow. "
                    "Use ONLY the supplied conversation and tool results. Produce a "
                    "Diagnosis. Choose start_container only when a target container is "
                    "observed stopped/exited. Choose restart_container only when a "
                    "running service clearly needs a restart and restart is sufficient. "
                    "Choose manual when the required repair is configuration change, "
                    "credential repair, or anything outside those two safe actions. "
                    "Choose none when no action is required. Never invent evidence."
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
                f"confidence={diagnosis.confidence}"
            ),
        )
        return {"diagnosis": diagnosis}

    def after_judge(state: IncidentState) -> Literal["approval", "report"]:
        diagnosis = state["diagnosis"]
        if diagnosis and diagnosis.recommended_action in {"start_container", "restart_container"}:
            return "approval"
        return "report"

    def approval(state: IncidentState) -> dict:
        """Pause execution before any mutation and wait for a human decision."""
        diagnosis = state["diagnosis"]
        if diagnosis is None:
            raise RuntimeError("approval node requires diagnosis")

        payload = ApprovalRequest(
            action=diagnosis.recommended_action,
            target_service=diagnosis.target_service,
            root_cause=diagnosis.root_cause,
            evidence=diagnosis.evidence,
            reason=diagnosis.action_reason,
        ).model_dump()
        approved = interrupt(payload)
        return {"approval": "approved" if bool(approved) else "rejected"}

    def after_approval(state: IncidentState) -> Literal["remediate", "report"]:
        return "remediate" if state["approval"] == "approved" else "report"

    async def remediate(state: IncidentState) -> dict:
        """Execute exactly the human-approved mutation through MCP."""
        diagnosis = state["diagnosis"]
        if diagnosis is None:
            raise RuntimeError("remediate node requires diagnosis")
        if diagnosis.recommended_action not in catalog.mutating:
            raise RuntimeError(f"unsupported remediation: {diagnosis.recommended_action}")
        if diagnosis.target_service == "none":
            raise RuntimeError("remediation requires a target service")

        emit_event(
            "WARN",
            f"Executing approved action: {diagnosis.recommended_action}({diagnosis.target_service})",
        )
        result = await catalog.mutating[diagnosis.recommended_action].ainvoke(
            {"service": diagnosis.target_service}
        )
        emit_event("INFO", f"Remediation result: {str(result)[:450]}")
        return {
            "messages": [
                HumanMessage(
                    content=(
                        "Human-approved remediation executed: "
                        f"{diagnosis.recommended_action}({diagnosis.target_service}). "
                        f"Tool result: {result}"
                    )
                )
            ]
        }

    async def verify(state: IncidentState) -> dict:
        """Re-observe the application after action, allowing service startup time."""
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
        verification = state["verification"] or {}
        if verification.get("success"):
            return "report"
        if state["verify_attempts"] <= settings.verify_retry_limit:
            return "investigate"
        return "report"

    async def report(state: IncidentState) -> dict:
        """Produce a concise operational report without another autonomous action."""
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

            text = (
                f"【一次障害対応レポート】\n"
                f"障害: {state['incident']}\n"
                f"推定原因: {diagnosis.root_cause}\n"
                f"確信度: {diagnosis.confidence}\n"
                f"根拠:\n{evidence}\n"
                f"提案/実施: {diagnosis.recommended_action} -> {diagnosis.target_service}\n"
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
    """Route to ToolNode when the latest AI message requests a tool."""
    latest = state["messages"][-1]
    if isinstance(latest, AIMessage) and latest.tool_calls:
        return "tools"
    return "judge"


def _status_code(tool_result) -> int | None:
    """Extract status code from MCP/LangChain tool output shapes."""
    if isinstance(tool_result, dict):
        value = tool_result.get("status_code")
        return int(value) if value is not None else None

    if isinstance(tool_result, str):
        try:
            parsed = json.loads(tool_result)
        except json.JSONDecodeError:
            match = __import__("re").search(r"status_code['\"]?\s*[:=]\s*(\d+)", tool_result)
            return int(match.group(1)) if match else None
        if isinstance(parsed, dict) and parsed.get("status_code") is not None:
            return int(parsed["status_code"])
    return None
