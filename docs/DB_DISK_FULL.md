# DB Disk Full シナリオ詳細

## 方針

前日のJava研修成果物を変更しません。MemberServlet、Database.java、pom.xml、WAR、Tomcatアプリのデプロイ内容はそのままです。

PostgreSQL containerに32MBのtmpfs `/training-disk` を追加し、training-onlyのtablespaceと監査triggerをDB側だけに作ります。

## DB側の仕掛け

~~~text
/training-disk
├─ pgspace/  -> training_disk_ts
│              └─ training_write_audit
└─ archive/
   └─ training-overnight-export.bin
~~~

`members` への既存INSERT後にDB triggerが `training_write_audit` へ1件書きます。同一transactionなので監査表の書き込みがENOSPCで失敗すると元のmembers INSERTもrollbackされます。

## Synthetic write health check

従来のGET-only監視だとdisk-full中もGET=200です。そのためAgent runtimeは既存CRUDを使い、POSTで一時memberを作成してDELETEします。

~~~text
POST -> 201
DELETE -> 200
=> Healthy
~~~

## 障害注入

障害注入直前に `TRUNCATE training_write_audit` し、次のINSERTが新しいDB blockを必要とする状態にします。その後 `training-overnight-export.bin` でfilesystemを埋めます。

結果:

~~~text
GET  /api/members -> 200
POST /api/members -> 500
~~~

## TODO E1

`get_postgres_training_disk_usage()` を実装します。対象はpostgres、pathは `/training-disk` 固定です。

## TODO E2

`list_postgres_training_disk_files()` を実装します。任意pathは受け取らず、pathとsize_kbを返します。

## TODO E3

`cleanup_postgres_training_exports()` を実装します。削除可能なのは `/training-disk/archive/training-overnight-export.bin` 完全一致だけです。

## TODO E4

観測ToolをREAD_ONLY、cleanupをMUTATINGへ分類します。mutation ToolはLLMへbindしません。

## TODO E5

write probe失敗時にDB disk-fullも調査できるPrompt、Diagnosis action、Human Approval routingを追加します。

## 合格条件

- Javaアプリのソースを変更しない
- GETは200のまま
- POSTはdisk-full中に500
- disk使用率と大容量exportを観測できる
- cleanupはHITL後だけ実行
- export以外は削除できない
- 復旧後synthetic POST/DELETEが成功する
