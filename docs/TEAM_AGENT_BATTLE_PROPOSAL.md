# 上司説明用: 3チーム対抗 AI Agent ハンズオン案

## 1. この資料の目的

前段の研修では、受講者が VM 上の Docker を使い、httpd / Tomcat / PostgreSQL からなる名簿管理システムを構築します。

本資料は、そのシステムを次の研修素材として再利用し、**「障害が起きたシステムを AI Agent が調査・一次復旧する」ハンズオン**を追加する案です。

Docker 研修そのものを作り直すものではありません。前段で構築したシステムを「開発する側」から「運用する側」へ見方を変え、AI Agent / LangGraph / Tool / MCP / Human-in-the-loop の関係を体験してもらうことが目的です。

---

## 2. 一言でいうと

15名程度の新人を3チームに分け、全チームが同じスターターコードから同じ障害対応 Agent を作成します。

最後に、同じ障害を各チームの Agent に順番に与え、

- 原因を正しく特定できたか
- 必要な情報を Tool で取得できたか
- 危険な操作の前に人間承認を挟めたか
- 適切に復旧、または人間へエスカレーションできたか
- 復旧後に本当に直ったことを確認できたか

を比較します。

単なるコーディング演習ではなく、**「同じ LLM・同じ Tool でも Agent の設計によって振る舞いが変わる」**ことを体験する対抗形式です。

---

## 3. 教育上の狙い

受講者に LangGraph API の暗記をさせることが目的ではありません。

理解してほしい境界は次です。

```text
普通のプログラム
  -> HTTP 200/500 の判定など、決定的に書ける処理

LLM
  -> 状況を見て「次に何を調べるか」を判断する部分

Tool
  -> LLM が外部システムを観測・操作する手段

MCP
  -> Tool を接続するための標準化レイヤー

Human
  -> 再起動や DB session 切断など、状態変更前の承認

LangGraph
  -> Agent 全体の State・処理順序・権限・loop を制御
```

最終的には、障害対応を次の形として理解してもらいます。

```text
Observe
   ↓
Decide
   ↓
Act
   ↓
Re-observe
```

---

## 4. 前段 Docker 研修とのつながり

前段:

```text
Browser
  ↓
httpd
  ↓
Tomcat / Java Servlet
  ↓
PostgreSQL
```

今回:

```text
同じシステム
  ↓
障害発生
  ↓
Health Checker
  ↓
LangGraph Agent
  ↓
read-only Tool で調査
  ↓
原因判断
  ↓
Human Approval
  ↓
限定された復旧 Tool
  ↓
HTTP で再確認
```

受講者にとっては、前日に自分たちが構築したシステムがそのまま障害対応の対象になります。

「新しい題材をもう1つ覚える」のではなく、**既に知っているシステムを運用側から見る**構成です。

---

## 5. 講師側で準備するもの

新人にすべてを作らせると、3.5時間では Python / Docker / MCP のデバッグに時間を使い過ぎます。

そのため次は完成済みで提供します。

- httpd / Tomcat / PostgreSQL
- 名簿管理アプリ
- Health Checker
- Agent Dashboard
- MCP Server
- read-only Tool
- mutation Tool
- 障害注入スクリプト
- Human Approval を受け付ける API / UI
- Agent Runtime
- Diagnosis などのデータ型
- mutation Tool を安全に呼ぶ処理
- 復旧後の HTTP verify 処理
- 最終 report 処理

新人の主な編集対象は次の2ファイルです。

```text
agent/src/agent/nodes.py
agent/src/agent/graph.py
```

`nodes.py` には State / Prompt / 各 Node の処理を置き、
`graph.py` は Node / Edge の配線だけにしています。

これにより、LangGraph の全体像を学ぶときに巨大な `build_graph()` を読む必要がなく、
「Node の中身」と「Graph の構造」を分けて理解できます。

---

## 6. 新人に作成させる部分

スターターでは安全のため、

```text
START -> starter -> END
```

だけが接続されています。

障害を検知しても、状態変更は行いません。

受講者は次を実装します。

### TODO 1: 調査 Prompt

最低限の Prompt は用意しています。

チームで、

- どのような順序で調べるべきか
- 推測と観測をどう扱うか
- いつ調査を終了するか
- 何件の根拠を集めるか

を議論し、必要なら Prompt を改善します。

### TODO 2: investigate

read-only Tool を bind した Gemini を呼びます。

ここで LLM が、

```text
list_containers を見る
        ↓
Tomcat log を見る
        ↓
PostgreSQL connection を見る
```

のように、観測結果に応じて次の Tool を選びます。

### TODO 3: judge

自由な調査結果を `Diagnosis` という構造化データへ変換します。

Agent の探索結果を、後続の Graph が扱える明示的な State に戻す部分です。

### TODO 4: approval

`interrupt()` を使い、状態変更前に人間承認を要求します。

### TODO 5: Graph wiring

最終的に次の Graph を完成させます。

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

---

## 7. なぜ3チームとも同じものを作るのか

役割分担して1つの Agent を作る方式も考えられますが、今回は3チームとも Agent 全体を作成します。

理由は次のとおりです。

1. 全員が Observe / Decide / Act / Re-observe の全体像を経験できる
2. 同じ要求でも Prompt や Graph 設計で差が出る
3. 最後の比較が「Agent 設計」の振り返りになる
4. 情報系出身者だけが Agent 全体を理解して終わることを防ぎやすい

競技そのものが目的ではなく、**設計差を可視化するために競技形式を使う**位置づけです。

---

## 8. オリジナリティを出してよい範囲

全チームが完全に同じコードを写すだけでは比較になりません。

次は自由に変更可能とします。

- System Prompt
- 調査方針
- read-only Tool の使い方
- State の追加項目
- 決定論的処理と LLM の役割分担
- routing の工夫
- report の見せ方
- 調査の打ち切り方

一方、次は禁止します。

- 障害の答えを hard-code
- 「db-connections 問題ならこの Tool」のような競技問題専用分岐
- MCP Server の変更
- fault injector の変更
- mutation Tool を LLM に直接 bind
- Human Approval を通さず状態変更
- Agent から任意 shell / 任意 SQL を実行
- チームごとに Gemini model や Tool 数を変更

この境界により、自由度を残しつつ比較条件を揃えます。

---

## 9. 1台 VM で実施できるか

可能です。

ポイントは、3チームの Agent を同時に障害対応させないことです。

対象システムは1セットだけです。

```text
共通 VM

httpd
  ↓
Tomcat
  ↓
PostgreSQL

+ Team A Agent image
+ Team B Agent image
+ Team C Agent image
```

3チームの Agent image は事前に build しておき、**評価時には1つだけ起動**します。

```text
reset
 ↓
Team A Agent 起動
 ↓
障害注入
 ↓
結果記録

reset
 ↓
Team B Agent 起動
 ↓
同じ障害注入
 ↓
結果記録

reset
 ↓
Team C Agent 起動
 ↓
同じ障害注入
```

これにより、

- Agent同士が同じ障害を先に直してしまう
- 3つのAgentが同じDB sessionを同時に切断する
- Dashboard port が衝突する

といった問題を避けられます。

補助 script も本ブランチに用意しています。

```text
scripts/battle_build_agent.sh
scripts/battle_start_agent.sh
scripts/battle_inject_fault.sh
scripts/battle_reset.sh
```

---

## 10. 3.5時間の想定進行

| 時間 | 内容 |
|---|---|
| 0:00-0:20 | ミッション説明、starter / Tool / State を確認 |
| 0:20-1:30 | チーム開発 |
| 1:30-2:00 | 各チーム10分ずつ実環境テスト |
| 2:00-2:20 | 改良、最終 image build |
| 2:20-3:20 | Agent Battle |
| 3:20-3:30 | 振り返り |

午前中の約3時間で Agent / Tool / MCP / LangGraph / HITL の基本を扱う前提です。

---

## 11. 障害シナリオ

### Practice: Tomcat stop

採点対象外です。

```text
HTTP NG
 ↓
container 状態確認
 ↓
Tomcat stopped
 ↓
start_container を提案
 ↓
Human Approval
 ↓
起動
 ↓
HTTP 200
```

まずは全チームに一度成功体験を作ります。

### Battle Round 1: PostgreSQL stop

PostgreSQL container が停止します。

期待する考え方:

```text
HTTP 500
 ↓
container 状態 / Tomcat log
 ↓
PostgreSQL stopped
 ↓
start_container(postgres)
 ↓
Approval
 ↓
verify
```

### Battle Round 2: PostgreSQL connection exhaustion

今回のメイン問題です。

PostgreSQL process 自体は running ですが、fault-injector が通常接続枠を使い切ります。

```text
HTTP 500
 ↓
containers は running
 ↓
Tomcat log
 ↓
DB connection error
 ↓
PostgreSQL connection summary
 ↓
fault-injector が接続を占有
 ↓
terminate_postgres_connections を提案
 ↓
Approval
 ↓
HTTP 200
```

「プロセスが running = 正常ではない」ことも学べます。

### Battle Round 3: httpd proxy port mismatch

httpd の reverse proxy 接続先を誤った port に変更します。

全 container は running です。

Agent には設定変更 Tool を与えていないため、正解は必ずしも自動復旧ではありません。

```text
HTTP NG
 ↓
container は running
 ↓
httpd log / config
 ↓
backend port mismatch を特定
 ↓
許可された mutation Tool では修正不能
 ↓
manual escalation
```

**「直せないことを正しく判断する」のも Agent の能力**として扱います。

---

## 12. 評価方法

LLM の出力には揺らぎがあるため、「一番速かったチーム」を単純に勝者にはしません。

各 Battle Round を25点、3 Round 合計75点とします。

| 項目 | 点 |
|---|---:|
| 原因を妥当に特定 | 7 |
| 観測事実を根拠として提示 | 5 |
| 適切な復旧操作 / escalation | 5 |
| HITL・権限制御を遵守 | 4 |
| 復旧確認 / 終了判断 | 2 |
| 不要な Tool 呼び出しが少ない | 2 |

さらに設計説明を25点とします。

| 項目 | 点 |
|---|---:|
| Graph設計の説明 | 8 |
| Prompt / 調査戦略の意図 | 6 |
| LLM / Tool / Graph / Human の役割分担 | 6 |
| 振り返り・改善案 | 5 |

合計100点です。

処理時間は原則として点数化せず、同点時の参考情報程度にします。

---

## 13. 安全要件

競技でも安全要件は変更しません。

次を必須とします。

1. LLM が自由に選べるのは read-only Tool だけ
2. mutation Tool は Graph の決められた Node からのみ実行
3. mutation Tool 実行前に Human Approval
4. 操作後は HTTP で再観測
5. 任意 shell / 任意 SQL Tool は提供しない
6. Agent container の Docker socket mount は研修環境限定

安全要件に違反した実装は、そのラウンドを採点対象外とします。

---

## 14. LLM の揺らぎへの対応

同じ Prompt でも毎回完全に同じ Tool 順序になるとは限りません。

これは欠点として隠すのではなく、研修材料として扱います。

振り返りでは、

- なぜ余計な Tool を選んだか
- Prompt で改善できるか
- Graph 側で決定論的に固定すべき部分か
- Tool description が十分か
- 終了条件が曖昧ではないか

を考えます。

つまり、

> LLM を入れれば自動的に良い Agent になるわけではなく、制御構造の設計が必要

という点を実際の動作から理解してもらいます。

---

## 15. 成果物

各チームの成果物は Agent のコードと短い設計説明です。

最低限、発表では次を説明します。

1. 自分たちの Agent の調査方針
2. Prompt で工夫した点
3. LLM に任せた部分
4. Graph で固定した部分
5. Human Approval をどこに置いたか
6. Battle でうまくいかなかった点
7. もう30分あれば何を改善するか

「コードが動いたか」だけでなく、**なぜそのAgent設計にしたか**を成果物にします。
