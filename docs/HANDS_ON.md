# 午後ハンズオン手順

## ゴール

LangGraphのAPI暗記ではなく、次の境界を説明できることをゴールにします。

```text
普通のプログラム: 決められる処理
LLM:              状況依存の局所判断
Tool:             外界の観測・操作
MCP:              Toolの標準接続
Human:            危険操作の承認
LangGraph:        全体フロー・状態・権限の制御
```

## Step 0: starterを観察

`agent/src/agent/graph.py` を開いてください。

最初は、

```text
START -> investigate_placeholder -> END
```

だけです。

一方、Docker / MCP / monitor / UI はすでに完成しています。

Pythonの周辺実装ではなくGraph設計に集中するためです。

## Step 1: 調査できるAgentへ

### 考えること

「名簿アプリが使えない」という1情報から、必ず同じ順番で全部確認する必要はあるでしょうか。

例えば、

- HTTP 503 + Tomcat exited
- HTTP 500 + 全container running
- HTTP 503 + 全container running

では次に見るべき情報が違います。

この部分をLLMへ任せます。

### 実装するもの

1. `ChatGoogleGenerativeAI`
2. `catalog.read_only` を `bind_tools`
3. `investigate` node
4. 既に用意済みの `ToolNode`
5. conditional edge
6. `tools -> investigate`

期待Graph:

```text
investigate
   |
   | tool call
   v
 tools
   |
   +----> investigate
```

LLMがTool callを返さなくなったら次工程へ進めるようにします。

## Step 2: judge

自由な文章のまま復旧工程へ進ませず、`Diagnosis` にします。

`agent/models.py` に既に型があります。

考えるポイント:

> なぜ「調査」と「最終判断」を1Nodeに全部入れないのか？

答えの一つは、Graphの次工程が扱いやすい明示的Stateを作るためです。

## Step 3: approval

変更系ToolをLLMへbindしないでください。

```text
LLM
  X start_container
  X restart_container
```

代わりに、

```text
judge
  |
  v
approval
  |
  | approved
  v
remediate
```

とします。

`approval` で `interrupt()` を使います。

## Step 4: remediate

人間が承認したactionだけ、

```python
catalog.mutating[...]
```

から呼びます。

System Promptに「勝手に再起動しないで」とお願いするだけではなく、**構造的にLLMから権限を外す**ことがポイントです。

## Step 5: verify

復旧Toolが成功を返しただけで「直った」と判断してはいけません。

もう一度ユーザー視点でHTTPを観測します。

```text
Act -> Re-observe
```

です。

失敗時は `investigate` へ戻します。

## Step 6: 完成確認

講師が既知障害 `tomcat-stop` を入れます。

期待:

1. monitorが異常検知
2. Agent起動
3. LLMがread-only Toolを複数使用
4. `Diagnosis`
5. Dashboardに承認表示
6. 承認
7. Tomcat起動
8. HTTP 200確認
9. report

## Step 7: Secret challenge

原因を聞かずにAgentを起動したまま待ってください。

発表ではコード説明より、次を説明してください。

- 最初の観測
- 選んだTool
- Tool結果で次の選択がどう変わったか
- どこをLLMに任せたか
- どこをGraphで固定したか
- Humanをどこに置いたか
- 自動復旧できない障害をどう扱ったか
