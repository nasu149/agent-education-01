# PostgreSQL db-lock 障害シナリオ

## 目的

PostgreSQL のプロセスやコンテナが正常に動いていても、
SQL が lock wait に入るとアプリケーションは利用不能になることを学ぶシナリオです。

connection exhaustion とは原因が異なります。

| シナリオ | PostgreSQL | DB接続 | SQL |
|---|---|---|---|
| postgres-stop | stopped | 不可 | 不可 |
| db-connections | running | 新規接続が枯渇 | 不可 |
| db-lock | running | 可能 | lock wait で進まない |

## なぜ単純な行ロックではないか

PostgreSQL は MVCC を使うため、別トランザクションが行を UPDATE して
行ロックを保持していても、通常の SELECT はコミット済みの古い版を読めます。

この研修の Health Checker は GET /api/members を呼び、
内部では SELECT を実行します。

そのため、単純な行ロックだけでは Health Checker が障害を検知できません。

db-lock では、研修用 fault-locker が次を実行します。

~~~sql
BEGIN;
LOCK TABLE members IN ACCESS EXCLUSIVE MODE;
~~~

ACCESS EXCLUSIVE は SELECT が取得する ACCESS SHARE とも競合するため、
GET /api/members が lock wait になります。

## 障害注入

Plain Docker / Battle:

~~~bash
./scripts/battle_inject_fault.sh db-lock
~~~

直接:

~~~bash
bash ./scripts/inject_db_lock.sh
~~~

Docker Compose:

~~~bash
./scripts/inject_fault.sh db-lock
~~~

## fault-locker

fault-locker は専用の training user fault_injector で接続します。

~~~text
DB user          fault_injector
application_name fault-locker
~~~

ロックを取得した後は同じ transaction を開いたまま保持します。

管理者が backend を terminate した場合、再接続してロックを取り直すことはありません。

## Agent が利用できる観測 Tool

### get_postgres_lock_summary

固定 SQL で pg_blocking_pids() と pg_stat_activity を参照します。

主に次を返します。

~~~text
blocked_pid
blocked_application_name
blocked_wait_event_type
blocked_wait_event
blocked_query

blocker_pid
blocker_application_name
blocker_state
blocker_query
~~~

想定される重要な観測は次です。

~~~text
blocked_application_name = PostgreSQL JDBC client
blocked_wait_event_type   = Lock

blocker_application_name  = fault-locker
blocker_state             = idle in transaction
blocker_query             = LOCK TABLE members IN ACCESS EXCLUSIVE MODE
~~~

任意 SQL Tool は公開していません。

## 復旧

新しい mutation Tool は追加していません。

既存の

~~~text
terminate_postgres_connections(application_name)
~~~

を利用します。

安全上、application_name は allowlist 方式です。

~~~text
fault-injector
fault-locker
~~~

さらに DB user は fault_injector に限定しています。

期待フロー:

~~~text
HTTP timeout
  ↓
list_containers
  ↓
httpd / tomcat / postgres = running
  ↓
get_postgres_lock_summary
  ↓
fault-locker が blocker
  ↓
Diagnosis
  action = terminate_postgres_connections
  target_application = fault-locker
  ↓
Human Approval
  ↓
terminate
  ↓
PostgreSQL transaction rollback
  ↓
ACCESS EXCLUSIVE lock 解放
  ↓
GET /api/members = HTTP 200
~~~

## Reset

~~~bash
./scripts/battle_reset.sh
~~~

で fault-locker コンテナを削除します。

既に backend が Agent によって terminate 済みの場合でも、
injector process は再接続しないため再発しません。
