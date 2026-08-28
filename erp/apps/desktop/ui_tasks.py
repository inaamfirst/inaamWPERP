from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class TaskSignals(QObject):
    result = Signal(object)
    error = Signal(object)
    finished = Signal()


class UiTask(QRunnable):
    def __init__(self, operation: Callable[[], object]) -> None:
        super().__init__()
        self.operation = operation
        self.signals = TaskSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            self.signals.result.emit(self.operation())
        except BaseException as exc:  # delivered to the main thread for display
            self.signals.error.emit(exc)
        finally:
            self.signals.finished.emit()


class UiTaskRunner:
    """Run API work away from the Qt GUI thread and marshal callbacks safely."""

    def __init__(self, parent: QObject | None = None) -> None:
        self.parent = parent
        self.pool = QThreadPool.globalInstance()
        self._active: set[UiTask] = set()

    def start(
        self,
        operation: Callable[[], object],
        *,
        on_result: Callable[[object], None],
        on_error: Callable[[BaseException], None],
        on_finished: Callable[[], None] | None = None,
    ) -> UiTask:
        task = UiTask(operation)
        self._active.add(task)
        task.signals.result.connect(on_result)
        task.signals.error.connect(on_error)

        def finish() -> None:
            self._active.discard(task)
            if on_finished:
                on_finished()

        task.signals.finished.connect(finish)
        self.pool.start(task)
        return task
