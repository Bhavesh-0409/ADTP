"""Command line entry point:  python -m adtp.cli <command>

Commands:
    info: show config, controllers, scenarios
    run <scenario> <controller>: run one benchmark
    run-all: run all benchmark scenarios for Reno and ADTP
    side-by-side <scenario>: run Reno and ADTP concurrently
"""

from __future__ import annotations

import argparse
import asyncio

from . import config
from .congestion import CONTROLLERS
from .packet import HEADER_SIZE
from .runner import run_all, run_scenario, run_side_by_side
from .scenarios import SCENARIOS


def cmd_info(_args) -> None:
    print(f"ADTP  (header {HEADER_SIZE} B, MSS {config.MSS} B, recv window {config.RECV_WINDOW} pkts)")
    print("\nControllers:", ", ".join(CONTROLLERS))
    print(f"ADTP classifier: backlog threshold {config.ADTP_BACKLOG_THRESHOLD}, "
          f"random-loss cut x{config.ADTP_RANDOM_CUT}, congestion cut x{config.RENO_CUT}, "
          f"timeout_as_congestion={config.ADTP_TIMEOUT_AS_CONGESTION}")
    print("\nScenarios:")
    for s in SCENARIOS.values():
        tag = " (optional)" if s.optional else ""
        print(f"  {s.key:10s} {s.title}{tag}")


def cmd_run(args) -> None:
    log = asyncio.run(run_scenario(
        args.scenario,
        args.controller,
        seed=args.seed,
        file_bytes=args.size,
        out_dir=args.out_dir,
        timeout=args.timeout,
    ))
    meta = log.meta
    summary = log.summary
    print("\n" + "=" * 55)
    print(f"Result: {meta['scenario']} ({meta['controller']}, seed={meta['seed']})")
    print("=" * 55)
    print(f"  Throughput      : {summary.get('throughput_kbps', 0.0):.2f} kbps")
    print(f"  Completion Time : {summary.get('completion_time_s', 0.0):.2f} s")
    print(f"  Retransmissions : {summary.get('retransmissions', 0)}")
    print(f"  Packets Sent    : {summary.get('packets_sent', 0)}")
    if summary.get("accuracy") is not None:
        print(f"  Accuracy        : {summary['accuracy'] * 100:.1f}%")
    print(f"  Saved JSON      : {args.out_dir}/{meta['scenario']}_{meta['controller']}_{meta['seed']}.json")
    print(f"  Saved CSV       : {args.out_dir}/{meta['scenario']}_{meta['controller']}_{meta['seed']}.csv")
    print("=" * 55)


def cmd_run_all(args) -> None:
    asyncio.run(run_all(
        seed=args.seed,
        file_bytes=args.size,
        out_dir=args.out_dir,
        timeout=args.timeout,
    ))


def cmd_side_by_side(args) -> None:
    reno_log, adtp_log = asyncio.run(run_side_by_side(
        args.scenario,
        seed=args.seed,
        file_bytes=args.size,
        out_dir=args.out_dir,
        timeout=args.timeout,
    ))
    r_sum, a_sum = reno_log.summary, adtp_log.summary
    r_thpt = r_sum.get("throughput_kbps", 0.0) or 1.0
    a_thpt = a_sum.get("throughput_kbps", 0.0)
    ratio = a_thpt / r_thpt
    print("\n" + "=" * 65)
    print(f"Side-by-Side: {args.scenario} (seed={args.seed}, size={args.size:,} B)")
    print("=" * 65)
    print(f"  Reno Throughput : {r_thpt:.2f} kbps ({r_sum.get('completion_time_s', 0.0):.2f} s)")
    print(f"  ADTP Throughput : {a_thpt:.2f} kbps ({a_sum.get('completion_time_s', 0.0):.2f} s)")
    if a_sum.get("accuracy") is not None:
        print(f"  ADTP Accuracy   : {a_sum['accuracy'] * 100:.1f}%")
    print(f"  ADTP / Reno     : {ratio:.2f}x")
    print("=" * 65)


def main() -> None:
    p = argparse.ArgumentParser(prog="adtp")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="show config, controllers, scenarios").set_defaults(fn=cmd_info)

    r = sub.add_parser("run", help="run one scenario with one controller")
    r.add_argument("scenario", choices=list(SCENARIOS))
    r.add_argument("controller", choices=list(CONTROLLERS))
    r.add_argument("--seed", type=int, default=None, help="random seed override")
    r.add_argument("--size", type=int, default=None, help="file size in bytes")
    r.add_argument("--out-dir", type=str, default="results", help="results directory")
    r.add_argument("--timeout", type=float, default=60.0, help="transfer timeout (s)")
    r.set_defaults(fn=cmd_run)

    ra = sub.add_parser("run-all", help="run all must-have scenarios, ADTP vs Reno")
    ra.add_argument("--seed", type=int, default=42, help="random seed (default: 42)")
    ra.add_argument("--size", type=int, default=1_000_000, help="file size in bytes (default: 1000000)")
    ra.add_argument("--out-dir", type=str, default="results", help="results directory")
    ra.add_argument("--timeout", type=float, default=60.0, help="transfer timeout (s)")
    ra.set_defaults(fn=cmd_run_all)

    sbs = sub.add_parser("side-by-side", help="run ADTP and Reno concurrently")
    sbs.add_argument("scenario", choices=list(SCENARIOS))
    sbs.add_argument("--seed", type=int, default=42, help="random seed (default: 42)")
    sbs.add_argument("--size", type=int, default=1_000_000, help="file size in bytes (default: 1000000)")
    sbs.add_argument("--out-dir", type=str, default="results", help="results directory")
    sbs.add_argument("--timeout", type=float, default=60.0, help="transfer timeout (s)")
    sbs.set_defaults(fn=cmd_side_by_side)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
