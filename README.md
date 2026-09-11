# agent-education-01

新人向け **AI活用 / AI Agent研修** の教材リポジトリです。

題材は、Java / Docker研修で構築した想定の名簿管理Webシステムです。

```text
Browser -> httpd -> Tomcat -> Java Servlet -> PostgreSQL
```

最終日に、このシステムを運用する **一次障害対応Agent** をLangGraphで構築します。

## 利用するブランチ

| Branch | 用途 |
|---|---|
| [`instructor-ready`](../instructor-ready) | 講師準備済み環境 + 受講者が午後ハンズオンを開始するStarter |
| [`student-complete`](../student-complete) | 受講者が最終的に到達する完成版 / 講師用解答 |

`main` は案内用です。研修実施時は上記2ブランチを使用してください。

## 教育上の中心テーマ

単に「LLMからMCP Toolを呼ぶ」研修にはしていません。

```text
Observe -> Decide -> Act -> Re-observe
```

を中心に、次の境界を体験する構成です。

- 決定論的な監視は通常プログラム
- 状況依存の調査判断はLLM
- 外界の観測 / 操作はTool
- Tool接続はMCP
- 危険な変更操作はHuman-in-the-loop
- 全体フロー、State、権限境界はLangGraph

詳細な起動手順、午後ハンズオン、障害注入シナリオ、講師向け説明は各ブランチのREADMEを参照してください。
