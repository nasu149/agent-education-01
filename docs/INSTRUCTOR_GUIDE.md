# 講師ガイド

> このファイルは受講者にSecret challengeの前に見せない想定です。

## 推奨障害

### Level 1: Tomcat停止

```powershell
.\scripts\inject_fault.ps1 tomcat-stop
```

観測の例:

- HTTP 503/502
- `tomcat` exited
- httpd proxy error

期待action:

- `start_container`
- target `tomcat`
- Human Approval
- verify HTTP 200

### Level 2: PostgreSQL停止

```powershell
.\scripts\inject_fault.ps1 postgres-stop
```

観測の例:

- HTTP 500
- postgres exited
- Tomcat logにDB connection failure

期待action:

- `start_container`
- target `postgres`
- Human Approval
- verify HTTP 200

### Level 3: httpd backend port mismatch

```powershell
.\scripts\inject_fault.ps1 proxy-port
```

観測の例:

- 全container running
- HTTP failure
- httpd logにupstream接続失敗
- `read_config("httpd_proxy")` が `tomcat:18080`
- Tomcat自身は8080

期待action:

- `manual`
- 「設定変更権限がないのでエスカレーション」

ここで「Agentが直せない = 失敗」ではないことを説明します。

### Level 3: DB password mismatch

```powershell
.\scripts\inject_fault.ps1 db-password
```

観測の例:

- 全container running
- HTTP 500
- Tomcat logにpassword authentication failed
- Tomcat側DB設定は変わっていない

期待action:

- `manual`
- credential repairはAgentの権限外

## Secret challenge割当例

- Team A: `postgres-stop`
- Team B: `tomcat-stop`
- Team C: `proxy-port`
- Team D: `db-password`

## リセット

障害ごとに確実に戻すなら:

```powershell
.\scripts\reset.ps1
```

## 講師が強調する問い

1. monitorをLLMにしなかったのはなぜ？
2. `check_postgres()` Toolを作らなかったのはなぜ？
3. `docker exec` Toolを渡さなかったのはなぜ？
4. mutation ToolをLLMへ見せなかったのはなぜ？
5. Tool実行成功後になぜverifyする？
6. port mismatchを直せなかったAgentは失敗か？
7. MCPがなくてもAgentは作れるか？

最後の答えは「作れる」です。MCPはTool接続の規格であってAgentそのものではありません。
