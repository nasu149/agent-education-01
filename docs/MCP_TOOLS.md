# MCP Tool Reference

この文書は、`training/disk-full-hitl-tool-call` ブランチで利用する MCP Tool の一覧と役割をまとめたリファレンスです。

実装の正本は次の2ファイルです。

- `agent/src/mcp_server/server.py`: MCP Server と各 Tool の実装
- `agent/src/agent/mcp_tools.py`: MCP Tool の取得と read-only / mutation の分類

## 全体像

この教材では、MCP は **Agent が外部環境を観測・操作するための接続層** として使います。
MCP 自体が Agent の判断を行うわけではありません。

```text
Gemini / LangGraph
       |
       |  bind_tools(read_only)
       v
investigator_llm
       |
       | AIMessage.tool_calls
       v
    ToolNode
       |
       | MCP (stdio)
       v
operations-training-server
       |
       +--> HTTP
       +--> Docker
       +--> PostgreSQL
       +--> /training-disk
```

MCP Server は `FastMCP("operations-training-server")` として実装され、
Agent 側の `MultiServerMCPClient` が Python 子プロセスとして起動し、stdio で接続します。

`load_tool_catalog()` は MCP Server から Tool 定義を取得した後、Tool を次の2種類に分けます。

- **read-only Tool**: 調査用 LLM に bind し、ToolNode で自動実行可能
- **mutation Tool**: 復旧計画用 LLM に bind するが、生成された Tool Call は Human Approval 前には実行しない

このブランチでは「Tool を LLM に見せること」と「Tool を実行すること」を分離します。
mutation Tool の description / input schema は `bind_tools()` で LLM に渡し、
実行権限は LangGraph の `interrupt()` と ToolNode の配線で制御します。

## Tool 一覧

### Read-only Tool

| Tool | 主な用途 | 主な引数 |
|---|---|---|
| `http_request` | Web アプリの HTTP 応答確認 | `path`, `method` |
| `list_containers` | httpd / tomcat / postgres の稼働状態一覧 | なし |
| `inspect_container` | 1コンテナの状態・Network・一部環境変数確認 | `service` |
| `get_container_logs` | コンテナの直近ログ確認 | `service`, `tail` |
| `read_config` | 許可済み設定の確認 | `config_name` |
| `get_postgres_connection_summary` | PostgreSQL 接続数・接続元の確認 | なし |
| `get_disk_usage` | Tomcat の `/training-disk` 使用率確認 | `service` |
| `list_large_files` | `/training-disk` 内の大容量ファイル確認 | `service`, `limit` |

### Mutation Tool

| Tool | 主な用途 | 主な引数 |
|---|---|---|
| `start_container` | 停止コンテナを起動 | `service` |
| `restart_container` | コンテナを再起動 | `service` |
| `terminate_postgres_connections` | 許可された PostgreSQL 接続を切断 | `application_name` |
| `cleanup_training_logs` | disk-full 用の古い模擬ログを削除 | `service` |

---

# Read-only Tool 詳細

## 1. http_request

### 目的

Agent と同じネットワークから研修用 Web アプリへ GET を送り、
ユーザー視点でアプリケーションが正常に応答しているか確認します。

### 入力

```text
path: str = "/api/members"
method: str = "GET"
```

- `path` は `/` から始まる必要があります。
- `method` は GET のみ許可されます。

### 戻り値

成功時の例:

```json
{
  "url": "http://httpd/api/members",
  "status_code": 200,
  "body": "..."
}
```

通信失敗時は `error` と `detail` を返します。

### 安全制約

- POST / PUT / DELETE 等は実行できません。
-レスポンス本文は最大 2000 文字です。

### 調査での利用例

- 最初に HTTP 500 を再確認する
- 復旧後に HTTP 200 へ戻ったか確認する

---

## 2. list_containers

### 目的

研修対象コンテナの存在と稼働状態を一覧で確認します。

既定の対象:

- `httpd`
- `tomcat`
- `postgres`

### 入力

なし。

### 戻り値

各サービスについて次の情報を返します。

```text
service
name
status
image
```

コンテナが見つからない場合は `status: "not_found"` と詳細を返します。

### 調査での利用例

障害調査の最初に、

- Tomcat が停止していないか
- PostgreSQL が停止していないか
- 全コンテナが running なのか

を広く確認する用途に向いています。

---

## 3. inspect_container

### 目的

指定した1サービスについて、Docker 上の状態を詳しく確認します。

### 入力

```text
service: str
```

許可されたサービス名のみ指定可能です。

### 戻り値

主に次を返します。

- container status
- health status
- port
- network
- IP address
- network alias
- 許可された一部の環境変数

公開する環境変数は次だけです。

```text
DB_HOST
DB_PORT
DB_NAME
DB_USER
```

### 安全制約

DB パスワード等の秘密情報は返しません。

### 調査での利用例

- Tomcat がどの PostgreSQL を参照しているか
- Network に正しく参加しているか
- コンテナは running だが health が異常ではないか

などを確認します。

---

## 4. get_container_logs

### 目的

対象コンテナの直近ログを取得し、障害原因の手掛かりを探します。

### 入力

```text
service: str
tail: int = 80
```

`tail` は実装側で 1〜200 行に制限されます。

### 戻り値

タイムスタンプ付きのログ文字列です。

### 調査での利用例

Tomcat ログから、

```text
No space left on device
audit storage unavailable
audit_write_failed
```

などを発見し、disk-full 調査へ進む判断材料にします。

### 安全制約

任意ログファイルをパス指定して読む Tool ではなく、Docker のコンテナログのみ取得します。

---

## 5. read_config

### 目的

事前に許可された設定だけを読み取り、接続先設定の誤りなどを調べます。

### 入力

```text
config_name: str
```

指定できる値は次だけです。

#### httpd_proxy

httpd の Proxy 設定:

```text
/usr/local/apache2/conf/extra/member-app.conf
```

を読み取ります。

#### tomcat_database

Tomcat の次の環境変数を読み取ります。

```text
DB_HOST
DB_PORT
DB_NAME
DB_USER
```

### 安全制約

`read_file(path)` のような任意ファイル読み取り機能はありません。
DB パスワードも返しません。

---

## 6. get_postgres_connection_summary

### 目的

PostgreSQL の接続枯渇を調査します。

### 入力

なし。

### 戻り値

主に次を返します。

```text
max_connections
superuser_reserved_connections
ordinary_connection_capacity
observed_connections_excluding_this_mcp_session
activity
```

`activity` では `pg_stat_activity` を次の単位で集計します。

- database
- username
- application_name
- client_addr
- state

### 特徴

LLM から SQL は受け取りません。

SQL は MCP Server 内に固定されており、
「LLM に任意 SQL を実行させる」設計にはなっていません。

### 調査での利用例

PostgreSQL コンテナ自体は running なのに Tomcat が DB 接続エラーになっている場合、

- 接続上限に達していないか
- 特定の application_name が大量接続していないか

を確認します。

---

## 7. get_disk_usage

### 目的

Tomcat の研修専用ディスク `/training-disk` の使用率を確認します。

### 入力

```text
service: str = "tomcat"
```

### 戻り値

`df -Pk /training-disk` の結果を構造化して返します。

```text
service
path
filesystem
size_kb
used_kb
available_kb
use_percent
mount_point
```

### 安全制約

- service は Tomcat 固定です。
- LLM は任意 path を指定できません。
- 対象パスは `/training-disk` に限定されています。

### 調査での利用例

Tomcat ログに `No space left on device` が出た場合、
実際にディスク使用率が高いか観測します。

---

## 8. list_large_files

### 目的

Tomcat の `/training-disk` 配下で容量を占有しているファイルを調べます。

### 入力

```text
service: str = "tomcat"
limit: int = 10
```

`limit` は 1〜20 に丸められます。

### 戻り値

```json
{
  "service": "tomcat",
  "path": "/training-disk",
  "files": [
    {
      "path": "/training-disk/archive/training-001.log",
      "size_kb": 12345
    }
  ],
  "command_exit_code": 0
}
```

### 安全制約

LLM から指定できないもの:

- 任意 path
- 任意 shell command

検索対象は `/training-disk` に固定されています。

### 調査での利用例

`get_disk_usage` で高使用率を確認した後、
何が容量を占有しているか特定します。

---

# Mutation Tool 詳細

Mutation Tool は **investigator_llm には bind しません**が、復旧計画専用の
`remediation_llm` には bind します。

```text
investigate
    ↓
judge / Diagnosis
    ↓
remediation_llm.bind_tools(mutation tools)
    ↓
AIMessage.tool_calls   ← まだ実行されていない
    ↓
Human Approval / interrupt()
    ↓ approve
ToolNode(mutation tools)
    ↓
MCP Tool 実行
```

`bind_tools()` は実行ではなく Tool Calling 用の定義提供です。
実際の状態変更は Human Approval 後の ToolNode で初めて発生します。

## 9. start_container

### 目的

停止している対象コンテナを起動します。

### 入力

```text
service: str
```

### 戻り値

```text
service
status
action = "start"
```

### 安全制約

許可された対象サービスだけを操作できます。

---

## 10. restart_container

### 目的

対象コンテナを再起動します。

### 入力

```text
service: str
```

### 戻り値

```text
service
status
action = "restart"
```

### 注意

「なんとなく再起動する」のではなく、
`judge` が観測結果から再起動が必要と判断し、人間が承認した場合だけ使います。

---

## 11. terminate_postgres_connections

### 目的

DB connection exhaustion の原因となっている、明示的に許可された PostgreSQL 接続だけを切断します。

### 入力

```text
application_name: str
```

既定では `TERMINABLE_DB_APPLICATIONS` に登録された
`fault-injector` だけが対象です。

さらに DB ユーザーが専用の `fault_injector` ユーザーである接続に限定されます。

### 戻り値

主に次を返します。

```text
action
application_name
database_user
matched_sessions
terminated_sessions
terminated_pids
failed_pids
```

### 安全制約

- 任意の PostgreSQL セッションは切断できません。
- application_name は allow-list 方式です。
- DB ユーザーも `fault_injector` に限定されます。
- SQL は固定で、LLM から任意 SQL は渡せません。

---

## 12. cleanup_training_logs

### 目的

disk-full 障害を復旧するため、研修用の古い模擬ログだけを削除します。

### 入力

```text
service: str = "tomcat"
```

### 削除対象

```text
/training-disk/archive/training-*.log
```

### 削除しないもの

たとえば active audit log:

```text
/training-disk/audit/member-audit.log
```

は削除しません。

### 戻り値

```text
action
service
deleted_files
failed_files
before
after
```

`before` / `after` には削除前後のディスク使用率が入ります。

### 安全制約

- service は Tomcat 固定です。
- 任意 path は受け取りません。
- 任意 `rm` コマンドを LLM に公開しません。
- 削除候補を取得した後も prefix / suffix を再検証します。
- Human Approval 後の mutation ToolNode からだけ実行します。

---

# Agent 側での Tool の使われ方

## 1. MCP Server から Tool 定義を取得

`load_tool_catalog()` では、

```python
client = MultiServerMCPClient(...)
tools = await client.get_tools()
```

として MCP Server から Tool の名前・説明・引数定義を取得します。

## 2. ToolCatalog で権限を分離

```python
READ_ONLY_TOOL_NAMES = {...}
MUTATING_TOOL_NAMES = {...}
```

に基づいて、

```python
ToolCatalog(
    read_only=[...],
    mutating={...},
)
```

へ分類します。

## 3. read-only と mutation を別の LLM 用途に bind

`nodes.py` では、調査と状態変更の Tool を別々に bind します。

```python
self.investigator_llm = self.llm.bind_tools(catalog.read_only)

mutation_tools = list(catalog.mutating.values())
self.remediation_llm = self.llm.bind_tools(mutation_tools)
```

`investigator_llm` の Tool Call は read-only ToolNode で自動実行できます。
一方 `remediation_llm` の Tool Call は Human Approval を通るまで実行しません。

## 4. ToolNode が実行

LLM が返した `AIMessage.tool_calls` を、

```python
self.raw_tool_node = ToolNode(catalog.read_only)
```

が実行し、結果を `ToolMessage` として State の `messages` に追加します。

```text
AIMessage(tool_calls=[...])
       ↓
ToolNode
       ↓
MCP Tool 実行
       ↓
ToolMessage(result)
       ↓
state["messages"]
```

## 5. Mutation Tool Call は実行直前で Human Approval

復旧計画用 LLM が返した `AIMessage.tool_calls` を、そのまま ToolNode に流しません。

```text
AIMessage(tool_calls=[
  cleanup_training_logs(service="tomcat")
])
       ↓
approval
       ↓ interrupt()
人間に Tool 名と引数を表示
       ↓ approve
ToolNode(catalog.mutating.values())
       ↓
MCP Tool 実行
```

却下された場合は ToolNode へ進まないため、状態変更は発生しません。
承認された場合は、承認画面で確認した同じ Tool Call を ToolNode が実行します。

> LLM は本物の MCP Tool schema を見て Tool Call を作れるが、状態変更の実行権限は人間が握る

---

# この教材で公開していない危険な Tool

意図的に次のような汎用 Tool は公開していません。

```text
run_shell(command)
read_file(path)
delete_file(path)
execute_sql(sql)
docker_exec(command)
```

これらを LLM にそのまま渡すと、Agent が実行できる操作範囲が広すぎます。

代わりに、

```text
get_disk_usage()
list_large_files()
cleanup_training_logs()
get_postgres_connection_summary()
terminate_postgres_connections()
```

のように、**目的と操作範囲を狭くした Tool** を用意しています。

この「LLM に自由な判断はさせるが、Tool の権限は狭く設計する」という考え方が、
この研修で扱う Agent / MCP 設計の重要なポイントです。
