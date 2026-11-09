"""python -m harrowgate ask P-1001 "My gate changed, what now?"  |  python -m harrowgate serve"""

from __future__ import annotations

import argparse

from . import world as W
from .system import BASELINE, Config, System


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="harrowgate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ask = sub.add_parser("ask", help="send one request to the assistant (simulated world)")
    ask.add_argument("passenger_id")
    ask.add_argument("text")
    ask.add_argument("--baseline", action="store_true", help="use the v0 configuration")
    ask.add_argument("--trace", action="store_true", help="print the trace")
    srv = sub.add_parser("serve", help="run the HTTP front door")
    srv.add_argument("--port", type=int, default=8080)
    args = ap.parse_args(argv)
    if args.cmd == "serve":  # pragma: no cover
        from .api import serve
        serve(args.port)
        return 0
    system = System(W.default_world(), BASELINE if args.baseline else Config())
    resp = system.handle({"passenger_id": args.passenger_id, "text": args.text}, run_id="cli")
    print(f"status: {resp.status}")
    for m in resp.messages:
        print(f"- {m}")
    if args.trace:
        print(resp.trace.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
