> **このブランチ `training/disk-full-hitl-tool-call` は HITL Tool Calling の派生実装です。**  
> `training/disk-full-solution` を土台に mutation MCP Tool を LLM に `bind_tools()` し、  
> 生成された Tool Call を実行する直前で `interrupt()` して人間承認を挟みます。

# AI Agent研修 - Disk Full 拡張課題

> **このブランチ `training/disk-full` は受講者向けの問題版です。**  
> 完成済みの障害対応 Agent を土台に、disk-full を観測・判断・復旧できる能力を追加します。  
> TODO D1〜D5 を残したまま、その直下へ実装してください。

## シナリオ

~~~text
Browser -> httpd -> Tomcat -> PostgreSQL
~~~

Tomcat には小さな `/training-disk` があり、各リクエストで監査ログを書きます。
夜間に古い監査ログが大量生成されると、全コンテナが running のまま
`GET /api/members` が HTTP 500 / No space left on device になります。

## 今回の課題

主に編集する場所:

~~~text
agent/src/mcp_server/server.py
agent/src/agent/mcp_tools.py
agent/src/agent/models.py
agent/src/agent/nodes.py
~~~

1. **TODO D1**: `get_disk_usage()`
2. **TODO D2**: `list_large_files()`
3. **TODO D3**: `cleanup_training_logs()`
4. **TODO D4**: read-only / mutation の分類
5. **TODO D5**: Diagnosis / Prompt / Human Approval routing への組み込み

既存の LangGraph、HITL、verify、report は完成済みです。

## Safety

`cleanup_training_logs()` は自由な `rm` Toolにしません。

~~~text
削除可能:
  /training-disk/archive/training-*.log

削除不可:
  /training-disk/audit/member-audit.log
  任意 path
  OS / Tomcat / WAR のファイル
~~~

mutation Tool は復旧計画用 LLM に `bind_tools()` しますが、`bind_tools()` 自体は実行しません。
LLM が生成した `AIMessage.tool_calls` は Human Approval で必ず停止し、承認後にだけ ToolNode が実行します。

詳細: [docs/DISK_FULL.md](docs/DISK_FULL.md)

## 関連ドキュメント

- [MCP Tool Reference](docs/MCP_TOOLS.md) - 全 MCP Tool の一覧、引数、戻り値、安全制約、LangGraph からの呼び出し方
- [Architecture](docs/ARCHITECTURE.md) - LangGraph / MCP / Human Approval の全体構成
- [Disk Full](docs/DISK_FULL.md) - Disk Full 課題のシナリオと要件
- [Disk Full 模範解答](docs/DISK_FULL_SOLUTION.md) - TODO D1〜D5 の解答方針

## 講師側の準備

Linux / Oracle Linux:

~~~bash
./scripts/prepare_disk_full_training.sh
~~~

Windows PowerShell:

~~~powershell
.\scripts\prepare_disk_full_training.ps1
~~~

## 障害注入

~~~bash
./scripts/battle_inject_fault.sh disk-full
~~~

~~~powershell
.\scripts\battle_inject_fault.ps1 disk-full
~~~

## Reset

~~~bash
./scripts/battle_reset.sh
~~~

~~~powershell
.\scripts\battle_reset.ps1
~~~

## 完成時の期待フロー

~~~text
HTTP 500
  ↓
Tomcat log: No space left on device
  ↓
get_disk_usage
  ↓
list_large_files
  ↓
Diagnosis
  ↓
plan_remediation
  ↓
LLM Tool Call: cleanup_training_logs(service="tomcat")
  ↓
Human Approval / interrupt()
  ↓
mutation ToolNode
  ↓
verify -> HTTP 200
~~~

障害名を見て答えを hard-code せず、観測結果から判断してください。
