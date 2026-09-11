"""Logging setup shared by the web backend and Agent graph."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys


def configure_logging(level: str) -> None:
    """Configure human-readable console and rotating file logs once."""
    root = logging.getLogger()
    if root.handlers:
        return

    root.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    root.addHandler(console)

    log_dir = Path("/app/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "agent.log",
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
