"""Structured logs with correlation and session IDs. Never log message contents (PII).

Two formats: `json` (one object per line, for log pipelines) and `console` (one readable
line per event, for local debugging). Both carry file, line and function of the caller.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
session_id: ContextVar[str | None] = ContextVar("session_id", default=None)

LOGGER_NAME = "agent"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHORT_ID = 8


def _relative_path(pathname: str) -> str:
    try:
        return Path(pathname).resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return Path(pathname).name


def _short(value: str | None) -> str:
    return value[:SHORT_ID] if value else "-"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "file": _relative_path(record.pathname),
            "line": record.lineno,
            "function": record.funcName,
            "correlation_id": correlation_id.get(),
            "session_id": session_id.get(),
        }
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        time = datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3]
        where = f"{_relative_path(record.pathname)}:{record.lineno} {record.funcName}"
        ids = f"[{_short(correlation_id.get())} {_short(session_id.get())}]"
        fields = " ".join(f"{k}={v}" for k, v in getattr(record, "fields", {}).items())
        line = f"{time} {record.levelname:<7} {record.getMessage():<18} {where} {ids} {fields}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line.rstrip()


def configure_logging(log_format: Literal["console", "json"] = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ConsoleFormatter() if log_format == "console" else JsonFormatter())
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False


def log_event(event: str, level: int = logging.INFO, exc_info: bool = False, **fields: Any) -> None:
    """stacklevel=2 makes file/line/function point at the caller, not at this helper."""
    logging.getLogger(LOGGER_NAME).log(
        level, event, exc_info=exc_info, stacklevel=2, extra={"fields": fields}
    )
