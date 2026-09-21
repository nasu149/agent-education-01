# 受講者向け: Team Agent Battle ハンズオン

## ミッション

昨日までに作成した名簿管理システムに障害が発生したとき、原因を調査し、安全に一次対応する AI Agent をチームで作成してください。

対象システム:

```text
Browser
  ↓
httpd
  ↓
Tomcat
  ↓
PostgreSQL
```

3チームとも同じ starter、同じ Tool、同じ Gemini model を使います。

最後に同じ障害を各チームの Agent に与え、動作を比較します。

---

## ゴール

コードをたくさん書くことがゴールではありません。

次を説明できることがゴールです。

```text
決められる処理       -> 普通のプログラム
状況依存の判断       -> LLM
外部の観測・操作     -> Tool
Tool 接続            -> MCP
危険操作の承認       -> Human
全体の制御           -> LangGraph
```

---

## 触るファイル

基本的にここだけです。

```text
agent/src/agent/graph.py
```

次は講師側の完成済み部分なので変更しません。

```text
agent/src/mcp_server/
agent/src/agent/mcp_tools.py
agent/src/agent/runtime.py
agent/src/agent/api.py
fault-injector/
scripts/battle_*.sh
```

---

## チーム内の役割例

5人チームなら、最初は次のように分けてください。

- Driver: 実際にコードを書く
- Navigator: LangGraph / Python の構造を確認する
- Agent Strategist: Prompt と調査方針を考える
- Observer: Dashboard / log / Tool結果を見る
- Recorder: 設計理由・失敗・発表内容を記録する

途中で役割を交代してください。

情報系出身者1人だけが全部書いて終わらないことを重視します。

---

## Step 0: starter を確認

最初の Graph は安全な placeholder です。

```text
START -> starter -> END
```

障害は検知しますが、調査・復旧は行いません。

`agent/src/agent/graph.py` の TODO 1〜5 を探してください。

---

## Step 1: Tool を確認

LLM が自由に使える read-only Tool:

- `http_request`
- `list_containers`
- `inspect_container`
- `get_container_logs`
- `read_config`
- `get_postgres_connection_summary`

状態変更 Tool:

- `start_container`
- `restart_container`
- `terminate_postgres_connections`

重要:

**状態変更 Tool を LLM に直接渡してはいけません。**

---

## Step 2: 調査 Prompt を設計

starter に最低限の Prompt があります。

チームで次を議論してください。

- 最初に何を見るべきか
- 1つの情報だけで原因を決めてよいか
- container が running なら正常と言えるか
- いつ Tool 呼び出しを止めるか
- 無駄な Tool 呼び出しをどう減らすか

Prompt はチームの個性を出してよい場所です。

ただし競技問題の答えそのものを書いてはいけません。

---

## Step 3: TODO 2 - investigate

`investigate` を実装します。

目的:

> 現在までに集めた情報から、次に必要な観測を LLM に選ばせる

使うもの:

```python
investigator_llm
state["messages"]
SystemMessage
```

戻り値:

```python
{"messages": [response]}
```

LLM が Tool call を返すと、後で `tools` Node へ進みます。

Tool の結果を見た後は再び `investigate` に戻ります。

```text
investigate
    |
    | tool call
    v
  tools
    |
    +------> investigate
```

---

## Step 4: TODO 3 - judge

調査が終わったら、自由文のまま復旧へ進ませません。

`Diagnosis` へ変換します。

```text
自由な調査履歴
    ↓
judge
    ↓
Diagnosis
    - root_cause
    - evidence
    - recommended_action
    - target_service
    - target_application
    - confidence
```

ここで学ぶポイント:

**LLM の自由な探索と、システムが扱う明示的な State を分ける。**

---

## Step 5: TODO 4 - approval

状態変更が必要な場合、人間へ承認を求めます。

```text
judge
  ↓
approval
  ↓
Human
```

`interrupt()` を使います。

注意:

- interrupt より前に状態変更しない
- LLM に mutation Tool を渡さない
- 承認されなければ remediate へ進ませない

---

## Step 6: TODO 5 - Graph を完成

次を完成させます。

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

`remediate`、`verify`、`report` の中身は講師側で完成しています。

皆さんは **Nodeをどう接続するか** を実装します。

---

## Team Originality

次は変更して構いません。

- Prompt
- 調査戦略
- State の追加
- routing
- LLM と普通のコードの役割分担
- report の表現

例えば、

- 最初の HTTP 観測だけは固定する
- 最低2種類の証拠が集まるまで診断しない
- Tool使用回数を State で管理する
- confidence が low なら追加調査する

なども考えられます。

ただし3.5時間しかありません。

**複雑にすること自体には価値はありません。**

---

## 禁止事項

競技条件と安全性を揃えるため、次は禁止です。

1. MCP Server の変更
2. fault injector の変更
3. mutation Tool を LLM に bind
4. Human Approval を迂回
5. 任意 shell / 任意 SQL の追加
6. 障害名や答えの hard-code
7. Gemini model の変更
8. 他チームのコードのコピー

---

## Team image を作る

完成したら各チームの作業ディレクトリで実行します。

Team A:

```bash
chmod +x scripts/*.sh
./scripts/battle_build_agent.sh team-a
```

Team B:

```bash
./scripts/battle_build_agent.sh team-b
```

Team C:

```bash
./scripts/battle_build_agent.sh team-c
```

これで同じ VM に3種類の Agent image を保持できます。

評価時に同時起動はしません。

---

## Practice

最初は `tomcat-stop` です。

採点しません。

期待する大まかな流れ:

```text
HTTP NG
 ↓
状態を観測
 ↓
Tomcat stopped を発見
 ↓
start_container を提案
 ↓
Human Approval
 ↓
起動
 ↓
HTTP 200
```

ここで失敗しても調整時間があります。

---

## Battle

本番の障害内容は事前に詳しく教えません。

ただし、Agent が持つ権限だけでは直せない障害もあります。

その場合は、

> 原因を特定し、人間へ正しくエスカレーションする

のが正しい終了です。

「何でも自動修復する Agent」を作ることが目的ではありません。

---

## 発表で説明すること

各チームは最後に次を説明してください。

1. Agent の調査方針
2. Prompt で工夫したところ
3. LLM に任せた部分
4. Graph で固定した部分
5. Human を入れた理由
6. Battle 中に想定外だった動き
7. 改善するなら何を変えるか
