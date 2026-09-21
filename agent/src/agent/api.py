"""研修用ダッシュボードと、人間による承認操作を提供する FastAPI の入口。

起動時に設定・ログ・AgentRuntime を準備し、lifespan で監視の開始と終了を管理する。
HTTP ハンドラーは実行管理を runtime に委ね、画面表示やリクエストの受け渡しを担当する。
HITL（Human-in-the-loop）は、復旧操作の前に人間の判断を挟む仕組みを指す。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from agent.config import Settings
from agent.logging_setup import configure_logging
from agent.models import ApprovalBody
from agent.runtime import AgentRuntime
from agent.ui import PAGE


settings = Settings.from_env()
configure_logging(settings.log_level)
runtime = AgentRuntime(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Web アプリの起動・終了に合わせて、Agent の監視処理を開始・停止する。

    FastAPI からアプリ本体を引数として受け取るが、この処理では使用しない。
    yield より前で MCP ツールと Graph を準備し、監視タスクを開始する。
    yield 中に HTTP リクエストを処理し、終了時は finally で監視タスクを停止する。
    """
    await runtime.start()
    try:
        yield
    finally:
        await runtime.stop()


app = FastAPI(title="Agent Education Runtime", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """GET / に対して、研修用ダッシュボードの HTML を返す。

    ui.py の PAGE をそのまま返し、HTMLResponse によって HTML として配信する。
    監視状況などの動的な情報は、画面内の JavaScript が別途 /api/status から取得する。
    """
    return PAGE


@app.get("/api/status")
async def status() -> dict:
    """GET /api/status に対して、現在の監視・障害対応状況を辞書で返す。

    正常性、HTTP ステータス、承認待ちの内容、ノード履歴、イベント、報告を含む。
    runtime の表示用スナップショットを取得するだけで、新たな調査や復旧は開始しない。
    """
    return runtime.snapshot()


@app.post("/api/approval")
async def approval(body: ApprovalBody) -> dict:
    """POST /api/approval で人間の判断を受け取り、承認待ちの Graph を再開する。

    body.approved が True なら承認、False なら却下として runtime に渡す。
    再開後の処理が次の停止点または終了まで進むのを待ち、その時点の状態を返す。
    runtime.approve() が RuntimeError を送出した場合は HTTP 409 に変換する。
    例えば、承認待ちの障害がない状態での操作が該当する。
    """
    try:
        await runtime.approve(body.approved)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return runtime.snapshot()


@app.post("/api/trigger")
async def trigger() -> dict:
    """POST /api/trigger で、定期監視を待たずに現在のアプリ状態を調査する。

    講師のデモや動作確認用の入口。障害対応が進行中なら HTTP 409 を返す。
    それ以外は手動開始の説明文を付けて Graph を実行し、承認待ちまたは終了時の
    状態を返す。この呼び出し自身が故障を起こすわけではない。
    """
    if runtime.active_incident_id:
        raise HTTPException(status_code=409, detail="incident already active")
    await runtime.open_incident("Manual training trigger: investigate current application condition.")
    return runtime.snapshot()
