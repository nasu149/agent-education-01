# AI Agent研修 - 3チーム対抗スターター

このブランチ `training/team-agent-battle` は、前段の Docker 研修で作成した

```text
Browser -> httpd -> Tomcat -> PostgreSQL
```

の名簿管理システムを使い、3チームがそれぞれ障害対応 AI Agent を作成して最後に同一条件で比較するための研修スターターです。

## 研修の狙い

LangGraph API の暗記ではなく、次の境界を体験します。

```text
普通のプログラム   -> 決定的な処理
LLM                -> 状況依存の判断
Tool               -> 外部の観測・操作
MCP                -> Tool 接続
Human              -> 危険操作の承認
LangGraph          -> State / flow / loop / 権限制御
```

最終的な Agent の考え方は、

```text
Observe -> Decide -> Act -> Re-observe
```

です。

## 3チーム対抗方式

約15名を3チームに分け、全チームが同じ starter から同じ障害対応 Agent を作成します。

最後に1台の共有 VM 上で、Agent を1チームずつ起動し、同じ障害を順番に注入します。

```text
reset
  ↓
Team A Agent
  ↓
fault
  ↓
result

reset
  ↓
Team B Agent
  ↓
same fault
  ↓
result

reset
  ↓
Team C Agent
```

3つの Agent を同時に障害対応させないため、同じ Tomcat / PostgreSQL を取り合うことはありません。

## 新人が主に編集する場所

```text
agent/src/agent/nodes.py   # TODO 1〜4: Prompt / investigate / judge / approval
agent/src/agent/graph.py   # TODO 5: Node / Edge の配線
```

役割を分けています。

```text
nodes.py = 各 Node が「何をするか」
graph.py = 各 Node を「どう繋ぐか」
```

`graph.py` を開けば LangGraph の全体構造だけを追えるようにしています。

開始時点は安全な placeholder Graph です。

```text
START -> starter -> END
```

受講者はコード内の `TODO 1〜5` を進めます。

**TODO コメントは問題文です。基本的に消さず、その直下へ実装を書いてください。**
講師用 solution branch も同じ TODO コメントを残したまま、直下へ模範解答を書いています。

主な実装対象:

1. 調査 Prompt の設計
2. `investigate`
3. `judge`
4. `approval`
5. LangGraph の Node / Edge / loop の配線

講師側で完成済み:

- Docker / 対象システム
- Health Checker
- Dashboard / API
- MCP Server
- read-only / mutation Tool
- mutation Tool の安全な実行処理
- `verify`
- `report`
- fault injector

## 完成時の Graph

```text
START
  |
  v
investigate <------ tools
  |                  |
  +------------------+
  |
  v
judge
  |
  +---- manual / none ------> report
  |
  v
approval
  |
  +---- reject --------------> report
  |
  v
remediate
  |
  v
verify ---- failure ---------> investigate
  |
  v
report
  |
 END
```

## 資料

### 上司・企画説明

[docs/TEAM_AGENT_BATTLE_PROPOSAL.md](docs/TEAM_AGENT_BATTLE_PROPOSAL.md)

Docker研修までは把握しているが、AI Agent ハンズオン案は初見、という前提で書いています。

### 受講者向け

[docs/TEAM_AGENT_BATTLE_HANDS_ON.md](docs/TEAM_AGENT_BATTLE_HANDS_ON.md)

### 競技ルール・採点

[docs/TEAM_AGENT_BATTLE_RULES.md](docs/TEAM_AGENT_BATTLE_RULES.md)

### 講師向け運営

[docs/TEAM_AGENT_BATTLE_INSTRUCTOR_GUIDE.md](docs/TEAM_AGENT_BATTLE_INSTRUCTOR_GUIDE.md)

### DB connection exhaustion の技術説明

[docs/DB_CONNECTION_EXHAUSTION.md](docs/DB_CONNECTION_EXHAUSTION.md)

## 共有 VM の初期起動

Linux / Oracle Linux を想定:

```bash
cp .env.example .env
# .env を編集して GEMINI_API_KEY などを設定
chmod +x scripts/*.sh
./scripts/pure_docker_up.sh
```

`pure_docker_up.sh` と `battle_start_agent.sh` はリポジトリ直下の `.env` を読み込みます。
Docker Compose 利用時も同じ `.env` が使われます。

主な設定:

```dotenv
HEALTH_CHECK_INTERVAL_SECONDS=5
MONITOR_STARTUP_GRACE_SECONDS=20
FAILURE_THRESHOLD=2
GEMINI_TIMEOUT_SECONDS=90
```

起動ログにも実際に採用された値が表示されます。

なお、Agent Dashboard は画面更新のため `GET /api/status` を約1.5秒ごとに呼びます。
これはヘルスチェックではありません。実際のヘルスチェックは
`HEALTH_CHECK_INTERVAL_SECONDS` ごとの `GET /api/members` です。

確認:

```bash
curl -f http://localhost:8088/api/members
curl -f http://localhost:8090/api/status
```

- 名簿アプリ: `http://VM_HOST:8088`
- Agent Dashboard: `http://VM_HOST:8090`

## Battle 補助 script

### チーム Agent image を build

各チームの working directory で:

```bash
./scripts/battle_build_agent.sh team-a
```

### 評価環境を正常化

```bash
./scripts/battle_reset.sh
```

### チーム Agent を起動

```bash
./scripts/battle_start_agent.sh team-a
```

### 障害注入

```bash
./scripts/battle_inject_fault.sh tomcat-stop
./scripts/battle_inject_fault.sh postgres-stop
./scripts/battle_inject_fault.sh db-connections
./scripts/battle_inject_fault.sh proxy-port
./scripts/battle_inject_fault.sh db-password
```

## 想定ラウンド

Practice:

```text
tomcat-stop
```

Battle:

```text
Round 1: postgres-stop
Round 2: db-connections
Round 3: proxy-port
```

`proxy-port` は許可された mutation Tool だけでは修復できません。

原因を特定し、`manual` と判断して人間へエスカレーションできれば成功です。

## Safety

競技でも次は変更禁止です。

- mutation Tool を LLM に直接 bind
- Human Approval を迂回
- 任意 shell / 任意 SQL を Agent に追加
- MCP Server / fault injector の競技用改造
- 障害の答えの hard-code

「何でもできるAgent」ではなく、**権限を限定した上で適切に判断できるAgent**を作る研修です。
