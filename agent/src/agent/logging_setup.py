"""Web API と障害対応 Graph が共通で使うログの出力先・書式を設定する。

標準エラー出力は docker logs での確認用、ファイル出力はログを保存するために使う。
このモジュールを import しただけでは設定せず、起動側から configure_logging() を呼ぶ。
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys


def configure_logging(level: str) -> None:
    """ログレベルと、コンソール・容量制限付きファイルへの出力を設定する。

    level には INFO や DEBUG などのログレベル名を渡す。時刻、レベル、ロガー名、
    本文の順で出力し、ファイルは UTF-8 の /app/logs/agent.log に保存する。
    ファイルが約 2 MB に達すると切り替え、過去のファイルを最大 3 個保持する。

    ルートロガーに既存のハンドラーがあれば何も変更せず戻る。二重出力を避けるための
    条件であり、その場合はここで指定したレベルやファイル出力も設定されない。
    戻り値はなく、ロガーの設定変更とログディレクトリの作成が副作用となる。
    """
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
