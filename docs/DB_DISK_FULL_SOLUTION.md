# DB Disk Full 模範解答

## E1: get_postgres_training_disk_usage

講師側helper `_training_db_disk_usage(service)` を呼び、`/training-disk` のdf結果を構造化して返します。任意pathはLLMに渡しません。

## E2: list_postgres_training_disk_files

`/training-disk` 固定で `find + du` を実行し、サイズ降順で最大20件返します。外部入力はserviceとlimitだけです。

## E3: cleanup_postgres_training_exports

削除対象は定数 `TRAINING_DB_EXPORT_PATH` の完全一致1ファイルだけです。

~~~text
/training-disk/archive/training-overnight-export.bin
~~~

`pgspace` や通常のPostgreSQLデータを削除する機能はありません。cleanup前後のdisk usageも返します。

## E4: ToolCatalog

~~~text
READ_ONLY
  get_postgres_training_disk_usage
  list_postgres_training_disk_files

MUTATING
  cleanup_postgres_training_exports
~~~

mutation ToolはLLMにbindしません。

## E5: Agent判断

synthetic write probeが失敗してもGETが200かつPostgreSQLがrunningなら、DB停止と決めつけずtraining diskを追加調査します。

`cleanup_postgres_training_exports` は、disk高使用率と `training-overnight-export.bin` の肥大化が両方観測された場合だけ選び、Human Approvalへ進めます。

## Javaアプリは変更なし

このsolutionでも `member-app` のJavaソースは `training/team-agent-battle-solution` と同一です。障害検知と復旧はPostgreSQL側のtraining-onlyな仕掛けとAgent側で実現します。
