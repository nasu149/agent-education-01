# Architecture - HITL before mutation Tool execution

このブランチは、mutation MCP Tool を LLM に `bind_tools()` しつつ、**実行直前で必ず Human-in-the-loop を挟む**構成です。

```text
Browser -> httpd -> Tomcat -> PostgreSQL

Ordinary health checker
  |
  v
investigate
  |
  +--> read-only ToolNode --> investigate
  |
  v
judge
  |
  v
plan_remediation
  |
  | remediation_llm = llm.bind_tools(mutation_tools)
  | AIMessage.tool_calls
  v
approval
  |
  | interrupt({tool name, exact args, evidence})
  | reject -----------------------------> report
  |
  | approve
  v
mutation_tools
  |
  | ToolNode(mutation_tools)
  | MCP Tool executes here for the first time
  v
verify
  |
  +-- failure --> investigate
  |
  v
report -> END
```

## 重要な境界

- `bind_tools()` は Tool を実行しない。名前・description・input schema を LLM に渡し、Tool Call を生成可能にするだけ。
- read-only Tool は `investigate` から自動実行してよい。
- mutation Tool は `plan_remediation` の LLM に bind されるが、そこで返るのは `AIMessage.tool_calls`。
- `approval` はその実際の Tool 名と引数を表示して `interrupt()` する。
- 承認されるまで mutation ToolNode には到達しない。
- 承認後は、承認対象になった同じ `AIMessage.tool_calls` を ToolNode が実行する。
- 複数 mutation Tool Call が同時に生成された場合は実行しない。
- MCP は接続層、LangGraph は実行制御、LLM は Tool 選択、人間は状態変更の最終許可を担当する。
