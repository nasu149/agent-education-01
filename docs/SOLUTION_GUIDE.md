# 完成版の設計意図

## なぜ monitor Node がないのか

HTTP status を定期確認するだけなら LLM は不要です。`runtime.py` の普通のコードが障害を検知し、初めて LangGraph を起動します。

この境界そのものが教材です。

## なぜ investigate と judge を分けたのか

`investigate` は状況に応じて Tool を選ぶ自由度が必要です。

一方、次工程へ渡す判断は `Diagnosis` という構造化データに固定します。

これにより「全部LLM」でも「全部if」でもない設計になります。

## なぜ mutation Tool を bind_tools しないのか

System Prompt で「勝手に再起動しないで」と書くだけでは、権限制御として弱いからです。

モデルが知っている Tool は read-only だけです。

`start_container` / `restart_container` は人間が承認した後に `remediate` Node が明示的に呼びます。

## なぜ設定誤りを自動修正しないのか

最初のAgent研修では「できることを増やす」より「権限を限定する」経験を優先しています。

原因を正しく特定し、安全にエスカレーションできれば一次対応Agentとして成功です。
