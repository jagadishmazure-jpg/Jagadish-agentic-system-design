"""The assembled system: guard -> understand -> route -> durable run of agent steps -> one message."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field

from . import world as W
from .actions import ActionExecutor
from .agents import AGENTS, ALLOWLIST, set_status
from .context import ContextBuilder
from .guards import check_input
from .knowledge import FAQ_PATH
from .llm import PARSE_SCHEMA, count_tokens, make_llm, structured
from .observability import Tracer
from .orchestrator import route
from .policy import PolicyEngine
from .requirements import SPEC
from .runtime import (
    Budget,
    Cancelled,
    CancelToken,
    DurableRunner,
    ToolClient,
    ToolFailed,
    ToolRejected,
)
from .runtime import BudgetExceeded as _Budget
from .state import FlightCache, StateStore
from .tools import ToolServer

ASSUMED_USD_PER_1K_TOKENS = 0.002  # illustrative assumption for the simulated cost metric, not a quoted price


@dataclass(frozen=True)
class Config:
    name: str = "v3"
    freshness_check: bool = True
    boarding_guard: bool = True
    idempotency: bool = True
    max_age: int = int(SPEC.constraint("C4"))


BASELINE = Config(name="v0", freshness_check=False, boarding_guard=False, idempotency=False)


@dataclass
class Response:
    run_id: str
    status: str
    intents: list[str]
    messages: list[str]
    destination: str | None
    route: list[str]
    eta: int | None
    data: dict
    trace: Tracer
    tokens: int
    repairs: int

    @property
    def sim_cost_usd(self) -> float:
        return self.tokens / 1000 * ASSUMED_USD_PER_1K_TOKENS


@dataclass
class RequestRuntime:
    world: W.World
    config: object
    tracer: Tracer
    client: ToolClient
    builder: ContextBuilder
    executor: ActionExecutor
    llm: object
    store: StateStore
    run_id: str
    approver: object
    budget: Budget
    spec: object = SPEC
    repairs: int = 0

    @property
    def now(self) -> int:
        return self.world.now

    def charge_llm(self, stats: dict, task: str) -> None:
        self.repairs += stats["repairs"]
        self.tracer.span("llm", task, sim_ms=250 + 2 * stats["tokens"], tokens=stats["tokens"],
                         repairs=stats["repairs"], escalated=stats["escalated"])
        self.budget.charge_tokens(stats["tokens"])


@dataclass
class System:
    world: W.World
    config: Config = field(default_factory=Config)
    store: StateStore = field(default_factory=StateStore)
    cache: FlightCache = field(default_factory=FlightCache)
    approver: object = None
    llm: object = None
    policy_key: bytes = field(default_factory=lambda: secrets.token_bytes(32))

    def __post_init__(self) -> None:
        self.llm = self.llm or make_llm(self.world.faults)
        self._policy = PolicyEngine(facts=self._facts, key=self.policy_key)
        self.server = ToolServer(self.world, ALLOWLIST, verify_token=lambda t, c: self._policy.verify(t, c),
                                 honour_idempotency=True)
        self._requests: dict[str, dict] = {}
        self._traces: dict[str, Tracer] = {}

    # facts the policy reads from systems of record (never from the agent)
    def _facts(self, question: str, args: dict) -> dict:
        p = self.world.passengers[args["passenger_id"]]
        old, new = self.world.flights[p["flight"]], self.world.flights[args["flight_id"]]
        return {"fare_diff": max(0, new["fare"] - old["fare"]), "seats_free": new["seats_free"],
                "cabin_change": False, "seat_held": False}

    def _runtime(self, run_id: str, tracer: Tracer, untrusted: bool) -> RequestRuntime:
        budget = Budget(int(SPEC.constraint("C1")), int(SPEC.constraint("C2")), int(SPEC.constraint("C3")))
        policy = PolicyEngine(facts=self._facts, key=self.policy_key, untrusted_input=untrusted)
        self._policy = policy
        client = ToolClient(self.server, tracer, budget)
        raw = count_tokens(json.dumps([self.world.flights, self.world.passengers, self.world.bags,
                                       self.world.orders])) + count_tokens(FAQ_PATH.read_text())
        builder = ContextBuilder(client, self.cache, self.store, tracer, self.world.now,
                                 freshness_check=self.config.freshness_check, max_age=self.config.max_age,
                                 raw_tokens=raw)
        executor = ActionExecutor(client, policy, tracer, use_idempotency=self.config.idempotency)
        return RequestRuntime(self.world, self.config, tracer, client, builder, executor, self.llm, self.store,
                              run_id, self.approver, budget)

    def _steps(self, rt: RequestRuntime) -> dict:
        def bind(name):
            agent, method = name.split(".")
            return lambda data: getattr(AGENTS[agent], method)(rt, data)
        from .orchestrator import FINAL_STEP, WORKFLOWS
        names = {s for wf in WORKFLOWS.values() for s in wf} | {FINAL_STEP}
        return {n: bind(n) for n in names}

    def handle(self, request: dict, *, run_id: str | None = None, crash_after: str | None = None,
               cancel_after: str | None = None) -> Response:
        run_id = run_id or f"run-{secrets.token_hex(4)}"
        names = tuple(p["name"] for p in self.world.passengers.values())
        tracer = Tracer(run_id, mask_terms=names)
        self._traces[run_id] = tracer
        tracer.span("input", "request", passenger=request["passenger_id"], text=request["text"])
        guard = check_input(request["text"])
        tracer.span("guard", "input_guard", untrusted=guard["untrusted_instruction"], match=guard["match"])
        self._requests[run_id] = {"untrusted": guard["untrusted_instruction"]}
        rt = self._runtime(run_id, tracer, guard["untrusted_instruction"])
        parsed, stats = structured(self.llm, "parse_request", {"text": request["text"]}, PARSE_SCHEMA)
        rt.charge_llm(stats, "parse_request")
        data = {"passenger_id": request["passenger_id"], "text": request["text"], "messages": [], "actions": [],
                "status": "done", "untrusted": guard["untrusted_instruction"]}
        if parsed is None:
            data["messages"].append("Sorry, I could not understand that. A member of staff will contact you.")
            data["status"] = "escalated"
            return self._respond(rt, data, [])
        data.update(intents=parsed["intents"], flight_id=parsed["flight_id"], bag_id=parsed["bag_id"],
                    order_id=parsed["order_id"])
        plan = route(parsed["intents"])
        tracer.span("route", "plan", intents=parsed["intents"], steps=plan)
        runner = DurableRunner(self.store, tracer, crash_after=crash_after, cancel=CancelToken(after_step=cancel_after))
        return self._execute(rt, runner, data, plan=plan)

    def resume(self, run_id: str) -> Response:
        """Simulate a new process picking the run up from its last checkpoint."""
        tracer = self._traces[run_id]
        rt = self._runtime(run_id, tracer, self._requests[run_id]["untrusted"])
        runner = DurableRunner(self.store, tracer)
        return self._execute(rt, runner, None, plan=None)

    def _execute(self, rt: RequestRuntime, runner: DurableRunner, data: dict | None, plan) -> Response:
        steps = self._steps(rt)
        try:
            if plan is not None:
                data = runner.run(rt.run_id, plan, steps, data)
            else:
                data = runner.resume(rt.run_id, steps)
        except Cancelled:
            data = self.store.load(rt.run_id)["data"]
            data["status"] = "cancelled"
            data.setdefault("messages", []).append("Request cancelled; nothing else will be changed.")
        except (_Budget, ToolFailed, ToolRejected) as e:
            data = self.store.load(rt.run_id)["data"]
            set_status(data, "escalated")
            reason = "budget" if isinstance(e, _Budget) else "tool"
            rt.tracer.span("runtime", "budget_exceeded" if reason == "budget" else "tool_failed", status="error",
                           error=str(e))
            data.setdefault("messages", []).append("I could not finish this safely; a member of staff will help you.")
        return self._respond(rt, data, data.get("intents", []))

    def _respond(self, rt: RequestRuntime, data: dict, intents: list[str]) -> Response:
        rt.tracer.span("output", "response", outcome=data["status"], destination=data.get("destination"))
        tokens = sum(s.attrs.get("tokens", 0) for s in rt.tracer.of_kind("llm"))
        repairs = sum(s.attrs.get("repairs", 0) for s in rt.tracer.of_kind("llm"))
        return Response(rt.run_id, data["status"], intents, data.get("messages", []), data.get("destination"),
                        data.get("route", []), data.get("eta"), data, rt.tracer, tokens, repairs)
