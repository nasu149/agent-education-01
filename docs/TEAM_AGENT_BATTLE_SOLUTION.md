# Team Agent Battle - 模範解答の見方

このブランチ `training/team-agent-battle-solution` は、
`training/team-agent-battle` を土台にした講師用模範解答です。

## 方針

starter 側の TODO コメントや placeholder は、できるだけ削除していません。

```text
nodes.py
  TODO 1〜4
  -> Prompt / investigate / judge / approval

graph.py
  TODO 5
  -> Node / Edge の配線
```

solution では、その TODO の直下へ `# ===== 模範解答 =====` 相当のコードを追記しています。

たとえば `investigate` は、

```python
# TODO 2: investigate を実装する
async def investigate(...):

    # ===== 模範解答（TODO 2）=====
    ...
    return {"messages": [response]}

    raise NotImplementedError(...)
```

という形です。

最後の `raise NotImplementedError(...)` は starter の行をそのまま残しています。
模範解答側で先に `return` するため、solution では到達しません。

TODO 5 も同じ考え方で、完成 Graph を先に compile / return し、
starter の placeholder Graph は下に残しています。

そのため、GitHub で

```text
training/team-agent-battle
        ↓ compare
training/team-agent-battle-solution
```

を見ると、かなりそのまま「新人が追記した解答コード」として読めます。

---

## ファイル構成

```text
agent/src/agent/
├─ graph.py
├─ nodes.py
├─ runtime.py
├─ mcp_tools.py
└─ models.py
```

### graph.py

LangGraph の構造だけに集中します。

```text
START
  ↓
investigate ← tools
  ↓
judge
  ↓
approval
  ↓
remediate
  ↓
verify
  ├─ NG → investigate
  └─ OK → report
```

### nodes.py

各 Node が何をするかを定義します。

```text
IncidentState
Prompt
IncidentNodes
  ├─ investigate
  ├─ tools
  ├─ judge
  ├─ approval
  ├─ remediate
  ├─ verify
  └─ report
```

`IncidentNodes` が settings / ToolCatalog / LLM / callback を保持するため、
以前のように `build_graph()` の中へ大量の nested function を置く必要がありません。

---

## TODO 1

`nodes.py` の `INVESTIGATION_SYSTEM_PROMPT` を改善します。

模範解答では、

- 観測を推測より優先
- broad → deep に調査
- 複数の証拠を関連付ける
- PostgreSQL が running でも利用不能はあり得る
- 必要な情報が集まったら Tool を止める
- mutation Tool を要求しない
- Tool結果を捏造しない

という方針を持たせています。

---

## TODO 2 - investigate

`self.investigator_llm` には read-only Tool だけが bind 済みです。

```text
investigate
  ↓
LLM が次の観測を選ぶ
  ↓
tool_calls あり
  ↓
tools
  ↓
investigate
```

観測数が `MAX_INVESTIGATION_TOOL_RESULTS` に達した場合は、
Tool を bind していない `self.llm` に切り替え、
現在までの証拠で結論を出させます。

---

## TODO 3 - judge

自由な調査履歴を `Diagnosis` へ変換します。

```text
messages
   ↓
judge
   ↓
Diagnosis
  root_cause
  evidence
  recommended_action
  target_service
  target_application
  confidence
```

LLM の自由な探索と、後続 Graph が扱う明示的 State を分けるための Node です。

---

## TODO 4 - approval

状態変更の直前で `interrupt()` します。

```text
Diagnosis
   ↓
approval
   ↓
Human
   ├─ approve → remediate
   └─ reject  → report
```

mutation Tool は LLM に直接 bind しません。

---

## TODO 5 - graph.py

`graph.py` では Node の中身を書かず、接続だけを書きます。

```python
builder.add_node("investigate", nodes.investigate)
builder.add_node("tools", nodes.tools)
builder.add_node("judge", nodes.judge)
...
```

routing は、

```text
investigate
  tool_callsあり -> tools
  なし           -> judge

judge
  mutation必要 -> approval
  manual/none  -> report

approval
  approved -> remediate
  rejected -> report

verify
  success -> report
  failure -> investigate
```

です。

---

## この分割にした理由

以前は `build_graph()` の中にすべての Node 関数が nested function として入っていました。

nested function には、

- 外側の settings や LLM をそのまま参照できる
- Graph 専用関数として閉じ込められる

というメリットがあります。

ただし今回のように Node が増えると、

```text
build_graph()
  数百行
```

となり、Graph の配線を読むだけでも各 Node の実装をスクロールする必要がありました。

そこで、

```text
nodes.py = What
graph.py = Flow
```

に分離しています。

研修では、

1. まず graph.py で全体フローを見る
2. 次に nodes.py で各 Node の中身を見る

という順番で説明すると理解しやすくなります。
