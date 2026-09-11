"""Starter LangGraph for the afternoon hands-on.

Infrastructure, MCP, monitoring and UI are complete. Learners edit this file to
turn the starter workflow into the completed incident-response Agent.

This starter intentionally RUNS before any TODO is completed: when an incident
occurs it records a teaching message and exits safely without mutating anything.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from agent.config import Settings
from agent.mcp_tools import ToolCatalog
from agent.models import Diagnosis


class IncidentState(TypedDict):
    """Shared incident work record.

    TODO during the exercise: discuss which fields belong in State and why.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    incident: str
    diagnosis: Diagnosis | None
    approval: str
    verification: dict | None
    verify_attempts: int
    report: str | None


def build_graph(settings: Settings, catalog: ToolCatalog, emit_event):
    """Build the safe starter graph.

    The `ToolNode` is already instantiated so learners can focus on Agent design,
    not MCP plumbing. Follow `docs/HANDS_ON.md` to complete each step.
    """

    # The instructor has already prepared the MCP server and loaded its tools.
    # Only the read-only list should ever be offered to the investigation LLM.
    tool_node = ToolNode(catalog.read_only)

    async def investigate_placeholder(state: IncidentState) -> dict:
        """Safe placeholder used before learners implement the agentic loop."""
        emit_event(
            "WARN",
            "Starter graph detected an incident. Investigation TODO is not implemented yet.",
        )
        return {
            "report": (
                "【Starter Graph】障害を検知しましたが、investigate / ToolNode / "
                "conditional edge は午後ハンズオンで実装します。"
            )
        }

    # TODO 1:
    #   ChatGoogleGenerativeAI を生成し、read-only tools だけ bind する。
    #
    # TODO 2:
    #   investigate node から LLM を呼び、Tool call があれば ToolNode へ、
    #   調査完了なら judge へ進む conditional edge を作る。
    #
    # TODO 3:
    #   judge -> approval -> remediate -> verify -> report を段階的に追加する。
    #
    # TODO 4:
    #   approval では interrupt()、remediate では catalog.mutating を使う。
    #   mutation tool を LLM の bind_tools() に追加してはいけない。
    #
    # TODO 5:
    #   verify が失敗した場合に investigate へ戻る edge を追加する。

    builder = StateGraph(IncidentState)
    builder.add_node("investigate", investigate_placeholder)

    # `tool_node` is intentionally unused in Step 0. It is the real LangGraph
    # ToolNode learners connect in Step 1.
    _ = tool_node

    builder.add_edge(START, "investigate")
    builder.add_edge("investigate", END)
    return builder.compile(checkpointer=InMemorySaver())
