# Disk Full 拡張課題

## 目的

コンテナが running でもアプリケーションは壊れることと、
副作用のある復旧操作を **狭い Tool + Human Approval** で扱うことを学びます。

## 障害の仕組み

~~~text
/training-disk
├─ audit/
│  └─ member-audit.log
└─ archive/
   └─ training-old-audit.log
~~~

研修用領域は16MBです。満杯になると監査ログ追記に失敗し、HTTP 500になります。

## TODO D1 - get_disk_usage

- Tomcat のみ
- path は `/training-disk` 固定
- helper `_training_disk_usage(service)` を利用してよい
- read-only Tool

## TODO D2 - list_large_files

- `/training-disk` 配下だけを調査
- 任意 path を引数にしない
- limit は 1〜20
- path / size_kb を返す
- read-only Tool

## TODO D3 - cleanup_training_logs

- Tomcat のみ
- `/training-disk/archive/training-*.log` のみ削除
- active audit log は削除禁止
- cleanup 前後の disk usage を返す
- deleted / failed を返す
- mutation Tool

## TODO D4 - ToolCatalog

追加Toolを `READ_ONLY_TOOL_NAMES` / `MUTATING_TOOL_NAMES` に正しく分類してください。
LLMへ渡すのは read-only だけです。

## TODO D5 - Agent判断

`cleanup_training_logs` を Diagnosis の action に追加し、
必要な場合だけ Human Approval へ進むようにしてください。

Promptはdisk-fullを決め打ちせず、ファイル書き込みエラーが観測された場合に
ディスク状態を追加調査する方針にしてください。

## 合格条件

~~~text
1. HTTP 500を検知
2. 全コンテナrunningを確認
3. No space left on deviceを根拠に追加調査
4. /training-disk高使用率を観測
5. 大容量training-old-audit.logを観測
6. cleanup_training_logsを提案
7. Human Approval前には削除しない
8. 承認後に限定ログだけ削除
9. verifyでHTTP 200
~~~

## 禁止

- mutation ToolをLLMに直接bind
- run_shell(command)
- delete_file(path)
- 障害名によるhard-code
