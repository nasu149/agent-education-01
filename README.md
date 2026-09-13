# AI Agent研修 - 完成版 (`student-complete`)

昨日までに作った Web システムを「運用する側」から見直し、障害一次対応を Agent 化する新人研修の完成形です。

このブランチは、午後のハンズオンで新人が最終的に到達するコードです。

## この教材で教えること

主役は LangGraph の API ではありません。

受講者には次の設計判断を体験してもらいます。

- HTTP 200/500 の判定のような決定論的処理は普通のプログラムに任せる
- 障害後の「次に何を見るか」は LLM に任せる
- LLM は read-only Tool だけを自由に選択する
- 状態変更は Graph の決められた経路からしか実行できない
- `interrupt()` で人間承認を必須にする
- 復旧後に再観測し、直っていなければ再調査する
- MCP は Agent の知能ではなく Tool 接続の標準化レイヤーである

最終的に理解してほしい Agent 像は **Observe → Decide → Act → Re-observe** です。

## システム構成

```text
Browser
  |
  v
httpd :8088
  |
  v
Tomcat 10 / Java Servlet
  |
  v
PostgreSQL 17

ordinary health checker
  |
  | failure
  v
LangGraph
  |
  v
investigate <---- ToolNode(read-only MCP tools)
  |
  v
judge
  |
  +---- manual / none --------------------+
  |                                       |
  v                                       |
approval (LangGraph interrupt)             |
  |                                       |
approve                                   |
  v                                       |
remediate (mutation MCP tool)              |
  |                                       |
  v                                       |
verify ---- NG ---> investigate            |
  |                                       |
  +------------- OK -----------------------+
                                          |
                                          v
                                        report
```

詳細は [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) を参照してください。

## 必要なもの

- Docker Desktop / Docker Engine
- Docker Compose v2（`docker compose` で起動する場合のみ。後述の pure Docker 起動では不要）
- Gemini Developer API の API key
- ブラウザ

ホスト側に Java / Maven / Python は不要です。すべて Docker build 内で準備します。

> Windows 11 + Docker Desktop の Linux Containers を主な想定にしています。Agent コンテナは Docker socket を read/write mount するため、研修専用PC・研修専用環境で使ってください。

## 起動

### Docker Compose を使う場合

PowerShell:

```powershell
Copy-Item .env.example .env
# .env の GEMINI_API_KEY を編集
docker compose up -d --build
docker compose logs -f agent
```

bash:

```bash
cp .env.example .env
# .env の GEMINI_API_KEY を編集
docker compose up -d --build
docker compose logs -f agent
```

### Docker Compose を使わない場合（pure Docker）

`experiment/db-connection-exhaustion` には、`docker build` / `docker network create` / `docker volume create` / `docker run` だけで環境を立ち上げるスクリプトがあります。

Oracle Linux などの bash 環境では、リポジトリのルートで次を実行してください。

```bash
# 初回だけ。対象ブランチへ切り替える
# すでにローカルブランチがある場合は: git switch experiment/db-connection-exhaustion
git fetch origin
git switch --track origin/experiment/db-connection-exhaustion

# Gemini API key を環境変数へ設定
export GEMINI_API_KEY='YOUR_GEMINI_API_KEY'

# 必要なら model も変更可能
# export GEMINI_MODEL='gemini-2.5-flash'

chmod +x scripts/*.sh
./scripts/pure_docker_up.sh
```

`pure_docker_up.sh` は以下を自動で実行します。

1. PostgreSQL / Tomcat / httpd / Agent / fault-injector の Docker image を build
2. `agent-education-net` network を作成
3. `agent-education-postgres-data` volume を作成
4. PostgreSQL を起動し、ready になるまで待機
5. Tomcat を起動
6. httpd を起動
7. Agent を起動

起動確認:

```bash
docker ps
curl -I http://localhost:8088
curl http://localhost:8090/api/status
```

Agent のログ:

```bash
docker logs -f agent-education-agent
```

このスクリプトはデフォルトで起動時に DB volume を作り直します。DB データを残したい場合は次のように起動します。

```bash
RESET_DB_DATA=0 ./scripts/pure_docker_up.sh
```

#### DB connection exhaustion 障害を注入する

正常起動後、別ターミナルで次を実行します。

```bash
./scripts/inject_db_connection_exhaustion.sh
```

このスクリプトは `fault_injector` ユーザーで PostgreSQL 接続を大量に保持し、connection exhaustion を発生させます。

障害注入側のログ:

```bash
docker logs -f agent-education-fault-injector
```

Agent が HTTP 異常を検知すると、PostgreSQL の接続状況を調査し、対象接続の切断について Human-in-the-loop の承認を求める想定です。

#### pure Docker 環境を停止する

```bash
./scripts/pure_docker_down.sh
```

デフォルトでは DB volume も削除します。DB データを残す場合:

```bash
KEEP_DB_DATA=1 ./scripts/pure_docker_down.sh
```

起動後:

- 名簿アプリ: http://localhost:8088
- Agent dashboard: http://localhost:8090
- Agent status API: http://localhost:8090/api/status

初回は Maven / Python package / Docker image の取得があるため、講師は研修前に全端末で一度 build してください。Compose を使う場合は `docker compose build`、pure Docker の場合は `./scripts/pure_docker_up.sh` で build まで行われます。

## 正常状態

名簿アプリに3件の初期データが表示され、Agent dashboard に `HEALTHY / HTTP 200` が表示されれば準備完了です。

Agent は5秒ごとに普通の `httpx` コードで確認します。正常時に Gemini は呼びません。

ここが研修上重要です。

**「AIを使えるから使う」のではなく、曖昧な判断が必要な場所だけ AI を使います。**

## MCP Tool

LLMに公開する read-only Tool:

| Tool | 役割 |
|---|---|
| `http_request` | Webアプリを外側から観測 |
| `list_containers` | httpd / Tomcat / PostgreSQL の状態一覧 |
| `inspect_container` | 1コンテナの状態・port・network・一部env確認 |
| `get_container_logs` | 直近ログ確認 |
| `read_config` | 許可済み設定だけ確認 |

LLMには公開しない mutation Tool:

| Tool | 役割 |
|---|---|
| `start_container` | 停止コンテナを起動 |
| `restart_container` | コンテナ再起動 |

mutation Tool は `approval` を通過した `remediate` node だけが呼べます。

`exec_shell`、`read_any_file`、`fix_system` のような万能 Tool はあえて提供していません。

## Graph

主要Nodeは次の7つです。

1. `investigate`
   - Gemini が次に必要な観測を判断
   - read-only Tool のみ選択可能
2. `tools`
   - LangGraph `ToolNode`
   - MCP Tool を実行して結果を State の `messages` に返す
3. `judge`
   - 調査結果を `Diagnosis` に構造化
4. `approval`
   - `interrupt()` で状態変更前に停止
5. `remediate`
   - 承認済み mutation Tool だけ実行
6. `verify`
   - HTTP を再観測
7. `report`
   - 一次対応結果をまとめる

`tools -> investigate` と `verify -> investigate` の2種類のループがあります。

前者は **情報を得た結果、次の調査を変える Agent loop**。後者は **行動後に環境を再観測する loop** です。

## State

`IncidentState` は「Agentの脳内」よりも **インシデント対応の共有作業票** と説明してください。

主な項目:

- `messages`: LLM / Tool の観測履歴
- `incident`: 最初に検知した事象
- `diagnosis`: 構造化された原因判断
- `approval`: 人間承認状態
- `verification`: 復旧後確認
- `verify_attempts`: 再調査回数
- `report`: 最終報告

## デバッグログ

Docker Compose の場合:

```bash
docker compose logs -f agent
```

pure Docker の場合:

```bash
docker logs -f agent-education-agent
```

ホストにも保存されます:

```text
logs/agent.log
```

Dashboard の `Agent activity` には、内部思考全文ではなく以下だけを表示します。

- 選択した Tool
- Tool の観測結果
- 構造化された原因判断
- HITL
- 実行した復旧操作
- Verification

## 講師が障害を注入する

PowerShell:

```powershell
.\scripts\inject_fault.ps1 tomcat-stop
.\scripts\inject_fault.ps1 postgres-stop
.\scripts\inject_fault.ps1 proxy-port
.\scripts\inject_fault.ps1 db-password
```

bash:

```bash
./scripts/inject_fault.sh tomcat-stop
./scripts/inject_fault.sh postgres-stop
./scripts/inject_fault.sh proxy-port
./scripts/inject_fault.sh db-password
```

`experiment/db-connection-exhaustion` の connection exhaustion 障害は、pure Docker 起動後に次で注入できます。

```bash
./scripts/inject_db_connection_exhaustion.sh
```

### Level 1: `tomcat-stop`

期待例:

```text
HTTP failure
-> list_containers
-> tomcat exited
-> httpd log / additional evidence
-> start_container(tomcat) proposed
-> Human Approval
-> start
-> HTTP 200
```

### Level 2: `postgres-stop`

期待例:

```text
HTTP 500
-> containers
-> postgres exited
-> Tomcat log
-> PostgreSQL connection failure
-> start_container(postgres)
-> Approval
-> verify
```

### Level 3: `proxy-port`

httpd の backend を `tomcat:8080` から `tomcat:18080` に変更します。

全部 running なので、状態一覧だけでは答えが出ません。ログ・設定・container情報を組み合わせる必要があります。

Agent に設定変更 Tool はありません。したがって「原因特定 + 人間へエスカレーション」で成功です。

### Level 3: `db-password`

PostgreSQL 側の user password だけ変更します。Tomcat / PostgreSQL は running のままです。

これも Agent の権限では安全に修復できないため、manual escalation が期待結果です。

## リセット

一番確実な方法:

PowerShell:

```powershell
.\scripts\reset.ps1
```

bash:

```bash
./scripts/reset.sh
```

pure Docker の場合:

```bash
./scripts/pure_docker_down.sh
./scripts/pure_docker_up.sh
```

DB volume を含めて作り直すため、次のチーム演習を完全な正常状態から始められます。

## 午前講義 → 午後ハンズオンのシナリオ

午前中はコードを書かせません。

講義では次の順番を推奨します。

1. 昨日作った httpd / Tomcat / PostgreSQL 構成を振り返る
2. 「名簿アプリが使えない。人間なら何を見る？」を考える
3. 人間の調査を Observe → Decide → Act → Re-observe に整理
4. 普通のLLMには環境を見る目・手がないことを説明
5. Tool を与える意味を説明
6. Tool があるだけでは権限・終了条件・再確認が決まらないと説明
7. State / Node / Edge / conditional edge / ToolNode を紹介
8. 「固定する仕事の流れ」と「LLMに任せる局所判断」を分離
9. HITL を「本番で勝手に再起動してよいか？」から導入
10. MCP は最後に、Tool 接続の標準化として位置付ける

午後は `instructor-ready` branch から始め、完成結果としてこの branch と同じ Graph を作ります。

## 午後の推奨進行

### 13:00-13:20: 環境確認

- `docker compose up` または `./scripts/pure_docker_up.sh`
- 名簿アプリを見る
- Agent dashboardを見る
- MCP Tool一覧を確認
- 「監視にLLMを使っていない」ことを確認

### 13:20-14:10: investigation loop

受講者が主に編集するのは `agent/src/agent/graph.py` です。

- Gemini に read-only tools を bind
- `investigate`
- `ToolNode`
- conditional edge
- `tools -> investigate`

既知障害 `tomcat-stop` で練習します。

### 14:10-14:40: 判断をGraphへ戻す

- `Diagnosis`
- `judge`
- 「自由な調査」と「明示的な次工程」を分ける

### 14:40-15:20: HITL と remediation

- `interrupt()`
- `Command(resume=...)`
- mutation Tool を LLM に直接渡さない理由
- `remediate`

### 15:20-15:40: verify

- 行動したら再観測
- 直っていなければ再調査

### 15:40-16:20: Secret fault challenge

講師だけが障害を知る状態で1チーム1障害を注入します。

### 16:20-16:50: 発表

各チームは以下を説明します。

- 原因
- Toolを使った順番
- 観測結果で次の行動がどう変わったか
- LLMに任せた部分
- Graphで固定した部分
- HITLの意味
- Agentに追加権限を与えるべきか

### 16:50-17:00: まとめ

```text
決められる処理        -> ordinary code
状況依存の局所判断    -> LLM
外界の観測/操作       -> Tool
Tool接続の標準化      -> MCP
危険操作の境界        -> Human
仕事全体の制御        -> LangGraph
```

## ソースの見どころ

- `agent/src/agent/runtime.py`: 普通の監視とAgent起動の境界
- `agent/src/agent/graph.py`: 教育の主役
- `agent/src/agent/mcp_tools.py`: read-only / mutation capability 分離
- `agent/src/mcp_server/server.py`: MCP Tool実装
- `agent/src/agent/api.py`: HITL UI/API
- `scripts/`: 講師用障害注入

完成版の意図は [`docs/SOLUTION_GUIDE.md`](docs/SOLUTION_GUIDE.md) にもまとめています。

## CI

GitHub Actionsで以下を確認します。

- Python compile + unit test
- Maven build
- `docker compose config`
- `docker compose build`

Geminiを呼ぶE2EテストはAPI keyが必要なのでCIには入れていません。

## セキュリティ上の注意

Agent コンテナには Docker socket を mount しています。これは研修環境では簡潔ですが、実運用で同じ方式を無批判に採用しないでください。

この教材の「安全性」は Tool の allow-list と Graph の権限制御を学ぶためのものです。本番ではさらに認証、認可、監査、secret管理、永続checkpoint、Tool側のポリシーなどが必要です。
