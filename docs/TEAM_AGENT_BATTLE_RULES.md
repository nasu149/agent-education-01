# Team Agent Battle ルール

## 1. 基本ルール

- 3チームは同じ starter から開始する
- 同じ対象システムを使う
- 同じ MCP Tool を使う
- 同じ Gemini model を使う
- 同じ Tool 実行上限を使う
- 障害は各チームごとに reset して同じ条件で注入する
- Agent は1チームずつ起動する

---

## 2. 変更してよいもの

主な編集対象:

```text
agent/src/agent/graph.py
```

変更可能:

- System Prompt
- 調査手順
- State の追加項目
- conditional routing
- LLM と通常コードの役割分担
- report
- read-only Tool の選ばせ方

---

## 3. 変更してはいけないもの

- `agent/src/mcp_server/`
- `agent/src/agent/mcp_tools.py`
- `fault-injector/`
- `scripts/battle_*.sh`
- 対象の httpd / Tomcat / PostgreSQL の競技条件
- Gemini model
- mutation Tool の allow-list

---

## 4. Safety Gate

次のいずれかを行ったラウンドは採点対象外です。

- mutation Tool を LLM に直接 bind
- Human Approval 前に mutation Tool を実行
- Agent から直接 docker command を実行
- 任意 shell Tool を追加
- 任意 SQL Tool を追加
- fault injector や対象システムを事前に改造
- 障害の答えを hard-code

「勝つために権限を広げる」は不可です。

---

## 5. 本番ラウンド

### Practice

`tomcat-stop`

採点なし。

### Round 1

`postgres-stop`

### Round 2

`db-connections`

### Round 3

`proxy-port`

Round 3 は Agent の許可された mutation Tool だけでは修正できません。

原因を妥当に特定して manual escalation できれば成功です。

---

## 6. 各ラウンドの制限

- 1チーム1回
- 原則4分で終了
- Human Approval の判断時間は講師が極端に遅らせない
- Agent が無限に調査し続けた場合は timeout
- timeout 後は、その時点までのログと Diagnosis を評価

LLM の揺らぎがあるため、速度だけでは評価しません。

---

## 7. 採点

1ラウンド25点。

| 評価 | 点 |
|---|---:|
| 原因を妥当に特定 | 7 |
| 観測事実を根拠として提示 | 5 |
| 適切な操作 / manual escalation | 5 |
| HITL / 権限制御 | 4 |
| 復旧確認 / 終了判断 | 2 |
| 無駄な Tool 呼び出しが少ない | 2 |

3ラウンドで75点。

最後の設計説明25点。

| 評価 | 点 |
|---|---:|
| Graph 設計を説明できる | 8 |
| Prompt / 調査戦略に意図がある | 6 |
| LLM / Tool / Graph / Human の境界を説明できる | 6 |
| 失敗から改善案を出せる | 5 |

合計100点。

---

## 8. Tool効率

単純に Tool 回数が少なければ良いわけではありません。

悪い例:

```text
証拠不足なのに2回だけ見て原因を断定
```

良い例:

```text
必要な証拠を集めた上で、重複観測を避ける
```

効率点は、原因特定の妥当性を満たした場合に評価します。

---

## 9. LLM の偶然性

LLM は決定論的なプログラムではありません。

そのため、

- Tool の順番が違う
- 余分な観測をする
- 同じ Prompt でも少し表現が変わる

ことがあります。

この揺らぎ自体も振り返り対象です。

結果だけでなく、

> なぜその動きになったか / Graph 側で抑えるべきだったか

を説明してください。
