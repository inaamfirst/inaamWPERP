from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from erp.apps.worker import main as worker_main
from erp.apps.worker.main import run_once
from erp.packages.core.db import session as db_session
from erp.packages.core.db.base import Base
from erp.packages.core.db.models import Setting


def test_worker_shell_reports_idle(tmp_path: Path) -> None:
    assert Setting.__tablename__ == "settings"
    engine = create_engine(
        f"sqlite:///{tmp_path / 'worker.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )

    state = run_once(session_factory=session_factory)
    engine.dispose()

    assert state["status"] == "idle"
    assert "no WooCommerce sync jobs are queued" in state["message"]


def test_worker_publishes_heartbeat_when_using_managed_session(
    monkeypatch,
    tmp_path: Path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'worker_heartbeat.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    heartbeats: list[dict[str, object]] = []

    monkeypatch.setattr(db_session, "SessionLocal", session_factory)
    monkeypatch.setattr(worker_main, "worker_identity", lambda: "test-worker:1")
    monkeypatch.setattr(
        worker_main,
        "write_worker_heartbeat",
        lambda **payload: heartbeats.append(payload) or True,
    )

    state = run_once()
    engine.dispose()

    assert state["status"] == "idle"
    assert heartbeats == [
        {"worker_id": "test-worker:1", "status": "starting", "run_id": None},
        {"worker_id": "test-worker:1", "status": "idle", "run_id": None},
    ]