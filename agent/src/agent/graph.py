"""LangGraph の Node / Edge の配線だけを定義する。

Node の中身は nodes.py に分離し、このファイルでは
「どの Node が、どの条件で、次のどの Node へ進むか」に集中する。

TODO コメントは研修の問題文なので、基本的に削除せず、その直下へ実装を書く。
"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from agent.config import Settings
from agent.mcp_tools import ToolCatalog
from agent.nodes import (
    IncidentNodes,
    IncidentState,
    route_after_investigate,
    status_code,
)

# 既存テストや教材から参照している名前を維持する。
_route_after_investigate = route_after_investigate
_status_code = status_code


def build_graph(
    settings: Settings,
    catalog: ToolCatalog,
    emit_event,
    emit_state,
):
    """研修用 Graph を構築する。

    nodes.py:
        各 Node が「何をするか」を実装する。

    graph.py:
        各 Node を「どう繋ぐか」を実装する。

    受講者がこのファイルで編集する主要ポイント:
    - TODO 5: StateGraph の配線
    """

    nodes = IncidentNodes(
        settings=settings,
        catalog=catalog,
        emit_event=emit_event,
        emit_state=emit_state,
    )

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
    # - judge の後は nodes.after_judge
    # - approval の後は nodes.after_approval
    # - remediate -> verify
    # - verify の後は nodes.after_verify
    #
    # Node の登録には、nodes.investigate のような bound method を渡せる。
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
    builder.add_node("starter", nodes.starter_placeholder)
    builder.add_edge(START, "starter")
    builder.add_edge("starter", END)

    return builder.compile(checkpointer=InMemorySaver())
