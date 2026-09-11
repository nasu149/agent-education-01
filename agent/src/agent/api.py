"""FastAPI entry point for the training dashboard and HITL endpoint."""

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
    """Start and stop the long-lived training runtime with the web application."""
    await runtime.start()
    try:
        yield
    finally:
        await runtime.stop()


app = FastAPI(title="Agent Education Runtime", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """Render the training dashboard."""
    return PAGE


@app.get("/api/status")
async def status() -> dict:
    """Return health, incident, approval and trace information."""
    return runtime.snapshot()


@app.post("/api/approval")
async def approval(body: ApprovalBody) -> dict:
    """Approve or reject the currently interrupted remediation."""
    try:
        await runtime.approve(body.approved)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return runtime.snapshot()


@app.post("/api/trigger")
async def trigger() -> dict:
    """Instructor/debug endpoint to start investigation without waiting for monitoring."""
    if runtime.active_incident_id:
        raise HTTPException(status_code=409, detail="incident already active")
    await runtime.open_incident("Manual training trigger: investigate current application condition.")
    return runtime.snapshot()
