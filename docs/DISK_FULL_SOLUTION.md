# Disk Full 模範解答

この文書は `training/disk-full` の TODO D1〜D5 に対する模範解答の考え方を説明します。

## 差分の見方

~~~text
training/disk-full
        ↓
training/disk-full-solution
~~~

solution branch は問題文・TODO・placeholderを削除せず、回答を直下へ追加しています。
したがって branch compare では、受講者が追加するコードを追いやすくしています。

## TODO D1 - get_disk_usage

講師側で用意した `_training_disk_usage(service)` を呼び出します。

この helper は、service が Tomcat であること、`/training-disk` 固定であること、
`df -Pk` の結果を構造化することを担当します。

Tool自身は薄くし、LLMへ任意 path を渡さないことがポイントです。

## TODO D2 - list_large_files

`/training-disk` だけを対象に `find + du` を実行し、サイズ降順で返します。
`limit` は 1〜20 に丸めます。

~~~text
LLMが指定できる:
  service=tomcat
  limit

LLMが指定できない:
  path
  shell command
~~~

## TODO D3 - cleanup_training_logs

mutation Tool は `/training-disk/archive/training-*.log` だけを削除します。
active log の `/training-disk/audit/member-audit.log` は削除しません。

候補を列挙した後でも prefix / suffix を再確認してから削除します。
復旧結果として deleted_files / failed_files / before / after を返します。

## TODO D4 - ToolCatalog

~~~text
READ_ONLY_TOOL_NAMES
  get_disk_usage
  list_large_files

MUTATING_TOOL_NAMES
  cleanup_training_logs
~~~

mutation Tool を investigator_llm に bind しないことが重要です。

## TODO D5 - Diagnosis / Prompt / Approval

`cleanup_training_logs` を Diagnosis の `recommended_action` に追加します。

調査Promptには `No space left on device`、`audit storage unavailable`、
`audit_write_failed` を観測した場合にディスク状態を確認する方針を追加します。

ただし障害名だけで決め打ちせず、`get_disk_usage` と `list_large_files` の観測結果まで
揃った場合だけ `cleanup_training_logs` を選ぶよう judge に条件を書きます。

最後に `after_judge` で `cleanup_training_logs` を approval 対象に加えます。

## 完成時の安全境界

~~~text
LLM
  ↓ read-only only
get_disk_usage / list_large_files
  ↓
Diagnosis
  ↓
Human Approval
  ↓
cleanup_training_logs
  ↓
verify HTTP 200
~~~

ファイル削除という危険な操作を、LLMへ直接渡さずGraph側で制御している点が、この課題の中心です。
