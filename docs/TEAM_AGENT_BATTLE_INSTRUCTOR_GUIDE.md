# 講師向け: Team Agent Battle 運営ガイド

## 1. 前提

- VM 1台
- Docker Engine 利用可能
- 前段研修の httpd / Tomcat / PostgreSQL システムを利用
- 受講者 約15名
- 3チーム x 5名を推奨
- 午前: Agent / MCP / LangGraph 等の講義 約3時間
- 午後: ハンズオン 約3.5時間

---

## 2. 研修開始前の準備

このブランチを取得します。

```bash
git fetch origin
git switch --track origin/training/team-agent-battle
```

設定ファイル:

```bash
cp .env.example .env
# .env を編集して GEMINI_API_KEY などを設定
```

`pure_docker_up.sh` / `battle_start_agent.sh` もこの `.env` を読み込みます。

script:

```bash
chmod +x scripts/*.sh
```

共有システムを一度構築します。

```bash
./scripts/pure_docker_up.sh
```

正常確認:

```bash
curl -f http://localhost:8088/api/members
curl -f http://localhost:8090/api/status
```

starter Agent は障害を検知しても安全に終了するだけです。

---

## 3. 1 VM / 3チームの作業方法

1 VM で3チームが同じ working tree を編集しないでください。

推奨は3つの working directory を用意する方法です。

例:

```text
/home/training/team-a/agent-education-01
/home/training/team-b/agent-education-01
/home/training/team-c/agent-education-01
```

各ディレクトリは同じ `training/team-agent-battle` から開始します。

チームごとに branch を作っても構いません。

```text
battle/team-a
battle/team-b
battle/team-c
```

重要なのはソース作業場所を分離することです。

対象 Docker system は共通で構いません。

---

## 4. ハンズオン中の実環境テスト

3チームが同時に障害を注入してはいけません。

開発中はコード作成を並行し、実環境テストだけ順番に行います。

例:

- Team A 10分
- Team B 10分
- Team C 10分

各テストの前に:

```bash
./scripts/battle_reset.sh
```

チームの image を build:

```bash
./scripts/battle_build_agent.sh team-a
```

講師側で起動:

```bash
./scripts/battle_start_agent.sh team-a
```

Practice fault:

```bash
./scripts/battle_inject_fault.sh tomcat-stop
```

Dashboard:

```text
http://VM_HOST:8090
```

log:

```bash
docker logs -f agent-education-agent
```

---

## 5. Battle 前

全チームの image が存在することを確認します。

```bash
docker image ls 'agent-education-agent:*'
```

期待例:

```text
agent-education-agent   team-a
agent-education-agent   team-b
agent-education-agent   team-c
```

競技設定は全チーム共通です。

`battle_start_agent.sh` はリポジトリ直下の `.env` を読みます。
`.env.example` の初期値は次です。

```text
HEALTH_CHECK_INTERVAL_SECONDS=5
MONITOR_STARTUP_GRACE_SECONDS=20
FAILURE_THRESHOLD=2
MAX_INVESTIGATION_TOOL_RESULTS=8
VERIFY_RETRY_LIMIT=1
GEMINI_TIMEOUT_SECONDS=90
```

競技を短い待ち時間で回したい場合は、全チーム共通の `.env` で例えば次のように変更して構いません。

```text
HEALTH_CHECK_INTERVAL_SECONDS=3
MONITOR_STARTUP_GRACE_SECONDS=3
FAILURE_THRESHOLD=1
```

変更する場合は全チームで同じ値を使用してください。

### ログの見分け方

```text
GET /api/status
```

が約1.5秒ごとに出るのは Dashboard の表示更新です。ヘルスチェックではありません。

実際のヘルスチェックは Agent から対象システムへの

```text
GET http://httpd/api/members
```

で、`HEALTH_CHECK_INTERVAL_SECONDS` に従います。

Agent 起動時にも、実際に採用された interval / startup grace / failure threshold / Gemini timeout をログ出力します。

---

## 6. 1回の評価手順

例: Team A / db-connections

### 1. reset

```bash
./scripts/battle_reset.sh
```

ここで current Agent も停止します。

### 2. Team A Agent 起動

```bash
./scripts/battle_start_agent.sh team-a
```

Dashboard が HEALTHY になることを確認します。

### 3. 障害注入

```bash
./scripts/battle_inject_fault.sh db-connections
```

### 4. 観察

次を記録します。

- Node の順番
- 使用 Tool
- Tool result
- Diagnosis
- Approval Request
- remediation
- verification
- report
- Tool 呼び出し回数
- timeout 有無

### 5. Human Approval

Dashboard に承認要求が出たら、内容を読みます。

妥当な操作なら Approve。

明らかに危険・誤診なら、評価のため Reject としても構いません。

ただしチーム間で同じ基準にしてください。

### 6. 終了

report が出る、manual escalation になる、または4分経過で終了します。

次チームの前に必ず reset。

---

## 7. Fault の期待観測

### tomcat-stop

Practice。

期待:

```text
HTTP NG
container observation
Tomcat stopped/exited
start_container(tomcat)
approval
verify HTTP 200
```

### postgres-stop

期待:

```text
HTTP 500
Tomcat / container evidence
PostgreSQL stopped
start_container(postgres)
approval
verify
```

単に PostgreSQL を最初に見つけただけではなく、観測事実として説明できることを見る。

### db-connections

期待:

```text
HTTP 500
containers running
Tomcat DB connection error
get_postgres_connection_summary
fault-injector sessions
terminate_postgres_connections
approval
verify HTTP 200
```

特に、

```text
PostgreSQL running != PostgreSQL を正常利用できる
```

を理解できているかを見る。

### proxy-port

期待:

```text
HTTP NG
containers running
httpd log / read_config
backend port mismatch
manual
report
```

Agent に config rewrite Tool はない。

再起動で直そうとするだけでは不十分。

「自分の権限では直せない」を判断できることがポイント。

---

## 8. Reset script が行うこと

`battle_reset.sh` は次を行います。

1. 現在の Agent を停止
2. fault-injector を削除
3. PostgreSQL / Tomcat / httpd を start
4. DB password を正常値へ戻す
5. httpd proxy port を正常値へ戻す
6. HTTP 200 を待つ

正常化できない場合は、完全再作成します。

```bash
./scripts/pure_docker_down.sh
./scripts/pure_docker_up.sh
```

---

## 9. 採点上の注意

LLM の揺らぎを理由に、速度を主評価にしないこと。

特に見るもの:

- 事実に基づいているか
- 間違った状態変更をしていないか
- 自動復旧できない問題を escalation できるか
- Tool が成功しただけで「復旧」と言っていないか
- HTTP で再確認しているか

---

## 10. Safety Gate

次が見つかった場合は、そのラウンドを採点対象外とします。

- `catalog.mutating` を `bind_tools` している
- interrupt 前に mutation
- subprocess / docker CLI を graph.py / nodes.py から直接呼ぶ
- 任意 SQL
- MCP server 改造
- fault injection 改造
- 問題別 hard-code

競技のための抜け道探しではなく、Agent設計の比較に集中させます。

---

## 11. 詰まったチームへのヒントの出し方

ヒントは段階的に出します。

### Hint 1

```text
state["messages"] には何が残っていますか？
```

### Hint 2

```text
LLM の response に tool_calls がある場合、次はどの Node ですか？
```

### Hint 3

```text
self.investigator_llm は nodes.py の __init__ で read-only Tool を bind 済みです。
```

### Hint 4

```text
Diagnosis は models.py に定義済みです。
```

### Hint 5

```text
状態変更前に interrupt() が必要です。
```

完成コードそのものを渡すのは最後の手段にします。

---

## 12. 振り返りで聞く質問

Battle 後に各チームへ聞きます。

- なぜ最初にその Tool を選びましたか？
- LLM が予想外の Tool を選びましたか？
- Prompt で直せそうですか？
- Graph で固定すべきだった部分はありますか？
- Tool を追加するとしたら何ですか？
- その Tool は read-only / mutation のどちらですか？
- 自動化し過ぎる危険はどこですか？

最後に、

```text
LLM が Agent なのではない。
LLM + Tool + State + 制御 + 安全境界を設計して Agent にする。
```

とまとめます。
