# PostgreSQL 接続枯渇 障害調査シナリオ

このブランチでは、名簿アプリのコードを壊さずに、運用上の障害として PostgreSQL の通常接続枠を別プロセスが使い切る状況を再現します。

## 1. シナリオ

正常時:

```text
Browser
  -> httpd
  -> Tomcat
  -> PostgreSQL
```

障害注入後:

```text
fault-injector
  -> PostgreSQL に多数の接続を作成
  -> 通常ユーザー向け接続枠を使い切る

Tomcat
  -> 新しい DB 接続を作成できない
  -> CRUD API が 500

PostgreSQL
  -> プロセス自体は正常稼働
```

アプリケーションの close 漏れや SQL バグではありません。外部クライアントが PostgreSQL の接続リソースを占有した、という運用障害です。

## 2. なぜ障害中でも Agent は PostgreSQL を調査できるのか

デモ環境では次の設定です。

```text
max_connections = 20
superuser_reserved_connections = 3
```

アプリの `memberapp` と障害注入用の `fault_injector` はどちらも `NOSUPERUSER` です。

そのため fault-injector が通常接続枠を使い切っても、PostgreSQL は superuser 用の予約接続枠を残します。

MCP サーバーは管理用の `postgres` 接続を内部だけで使用するため、通常接続枠が枯渇した後でも `pg_stat_activity` を調査できます。

重要なのは、LLM に PostgreSQL の管理者資格情報や任意 SQL 実行機能を渡していないことです。

## 3. MCP Tool

### 読み取り専用

`get_postgres_connection_summary`

MCP 実装内に固定された SELECT だけを実行します。

取得する情報:

- `max_connections`
- `superuser_reserved_connections`
- 通常接続枠の概算
- `pg_stat_activity` の接続数
- DB ユーザー
- `application_name`
- client address
- state

モデルから SQL 文字列を渡すことはできません。

### 更新系

`terminate_postgres_connections(application_name)`

この Tool も任意 SQL ではありません。

デフォルトでは次の条件をすべて満たすセッションだけが対象です。

```text
application_name = fault-injector
DB user          = fault_injector
```

さらに LangGraph の Human-in-the-loop 承認後にしか呼ばれません。

## 4. 期待する Agent の調査フロー

```text
HTTP ヘルスチェック失敗
        |
        v
httpd / Tomcat / PostgreSQL コンテナ状態確認
        |
        v
Tomcat ログ確認
        |
        v
DB 接続エラーを発見
        |
        v
PostgreSQL は running
        |
        v
get_postgres_connection_summary
        |
        v
fault-injector が通常接続枠をほぼ占有
        |
        v
原因: PostgreSQL 接続枯渇
        |
        v
terminate_postgres_connections("fault-injector") を提案
        |
        v
Human-in-the-loop
        |
   承認 / 却下
        |
      承認
        v
fault-injector の DB session だけ terminate
        |
        v
HTTP GET /api/members を再試行
        |
        v
HTTP 200 -> 復旧確認
```

fault-injector は、管理者に session を切断された後に自動再接続しません。そのため Agent の復旧操作後は正常状態に戻ります。

## 5. plain Docker だけで試す

実研修の `docker run` 前提に合わせた確認方法です。Docker Compose は不要です。

### 起動

```bash
export GEMINI_API_KEY='YOUR_KEY'
bash scripts/pure_docker_up.sh
```

起動後:

```text
名簿アプリ: http://localhost:8088
Agent UI:   http://localhost:8090
```

正常時にまず名簿一覧が表示できることを確認してください。

### 障害注入

```bash
bash scripts/inject_db_connection_exhaustion.sh
```

障害注入コンテナのログ:

```bash
docker logs agent-education-fault-injector
```

次のような状態になります。

```text
Holding 5 connections.
Holding 10 connections.
Holding 15 connections.
Connection attempt blocked ...
Fault active: holding ... ordinary PostgreSQL sessions.
```

数秒後、名簿 API が失敗し、Agent がインシデント調査を開始します。

Agent UI で `terminate_postgres_connections` の承認要求が表示されたら、内容を確認して承認してください。

### 終了

```bash
bash scripts/pure_docker_down.sh
```

DB volume を残したい場合:

```bash
KEEP_DB_DATA=1 bash scripts/pure_docker_down.sh
```

## 6. Docker Compose で手早く試す場合

この方法はローカル検証用です。実研修で Compose を使う必要はありません。

```bash
cp .env.example .env
# .env の GEMINI_API_KEY を設定

docker compose down -v --remove-orphans
docker compose up -d --build
```

正常確認後:

```bash
sh scripts/inject_fault.sh db-connections
```

## 7. 手動で PostgreSQL の状態を見る

Agent が取得している情報と同じ考え方を人間が確認する場合:

```bash
docker exec -it agent-education-postgres \
  psql -U postgres -d memberdb
```

```sql
SHOW max_connections;
SHOW superuser_reserved_connections;

SELECT
    usename,
    application_name,
    state,
    count(*)
FROM pg_stat_activity
GROUP BY usename, application_name, state
ORDER BY count(*) DESC;
```

障害中は `fault_injector / fault-injector` の接続が大半を占めることを確認できます。

## 8. 実際の新人研修へ持ち込む場合の重要条件

新人が前日に plain Docker でコンテナを構築済みでも、障害注入そのものは後からできます。既存の PostgreSQL コンテナへ volume を追加する必要はありません。

ただし、接続枯渇シナリオを成立させるには、最初の Docker / DB 教育時点で次を満たしておく必要があります。

1. Tomcat が接続する DB ユーザーを superuser にしない。
2. 障害注入用の non-superuser DB ユーザーを事前に用意する。
3. Agent 用には、接続枯渇時にも利用できる管理接続経路を用意する。
4. Agent に任意 SQL Tool を与えず、固定用途の Tool に限定する。
5. session terminate のような更新操作は Human-in-the-loop を通す。

`max_connections=20` はこのリポジトリで素早く再現するためのデモ設定です。実研修ではデフォルト値のままでも fault-injector が十分な数の通常接続を確保すれば同じ障害を作れます。

## 9. この教材で学ばせたいポイント

単純に「PostgreSQL が落ちているから起動する」ではなく、次の違いを理解させることが目的です。

```text
PostgreSQL プロセスは生きている
        !=
アプリケーションが PostgreSQL を正常利用できる
```

さらに Agent 設計では、

```text
観測は LLM が Tool を選択
変更操作は用途限定 Tool
変更前に Human-in-the-loop
変更後に再疎通で検証
```

という安全な障害対応 Agent の基本形を確認できます。
