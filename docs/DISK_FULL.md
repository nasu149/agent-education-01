# Disk Full 障害シナリオ

## 目的

このシナリオでは、Tomcat / PostgreSQL / httpd の各コンテナがすべて
`running` でも、アプリケーションが使うファイルシステムの容量枯渇によって
Web API が利用不能になるケースを扱います。

さらに、Agent に任意 shell を与えず、

- ディスク使用率を確認する read-only Tool
- 大きなファイルを確認する read-only Tool
- 限定されたログだけを削除する mutation Tool

を使って復旧させます。

## 前提

前日の Docker 研修では volume / tmpfs を扱わなくても構いません。

AI Agent 研修の開始前に講師が Tomcat だけをこっそり作り直します。

Linux / Oracle Linux:

~~~bash
./scripts/prepare_disk_full_training.sh
~~~

Windows PowerShell:

~~~powershell
.\scripts\prepare_disk_full_training.ps1
~~~

このスクリプトは、

~~~text
httpd       そのまま
PostgreSQL  そのまま
Tomcat      再作成
~~~

とし、Tomcat に次を追加します。

~~~text
/training-disk
size = 16MB
type = tmpfs
~~~

通常の Docker named volume は、この研修で欲しい「小さく固定された容量」を
単純かつ移植性高く設定しにくいため、このブランチでは容量指定できる tmpfs を使います。

アプリには次の環境変数を設定します。

~~~text
AUDIT_LOG_PATH=/training-disk/audit/member-audit.log
~~~

名簿 API は各 request の最初に短い監査ログを1行追記します。
正常時の使用量はごく小さいため、通常の CRUD には影響しません。

## 障害ストーリー

想定ストーリーは「夜間に古い監査ログが異常増大した」です。

~~~text
昨日
  正常稼働
    ↓
夜間
  archive log が大量生成
    ↓
/training-disk 100%
    ↓
朝
  Tomcat running
  PostgreSQL running
  httpd running
    ↓
監査ログを書けない
    ↓
GET /api/members = HTTP 500
~~~

障害注入:

Linux / Oracle Linux:

~~~bash
./scripts/battle_inject_fault.sh disk-full
~~~

Windows PowerShell:

~~~powershell
.\scripts\battle_inject_fault.ps1 disk-full
~~~

直接実行する場合:

~~~bash
./scripts/inject_disk_full.sh
~~~

~~~powershell
.\scripts\inject_disk_full.ps1
~~~

障害注入スクリプトが作る大容量ファイルは、

~~~text
/training-disk/archive/training-old-audit.log
~~~

だけです。

ホストOSのディスクや PostgreSQL のデータ領域を埋めることはありません。

## アプリケーションの観測

ディスクが埋まると Tomcat log に、

~~~text
audit_write_failed
No space left on device
~~~

が出ます。

HTTP response も、

~~~json
{
  "error": "audit storage unavailable",
  "detail": "... No space left on device"
}
~~~

となります。

## read-only Tool

### get_disk_usage

~~~text
get_disk_usage(service="tomcat")
~~~

確認対象は `/training-disk` 固定です。

### list_large_files

~~~text
list_large_files(service="tomcat", limit=10)
~~~

`/training-disk` 配下だけをサイズ降順で確認します。

期待される観測:

~~~text
/training-disk/archive/training-old-audit.log
  -> 約16MB
~~~

LLM から任意パスや shell command は指定できません。

## mutation Tool

### cleanup_training_logs

~~~text
cleanup_training_logs(service="tomcat")
~~~

これはファイル削除を行うため mutation Tool です。

そのため LLM には直接 bind せず、

~~~text
investigate
  ↓
judge
  ↓
Human Approval
  ↓
remediate
  ↓
cleanup_training_logs
~~~

の順でのみ実行します。

削除可能な範囲も固定しています。

~~~text
削除可能:
  /training-disk/archive/training-*.log

削除不可:
  /training-disk/audit/member-audit.log
  Tomcat設定
  WAR
  OSファイル
  任意パス
~~~

つまり、

~~~text
run_shell("rm -rf ...")
~~~

のような強い Tool は Agent に与えません。

## 期待する Agent の調査

~~~text
Health Check NG
  ↓
http_request
  ↓
HTTP 500
audit storage unavailable
  ↓
list_containers
  ↓
全部 running
  ↓
get_container_logs(tomcat)
  ↓
audit_write_failed
No space left on device
  ↓
get_disk_usage(tomcat)
  ↓
100%
  ↓
list_large_files(tomcat)
  ↓
training-old-audit.log が大半を占有
  ↓
Diagnosis
  recommended_action = cleanup_training_logs
  target_service = tomcat
  ↓
Human Approval
  ↓
cleanup_training_logs(tomcat)
  ↓
verify
  ↓
GET /api/members = HTTP 200
~~~

## Reset

~~~bash
./scripts/battle_reset.sh
~~~

~~~powershell
.\scripts\battle_reset.ps1
~~~

でも `training-*.log` を削除するため、次チームへ障害を持ち越しません。

## 教育上のポイント

この障害では、

~~~text
container running != application healthy
~~~

だけでなく、

~~~text
危険なファイル削除を
なぜ専用 mutation Tool に閉じ込めるのか
~~~

も説明できます。

Agent に任意 shell を渡すのではなく、対象・パス・ファイル名を固定した Tool を用意し、
Human Approval の後だけ実行することがポイントです。
