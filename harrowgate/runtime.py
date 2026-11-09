"""Layer 10 - Runtime: durable execution that survives timeouts, crashes and runaway loops.

* `ToolClient` wraps every tool call with a timeout, bounded retries with exponential backoff
  (simulated time), a per-request budget and a trace span per attempt.
* `DurableRunner` runs a plan step by step and writes a checkpoint after each step, so a new
  process can `resume()` from the last finished step. A cancel token is checked between steps.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field

from .observability import Tracer
from .state import StateStore
from .tools import ToolServer, ToolTimeout


class BudgetExceeded(Exception):
    pass


class ToolFailed(Exception):
    """Retries exhausted on a transient error."""


class ToolRejected(Exception):
    """The tool answered with an error (business rule, access, bad arguments)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class SimulatedCrash(Exception):
    """Raised to imitate the process dying after a step's side effects but before its checkpoint."""


class Cancelled(Exception):
    pass


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_backoff_ms: int = 200
    timeout_ms: int = 2000

    def backoff(self, attempt: int) -> int:
        return self.base_backoff_ms * (2 ** (attempt - 1))


@dataclass
class Budget:
    max_tool_calls: int
    max_tokens: int
    max_sim_ms: int
    tool_calls: int = 0
    tokens: int = 0

    def charge_tool(self) -> None:
        self.tool_calls += 1
        if self.tool_calls > self.max_tool_calls:
            raise BudgetExceeded(f"tool calls {self.tool_calls} > {self.max_tool_calls}")

    def charge_tokens(self, n: int) -> None:
        self.tokens += n
        if self.tokens > self.max_tokens:
            raise BudgetExceeded(f"tokens {self.tokens} > {self.max_tokens}")

    def check_time(self, sim_ms: int) -> None:
        if sim_ms > self.max_sim_ms:
            raise BudgetExceeded(f"latency {sim_ms} ms > {self.max_sim_ms} ms")


@dataclass
class ToolClient:
    server: ToolServer
    tracer: Tracer
    budget: Budget
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    _ids: int = 0

    def call(self, caller: str, tool: str, args: dict, *, token: str | None = None,
             idem_key: str | None = None) -> dict:
        params = {"name": tool, "arguments": args}
        if token:
            params["decision_token"] = token
        if idem_key:
            params["idempotency_key"] = idem_key
        latency = self.server.registry[tool].latency_ms
        for attempt in range(1, self.retry.max_attempts + 1):
            self.budget.charge_tool()
            self._ids += 1
            final = attempt == self.retry.max_attempts
            try:
                resp = self.server.handle({"jsonrpc": "2.0", "id": self._ids, "method": "tools/call",
                                           "params": params}, caller)
            except ToolTimeout as e:
                self.tracer.span("tool", tool, sim_ms=self.retry.timeout_ms, status="timeout", error=str(e),
                                 caller=caller, args=args, attempt=attempt, attempt_final=final, idem_key=idem_key)
                if final:
                    raise ToolFailed(f"{tool} failed after {attempt} attempts") from None
                self.tracer.span("runtime", "backoff", sim_ms=self.retry.backoff(attempt), tool=tool, attempt=attempt)
                continue
            if "error" in resp:
                err = resp["error"]
                self.tracer.span("tool", tool, sim_ms=latency, status="error", error=err["message"], caller=caller,
                                 args=args, attempt=attempt, attempt_final=True, idem_key=idem_key)
                raise ToolRejected(err.get("data", {}).get("code", str(err["code"])), err["message"])
            result = resp["result"]
            self.tracer.span("tool", tool, sim_ms=latency, caller=caller, args=args, attempt=attempt,
                             attempt_final=True, idem_key=idem_key, replayed=bool(result.get("_replayed")))
            self.budget.check_time(self.tracer.sim_ms)
            return {k: v for k, v in result.items() if k != "_replayed"}
        raise AssertionError("unreachable")


def idempotency_key(run_id: str, step: str, tool: str, args: dict) -> str:
    digest = hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()[:12]
    return f"{run_id}:{step}:{tool}:{digest}"


@dataclass
class CancelToken:
    cancelled: bool = False
    after_step: str | None = None  # test hook: cancel once this step has finished

    def cancel(self) -> None:
        self.cancelled = True


Step = tuple[str, Callable[[dict], None]]


@dataclass
class DurableRunner:
    store: StateStore
    tracer: Tracer
    crash_after: str | None = None   # test hook: die after this step's effects, before its checkpoint
    cancel: CancelToken = field(default_factory=CancelToken)

    def run(self, run_id: str, plan: list[str], steps: dict[str, Callable[[dict], None]], data: dict) -> dict:
        self.store.checkpoint(run_id, plan, 0, data)
        return self._loop(run_id, plan, steps, 0, data)

    def resume(self, run_id: str, steps: dict[str, Callable[[dict], None]]) -> dict:
        saved = self.store.load(run_id)
        if saved is None:
            raise KeyError(run_id)
        self.tracer.span("runtime", "resume", run_id=run_id, from_step=saved["step"])
        if saved["status"] != "running":
            return saved["data"]
        return self._loop(run_id, saved["plan"], steps, saved["step"], saved["data"])

    def _loop(self, run_id: str, plan: list[str], steps, start: int, data: dict) -> dict:
        for i in range(start, len(plan)):
            name = plan[i]
            if self.cancel.cancelled:
                self.tracer.span("runtime", "cancelled", before_step=name)
                self.store.checkpoint(run_id, plan, i, data, status="cancelled")
                raise Cancelled(name)
            if data.get("halt"):
                break
            data["_step"] = name
            steps[name](data)
            if self.crash_after == name:
                self.crash_after = None
                self.tracer.span("runtime", "crash", status="error", after_step=name)
                raise SimulatedCrash(name)
            self.store.checkpoint(run_id, plan, i + 1, data)
            self.tracer.span("state", "checkpoint", step=name, index=i + 1)
            if self.cancel.after_step == name:
                self.cancel.cancel()
        self.store.checkpoint(run_id, plan, len(plan), data, status="done")
        return data
