"""Layer 11 - Recovery design: sagas with compensating actions.

A rebooking touches several systems (seat inventory, baggage, the booking itself). There is no
distributed transaction, so each step registers how to undo itself. If a later step fails, the
saga runs the compensations for the finished steps in reverse order. Idempotency keys (layer 7)
make each step and each compensation safe to repeat after a crash.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .observability import Tracer


@dataclass
class SagaStep:
    name: str
    action: Callable[[], dict]
    compensate: Callable[[dict], None] | None = None


@dataclass
class SagaResult:
    status: str  # completed | compensated | compensation_failed
    done: list[str]
    failed_step: str | None = None
    error: str | None = None
    compensated: list[str] = field(default_factory=list)


@dataclass
class Saga:
    name: str
    tracer: Tracer
    steps: list[SagaStep] = field(default_factory=list)

    def add(self, name: str, action: Callable[[], dict], compensate: Callable[[dict], None] | None = None) -> Saga:
        self.steps.append(SagaStep(name, action, compensate))
        return self

    def run(self) -> SagaResult:
        finished: list[tuple[SagaStep, dict]] = []
        for step in self.steps:
            try:
                result = step.action()
            except Exception as e:  # noqa: BLE001 - any failure triggers compensation
                self.tracer.span("saga", f"{self.name}:{step.name}", status="error", error=str(e))
                return self._unwind(finished, step.name, str(e))
            finished.append((step, result))
            self.tracer.span("saga", f"{self.name}:{step.name}")
        return SagaResult("completed", [s.name for s, _ in finished])

    def _unwind(self, finished, failed: str, error: str) -> SagaResult:
        undone = []
        for step, result in reversed(finished):
            if step.compensate is None:
                continue
            try:
                step.compensate(result)
            except Exception as e:  # noqa: BLE001
                self.tracer.span("saga", f"compensate:{step.name}", status="error", error=str(e))
                return SagaResult("compensation_failed", [s.name for s, _ in finished], failed, error, undone)
            undone.append(step.name)
            self.tracer.span("saga", f"compensate:{step.name}")
        return SagaResult("compensated", [s.name for s, _ in finished], failed, error, undone)
