from __future__ import annotations

import logging
import os
import socket
import time
from collections.abc import Callable

from erp.packages.core.config import get_settings
from erp.packages.core.logging import configure_logging
from erp.packages.core.production_services import write_worker_heartbeat

LOGGER = logging.getLogger(__name__)
SessionFactory = Callable[[], object]


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def run_once(session_factory: SessionFactory | None = None) -> dict[str, object]:
    from erp.packages.core.db.session import SessionLocal
    from erp.packages.core.push_services import process_push_notifications
    from erp.packages.core.woocommerce_services import (
        claim_next_woocommerce_sync_run,
        enqueue_pending_woocommerce_sync_runs,
        execute_woocommerce_sync_run,
        recover_stale_woocommerce_sync_records,
    )

    active_session_factory = session_factory or SessionLocal
    current_worker_id = worker_identity()
    heartbeat_enabled = session_factory is None
    claimed_run_id: str | None = None
    push_stats: dict[str, int] = {}

    def heartbeat(status: str, run_id: str | None = None) -> None:
        if not heartbeat_enabled:
            return
        if not write_worker_heartbeat(
            worker_id=current_worker_id,
            status=status,
            run_id=run_id,
        ):
            LOGGER.warning("Unable to update the worker heartbeat file.")

    db = active_session_factory()
    try:
        heartbeat("starting")
        push_stats = process_push_notifications(db)
        # Push delivery state must survive independently from WooCommerce work.
        db.commit()
        recovery = recover_stale_woocommerce_sync_records(db)
        queued_outbound_runs = enqueue_pending_woocommerce_sync_runs(db)
        claimed = claim_next_woocommerce_sync_run(db, worker_id=current_worker_id)
        # The lease must be durable before any network work begins.
        db.commit()
        if claimed is None:
            recovered_total = int(recovery["recovered_runs"]) + int(recovery["recovered_outbox"])
            message = "Worker idle: no WooCommerce sync jobs are queued."
            if push_stats["processed"]:
                message = f"{message} Processed {push_stats['processed']} push notification(s)."
            if recovered_total:
                message = f"{message} Recovered {recovered_total} stale record(s)."
            heartbeat("idle")
            return {
                "status": "idle",
                "message": message,
                **recovery,
                "queued_outbound_runs": queued_outbound_runs,
                "push": push_stats,
            }

        claimed_run_id = claimed.id
        heartbeat("running", claimed_run_id)
        completed = execute_woocommerce_sync_run(
            db,
            run_log_id=claimed_run_id,
            worker_id=current_worker_id,
            progress_callback=lambda: heartbeat("running", claimed_run_id),
        )
        if completed is None:
            heartbeat("failed", claimed_run_id)
            return {
                "status": "failed",
                "message": f"Worker could not reload queued sync job {claimed_run_id}.",
                **recovery,
                "push": push_stats,
            }
        heartbeat(completed.status, completed.id)
        return {
            "status": completed.status,
            "message": f"WooCommerce sync job {completed.id} finished: {completed.status}.",
            "run_id": completed.id,
            "attempts": completed.attempts,
            **recovery,
            "queued_outbound_runs": queued_outbound_runs,
            "push": push_stats,
        }
    except Exception as exc:
        db.rollback()
        heartbeat("failed", claimed_run_id)
        LOGGER.exception(
            "Worker run failure",
            extra={"run_id": claimed_run_id, "worker_id": current_worker_id},
        )
        return {
            "status": "failed",
            "message": (
                f"Worker failed while processing sync job {claimed_run_id or 'none'}: {exc}"
            ),
            "run_id": claimed_run_id,
            "push": push_stats,
        }
    finally:
        db.close()


def run_loop(
    *,
    poll_seconds: int,
    run_once_func: Callable[[], dict[str, object]] = run_once,
) -> None:
    while True:
        state = run_once_func()
        LOGGER.info("%s", state["message"])
        time.sleep(poll_seconds)


def main() -> None:
    settings = get_settings()
    configure_logging(
        settings.log_level,
        log_dir=settings.log_dir,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
    )
    if settings.worker_loop:
        LOGGER.info(
            "Worker loop starting with %s second poll interval.",
            settings.worker_poll_seconds,
        )
        run_loop(poll_seconds=min(settings.worker_poll_seconds, settings.push_poll_seconds))
        return
    state = run_once()
    LOGGER.info("%s", state["message"])
    print(state["message"])


if __name__ == "__main__":
    main()
