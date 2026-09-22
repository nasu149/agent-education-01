> **このブランチ `training/db-disk-full-solution` は講師用模範解答です。**  
> `training/db-disk-full` のTODO・placeholderを残したまま、回答コードだけを追記しています。  
> branch diffで受講者が追加する実装をそのまま確認できます。

# AI Agent研修 - DB Disk Full 拡張課題

> **このブランチ `training/db-disk-full` は受講者向けの問題版です。**
>
> 前日の Java CRUD アプリは一切変更しません。
> `member-app/src` / WAR / Tomcat アプリの再コンパイル・再デプロイは不要です。

## シナリオ

前日の構成をそのまま使います。

~~~text
Browser -> httpd -> Tomcat -> PostgreSQL
~~~

追加するのは PostgreSQL 側の研修用ストレージだけです。

~~~text
PostgreSQL container

/var/lib/postgresql/data
  └─ 通常のDBデータ

/training-disk  32MB tmpfs
  ├─ pgspace/
  │   └─ training_write_audit
  └─ archive/
      └─ training-overnight-export.bin
~~~

`members` テーブル自体は通常の PostgreSQL データ領域に残します。

DB側にtraining-onlyのINSERT triggerを追加し、既存アプリの `POST /api/members` が成功したときだけ `training_write_audit` に監査レコードを1件書きます。

## なぜ Java を変更しないのか

Javaアプリは元からCRUDを持っています。

~~~text
GET    /api/members       -> SELECT
POST   /api/members       -> INSERT
PUT    /api/members/{id}  -> UPDATE
DELETE /api/members/{id}  -> DELETE
~~~

この既存POSTをsynthetic write health checkとして使います。

~~~text
POST synthetic member
  ↓
正常なら201
  ↓
DELETE synthetic member
  ↓
正常

disk-full時:
POST
  ↓
members INSERT
  ↓
DB-side audit trigger
  ↓
training_write_audit へ書けない
  ↓
transaction rollback
  ↓
HTTP 500
~~~

disk-full中でも `GET /api/members` は200のままです。つまり「HTTPが返る = 正常」ではなく、実際の書き込みまで確認するsynthetic monitoringを扱えます。

## 講師側の準備

Linux / Oracle Linux:

~~~bash
./scripts/prepare_db_disk_full_training.sh
~~~

Windows PowerShell:

~~~powershell
.\scripts\prepare_db_disk_full_training.ps1
~~~

Tomcat / Java / httpdは変更せず、PostgreSQL containerだけ既存volumeを使って作り直します。

## 障害注入

~~~bash
./scripts/battle_inject_fault.sh db-disk-full
~~~

~~~powershell
.\scripts\battle_inject_fault.ps1 db-disk-full
~~~

夜間exportが暴走した想定で `/training-disk/archive/training-overnight-export.bin` をddで肥大化させます。

## 受講者課題

主に編集するのは次の4ファイルです。

~~~text
agent/src/mcp_server/server.py
agent/src/agent/mcp_tools.py
agent/src/agent/models.py
agent/src/agent/nodes.py
~~~

- TODO E1: `get_postgres_training_disk_usage()`
- TODO E2: `list_postgres_training_disk_files()`
- TODO E3: `cleanup_postgres_training_exports()`
- TODO E4: read-only / mutation Tool の分類
- TODO E5: Diagnosis / Prompt / Human Approval routing

## Safety

復旧Toolが削除できるのは完全一致の1ファイルだけです。

~~~text
/training-disk/archive/training-overnight-export.bin
~~~

`/training-disk/pgspace/*`、通常のPostgreSQLデータ、任意path、任意shellは触れません。

## 完成時の期待フロー

~~~text
synthetic write probe: POST -> 500
    ↓
GETは200 / 全container running
    ↓
get_postgres_training_disk_usage -> 100%
    ↓
list_postgres_training_disk_files
    ↓
training-overnight-export.bin が大部分
    ↓
Diagnosis
    ↓
Human Approval
    ↓
cleanup_postgres_training_exports
    ↓
verify: POST 201 -> DELETE 200
~~~

詳細: [docs/DB_DISK_FULL.md](docs/DB_DISK_FULL.md)
