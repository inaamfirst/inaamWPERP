from __future__ import annotations

import contextvars
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "erp_request_id",
    default=None,
)


def set_request_id(value: str | None) -> contextvars.Token[str | None]:
    return _request_id.set(value)


def reset_request_id(token: contextvars.Token[str | None]) -> None:
    _request_id.reset(token)


def current_request_id() -> str | None:
    return _request_id.get()


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = current_request_id() or "-"
        return True


class JsonLogFormatter(logging.Formatter):
    """One-record JSON formatter for the rotating production log."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for name in ("operation", "method", "path", "status_code", "run_id", "worker_id"):
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True, default=str)


def _handler_for_path(root: logging.Logger, log_path: Path) -> bool:
    return any(
        isinstance(handler, RotatingFileHandler)
        and Path(handler.baseFilename).resolve() == log_path.resolve()
        for handler in root.handlers
    )


def configure_logging(
    level: str = "INFO",
    *,
    log_dir: str = "runtime_data/logs",
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Configure concise console logs plus safe, rotating structured logs."""

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # httpx logs full request URLs at INFO, including query-auth credentials.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    context_filter = RequestContextFilter()
    console_format = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] [request=%(request_id)s] %(message)s"
    )
    if not any(getattr(handler, "_erp_console_handler", False) for handler in root.handlers):
        console = logging.StreamHandler()
        console._erp_console_handler = True  # type: ignore[attr-defined]
        console.setFormatter(console_format)
        console.addFilter(context_filter)
        root.addHandler(console)

    try:
        directory = Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        log_path = (directory / "erp.jsonl").resolve()
        if not _handler_for_path(root, log_path):
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=max(max_bytes, 64 * 1024),
                backupCount=max(backup_count, 1),
                encoding="utf-8",
            )
            file_handler.setFormatter(JsonLogFormatter())
            file_handler.addFilter(context_filter)
            root.addHandler(file_handler)
    except OSError:
        # Do not make local development unusable because a diagnostics volume
        # is temporarily unavailable. Production preflight validates it first.
        root.warning("Unable to initialize the rotating ERP log directory.")
