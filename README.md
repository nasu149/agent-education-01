# AI Agent研修 - 講師準備 / ハンズオン開始版 (`instructor-ready`)

このブランチは **午後ハンズオン開始時に受講者へ配布する状態** です。

httpd / Tomcat / PostgreSQL、名簿管理Servlet、MCP Server、Tool、Gemini接続用依存、Health Checker、Agent Dashboard、障害注入script、debug log まで講師側で完成しています。

受講者が主に編集するのは次の1ファイルです。

```text
agent/src/agent/graph.py
```

最初のGraphは安全なplaceholderです。環境全体は正常に起動し、障害を検知できますが、Agent調査は「ここから実装する」と表示して終了します。

完成形は `student-complete` branch にあります。

## 研修の設計思想

午前講義で先に次を理解させてからコードへ入ってください。

```text
昨日まで:
Browser -> httpd -> Tomcat -> Servlet -> PostgreSQL を作った

今日:
そのシステムを「運用する側」になる
```

最初の問いは LangGraph ではありません。

> 名簿アプリが使えない、と言われたら人間は何を見ますか？

受講者の答えを整理して、

```text
Observe
  ↓
Decide
  ↓
Act
  ↓
Re-observe
```

へつなげます。

その後で、

- HTTP status 判定は普通のコードで十分
- 「次にログを見るか、containerを見るか」は状況依存
- そこを LLM に任せる
- 外界を見る能力が Tool
- Tool接続の標準化が MCP
- 全体の仕事の順序・権限制御が LangGraph
- 危険操作前の境界が Human-in-the-loop

という順番にしてください。

## システム

```text
Browser
  |
  v
httpd :8088
  |
  v
Tomcat 10 + Java Servlet
  |
  v
PostgreSQL 17


Health Checker (ordinary Python)
  |
  | abnormal
  v
LangGraph starter
  |
  v
investigate_placeholder
  |
  v
END
```

受講者が午後にこれを、

```text
START
  |
  v
investigate <---- tools(ToolNode)
  |                 |
  +-----------------+
  |
  v
judge
  |
  +--> report (manual / no action)
  |
  v
approval
  |
  v
remediate
  |
  v
verify -- failure --> investigate
  |
  v
report
  |
 END
```

へ育てます。

## 必要なもの

- Docker Desktop / Docker Engine
- Docker Compose v2
- Gemini Developer API key
- ブラウザ

ホストに Python / Java / Maven は不要です。

## 講師の事前準備

### 1. `.env`

PowerShell:

```powershell
Copy-Item .env.example .env
```

bash:

```bash
cp .env.example .env
```

`.env` の次だけ設定します。

```dotenv
GEMINI_API_KEY=...
```

### 2. 事前build

研修前に必ず各PCで一度実施してください。

```bash
docker compose build
```

研修中に Maven / PyPI / Docker Hub の大量downloadが発生するのを避けるためです。

### 3. 起動確認

```bash
docker compose up -d
docker compose ps
```

- 名簿アプリ: http://localhost:8088
- Agent dashboard: http://localhost:8090

名簿が3件表示され、Agent側が `HEALTHY / HTTP 200` ならOKです。

### 4. MCPの確認

Agent container 内からMCP Serverはstdioで起動されます。

MCPの実装:

```text
agent/src/mcp_server/server.py
```

提供済みread-only Tool:

- `http_request`
- `list_containers`
- `inspect_container`
- `get_container_logs`
- `read_config`

変更系Tool:

- `start_container`
- `restart_container`

**変更系Toolは存在しますが、LLMへ直接渡すためのものではありません。**

完成版ではHuman Approval後のNodeだけが呼びます。

## 午後ハンズオン

詳細手順は [`docs/HANDS_ON.md`](docs/HANDS_ON.md) を参照してください。

推奨は約3.5〜4時間です。

### Step 0 - まず動かす

受講者はコードを書く前に、

```bash
docker compose up -d --build
```

で、

- 名簿アプリ
- Agent dashboard
- `docker compose logs -f agent`

を確認します。

ここで講師が一度 `tomcat-stop` を入れても構いません。

starterは障害を検知しますが、調査せず安全に終了します。

> 「監視はできた。でも原因を調べる判断能力がまだない」

という状態を見せられます。

### Step 1 - investigation loop

受講者が、

- Gemini
- read-only Tool bind
- `investigate`
- `ToolNode`
- conditional edge
- `tools -> investigate`

を追加します。

ここが最重要です。

```text
観測結果
   ↓
次に見るものを変える
   ↓
また観測
```

というAgent loopを体験させます。

### Step 2 - judge

調査中の自由度をそのまま全Graphへ流さず、`Diagnosis` に変換します。

「LLMを使う場所」と「システムで固定する場所」を分けます。

### Step 3 - HITL / remediation

`interrupt()` を入れ、

```text
原因推定
 -> 復旧案
 -> Human Approval
 -> mutation Tool
```

にします。

### Step 4 - verify

状態を変えたら終わりではなく、HTTPを再観測します。

失敗なら `investigate` へ戻します。

### Step 5 - Secret fault

最後は講師が障害を隠して注入します。

詳しい答えは [`docs/INSTRUCTOR_GUIDE.md`](docs/INSTRUCTOR_GUIDE.md) にあります。

## Debug

```bash
docker compose logs -f agent
```

さらに、

```text
logs/agent.log
```

へrotating logを保存します。

Dashboardにも教育上必要なtraceだけ表示されます。

## Reset

PowerShell:

```powershell
.\scripts\reset.ps1
```

bash:

```bash
./scripts/reset.sh
```

DB volumeも削除し、完全な初期状態へ戻します。

## ブランチの使い分け

| Branch | 用途 |
|---|---|
| `instructor-ready` | 午後開始時。インフラ完成、Graphは演習用starter |
| `student-complete` | 完成見本・講師の答え・トラブル時の比較用 |

新人に最初から `student-complete` のコードを見せない方が、設計を考える時間を作れます。
