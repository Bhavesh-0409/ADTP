"""Run the Reno or ADTP emulator checkpoints and parameter sweeps without the runner or API.

Examples:
    python scripts/checkpoint.py --controller reno
    python scripts/checkpoint.py --controller adtp --threshold 2.0
    python scripts/checkpoint.py --controller adtp --scenarios congested --debug-losses
    python scripts/checkpoint.py --sweep --seeds 1,2,3 --timeout 120
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import random
import socket
import sys
import tempfile
from pathlib import Path

# Running ``python scripts/checkpoint.py`` makes ``scripts/`` the import root.
# Add the repository root so the local ``adtp`` package is found without install.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from adtp import config
from adtp.congestion import make_controller
from adtp.emulator import Emulator
from adtp.metrics import RunLog, classification_accuracy
from adtp.receiver import Receiver
from adtp.scenarios import SCENARIOS
from adtp.sender import Sender


class CheckpointTimeout(RuntimeError):
    """A checkpoint-specific timeout, distinct from asyncio.wait_for's timeout."""


def _free_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


async def _show_progress(scenario: str, sender: Sender, size: int,
                         transfer_task: asyncio.Task, started: float) -> None:
    """Print enough live state to distinguish a slow link from a stuck transfer."""
    while not transfer_task.done():
        await asyncio.sleep(1)
        acked = min(size, max(0, sender.base - 1) * 1000)
        elapsed = asyncio.get_running_loop().time() - started
        print(f"{scenario}: elapsed={elapsed:.1f}s acked={acked}/{size} B "
              f"cwnd={sender.controller.cwnd:.2f}", flush=True)


def _instantiate_controller(name: str, threshold: float, timeout_as_congestion: bool):
    if name == "adtp":
        return make_controller("adtp", threshold=threshold, timeout_as_congestion=timeout_as_congestion)
    return make_controller(name)


async def _run_one(key: str, controller_name: str, size: int, timeout: float,
                   seed: int | None = None, threshold: float = config.ADTP_BACKLOG_THRESHOLD,
                   timeout_as_congestion: bool = False, debug_losses: bool = False) -> dict:
    scenario = SCENARIOS[key]
    effective_seed = scenario.seed if seed is None else seed
    ctrl_label = controller_name.upper()
    if controller_name == "adtp":
        ctrl_label += f"(th={threshold:g},to_cong={timeout_as_congestion})"
    print(f"Setting up {key} ({ctrl_label}): {size} B "
          f"(seed={effective_seed}, global timeout: {timeout:g} s)", flush=True)
    payload = random.Random(effective_seed).randbytes(size)
    with tempfile.TemporaryDirectory(prefix="adtp-checkpoint-") as directory:
        source = Path(directory) / "input.bin"
        output = Path(directory) / "output.bin"
        source.write_bytes(payload)

        receiver_port, emulator_port = _free_udp_port(), _free_udp_port()
        receiver_task = asyncio.create_task(
            Receiver(("127.0.0.1", receiver_port), str(output), RunLog(),
                     transfer_timeout=timeout).receive_file()
        )
        await asyncio.sleep(0)  # ensure the receiver has bound before the sender starts
        log = RunLog(meta={"scenario": key, "controller": controller_name, "seed": effective_seed,
                           "threshold": threshold, "timeout_as_congestion": timeout_as_congestion})
        emulator = Emulator(
            ("127.0.0.1", emulator_port),
            ("127.0.0.1", receiver_port),
            copy.deepcopy(scenario.initial),
            log,
            seed=effective_seed,
        )
        await emulator.start()
        try:
            ctrl = _instantiate_controller(controller_name, threshold, timeout_as_congestion)
            sender = Sender(ctrl, ("127.0.0.1", emulator_port), log, transfer_timeout=timeout)
            print(f"Starting {key}: sender ({controller_name}) -> emulator -> receiver", flush=True)
            started = asyncio.get_running_loop().time()
            transfer_task = asyncio.create_task(sender.send_file(str(source)))
            progress_task = asyncio.create_task(_show_progress(key, sender, size, transfer_task, started))
            try:
                summary = await asyncio.wait_for(transfer_task, timeout=timeout)
            except asyncio.TimeoutError as error:
                transfer_task.cancel()
                forwards = log.of_kind("forward")
                queued = log.of_kind("queue")
                last_forward = forwards[-1] if forwards else None
                raise CheckpointTimeout(
                    f"{key} transfer exceeded {timeout:g} s; "
                    f"acked={min(size, max(0, sender.base - 1) * 1000)}/{size} B, "
                    f"cwnd={sender.controller.cwnd:.2f}, queue_events={len(queued)}, "
                    f"forward_events={len(forwards)}, last_forward={last_forward}"
                ) from error
            finally:
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass
            received = await receiver_task
            expected_hash = hashlib.sha256(payload).hexdigest()
            sha256_ok = (received["sha256"] == expected_hash and output.read_bytes() == payload)
            if not sha256_ok:
                raise RuntimeError(f"{key}: SHA-256 verification failed")

            drops = log.of_kind("drop")
            loss_events = log.of_kind("loss")

            if debug_losses:
                print(f"\n--- Loss Events Debug ({key}, controller={controller_name}, seed={effective_seed}) ---")
                print(f"{'#':<3} {'t(s)':<8} {'seq':<6} {'trigger':<9} {'cwnd':<7} {'rtt(ms)':<9} {'base(ms)':<9} {'backlog':<8} {'class':<12} {'ground_truth':<16}")
                for idx, loss in enumerate(loss_events, start=1):
                    t_val = loss.get("t", 0.0)
                    seq_val = loss.get("seq", 0)
                    trigger_val = loss.get("trigger", "")
                    cwnd_val = loss.get("cwnd_before", 0.0)
                    rtt_val = loss.get("rtt")
                    rtt_str = f"{rtt_val * 1000:.1f}" if rtt_val is not None else "None"
                    base_val = loss.get("base_rtt")
                    base_str = f"{base_val * 1000:.1f}" if base_val is not None else "None"
                    b_val = loss.get("backlog")
                    b_str = f"{b_val:.2f}" if b_val is not None else "None"
                    cls_val = loss.get("classification", "")
                    candidates = [d for d in drops if d["seq"] == seq_val and d["t"] <= t_val + 1e-6]
                    gt_val = candidates[-1]["label"] if candidates else "none (spurious)"
                    print(f"{idx:<3} {t_val:<8.3f} {seq_val:<6} {trigger_val:<9} {cwnd_val:<7.2f} {rtt_str:<9} {base_str:<9} {b_str:<8} {cls_val:<12} {gt_val:<16}")
                print("-" * 90 + "\n")

            classified_random = sum(e.get("classification") == "random" for e in loss_events)
            classified_congestion = sum(e.get("classification") == "congestion" for e in loss_events)
            accuracy_info = classification_accuracy(loss_events, drops) if controller_name == "adtp" else None
            return {
                "scenario": key,
                "seed": effective_seed,
                "controller": controller_name,
                "throughput_kbps": summary["throughput_kbps"],
                "completion_time_s": summary["completion_time_s"],
                "retransmissions": summary["retransmissions"],
                "random": sum(drop["label"] == "random" for drop in drops),
                "queue_overflow": sum(drop["label"] == "queue_overflow" for drop in drops),
                "classified_random": classified_random,
                "classified_congestion": classified_congestion,
                "accuracy": accuracy_info["accuracy"] if accuracy_info else None,
                "accuracy_info": accuracy_info,
                "sha256_ok": sha256_ok,
            }
        finally:
            await emulator.stop()
            if not receiver_task.done():
                receiver_task.cancel()
                try:
                    await receiver_task
                except asyncio.CancelledError:
                    pass


async def _run_sweep(scenarios: list[str], size: int, timeout: float, seeds: list[int | None]) -> None:
    # Target scenarios for sweep are lossy and congested
    target_scenarios = [s for s in scenarios if s in ("lossy", "congested")]
    if not target_scenarios:
        target_scenarios = ["lossy", "congested"]

    print("==========================================================================================")
    print(f"STARTING PARAMETER SWEEP: Scenarios={target_scenarios}, Seeds={seeds}, Size={size} B")
    print("==========================================================================================")

    configs: list[tuple[str, str, float, bool]] = [
        ("Reno (baseline)", "reno", 3.0, False),
    ]
    for th in (1.0, 2.0, 3.0, 5.0):
        configs.append((f"ADTP (th={th:g}, to_cong=F)", "adtp", th, False))
        configs.append((f"ADTP (th={th:g}, to_cong=T)", "adtp", th, True))

    sweep_results: list[dict] = []
    reno_baseline_thpt: dict[str, float] = {}

    for label, ctrl_name, th, to_cong in configs:
        print(f"\n>>> Running Config: {label}")
        config_metrics: dict[str, dict[str, float]] = {}
        for sc in target_scenarios:
            thpts: list[float] = []
            accs: list[float] = []
            for s in seeds:
                res = await _run_one(sc, ctrl_name, size, timeout, seed=s, threshold=th,
                                     timeout_as_congestion=to_cong, debug_losses=False)
                thpts.append(res["throughput_kbps"])
                if res["accuracy"] is not None:
                    accs.append(res["accuracy"])
            mean_thpt = sum(thpts) / len(thpts) if thpts else 0.0
            mean_acc = (sum(accs) / len(accs)) if accs else None
            config_metrics[sc] = {"throughput": mean_thpt, "accuracy": mean_acc}
            if ctrl_name == "reno":
                reno_baseline_thpt[sc] = mean_thpt

        sweep_results.append({
            "label": label,
            "metrics": config_metrics,
        })

    # Build the comparison table
    lines = []
    lines.append("=" * 115)
    lines.append(f"SWEEP RESULTS (size={size} B, seeds={seeds})")
    lines.append("=" * 115)
    header = f"{'Configuration':<28} {'Lossy Thpt':>12} {'Cong Thpt':>12} {'Lossy Acc':>11} {'Cong Acc':>10} {'Lossy/Reno':>12} {'Cong/Reno':>11}"
    lines.append(header)
    lines.append("-" * 115)

    reno_lossy = reno_baseline_thpt.get("lossy", 1.0) or 1.0
    reno_cong = reno_baseline_thpt.get("congested", 1.0) or 1.0

    for item in sweep_results:
        lbl = item["label"]
        m = item["metrics"]
        lossy_m = m.get("lossy", {})
        cong_m = m.get("congested", {})

        lossy_thpt = lossy_m.get("throughput", 0.0)
        cong_thpt = cong_m.get("throughput", 0.0)

        lossy_acc = lossy_m.get("accuracy")
        cong_acc = cong_m.get("accuracy")

        lossy_acc_str = f"{lossy_acc * 100:.1f}%" if lossy_acc is not None else "N/A"
        cong_acc_str = f"{cong_acc * 100:.1f}%" if cong_acc is not None else "N/A"

        lossy_ratio = lossy_thpt / reno_lossy if reno_lossy > 0 else 0.0
        cong_ratio = cong_thpt / reno_cong if reno_cong > 0 else 0.0

        line = (f"{lbl:<28} {lossy_thpt:>10.2f} k  {cong_thpt:>10.2f} k  "
                f"{lossy_acc_str:>11} {cong_acc_str:>10} "
                f"{lossy_ratio:>11.2f}x {cong_ratio:>10.2f}x")
        lines.append(line)

    lines.append("=" * 115)
    table_text = "\n".join(lines)
    print("\n" + table_text)

    # Save to results/sweep.txt
    results_dir = REPOSITORY_ROOT / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_file = results_dir / "sweep.txt"
    out_file.write_text(table_text)
    print(f"\n[Saved sweep summary table to {out_file}]")


async def _main(controller: str, size: int, timeout: float, seeds: list[int | None],
                scenarios: list[str], threshold: float, timeout_as_congestion: bool,
                debug_losses: bool, sweep: bool) -> None:
    if sweep:
        await _run_sweep(scenarios, size, timeout, seeds)
        return

    all_rows: list[dict] = []
    for sc in scenarios:
        for s in seeds:
            try:
                row = await asyncio.wait_for(
                    _run_one(sc, controller, size, timeout, seed=s, threshold=threshold,
                             timeout_as_congestion=timeout_as_congestion, debug_losses=debug_losses),
                    timeout=timeout
                )
                all_rows.append(row)
            except asyncio.TimeoutError as error:
                raise CheckpointTimeout(f"{sc} (seed={s}) setup exceeded {timeout:g} s") from error

    # Print summary table
    if controller == "adtp":
        print("\nscenario    seed   throughput_kbps  completion_s  retransmissions  random  queue_overflow  class_rand  class_cong  acc(%)  sha256_ok")
        for row in all_rows:
            seed_str = str(row['seed']) if row['seed'] is not None else "def"
            acc_str = f"{row['accuracy'] * 100:.1f}" if row['accuracy'] is not None else "N/A"
            print(f"{row['scenario']:10} {seed_str:5} {row['throughput_kbps']:16.2f} "
                  f"{row['completion_time_s']:13.4f} {row['retransmissions']:16} "
                  f"{row['random']:7} {row['queue_overflow']:15}  "
                  f"{row['classified_random']:10}  {row['classified_congestion']:10}  "
                  f"{acc_str:>6}  {str(row['sha256_ok']):>9}")
    else:
        print("\nscenario    seed   throughput_kbps  completion_s  retransmissions  random  queue_overflow  sha256_ok")
        for row in all_rows:
            seed_str = str(row['seed']) if row['seed'] is not None else "def"
            print(f"{row['scenario']:10} {seed_str:5} {row['throughput_kbps']:16.2f} "
                  f"{row['completion_time_s']:13.4f} {row['retransmissions']:16} "
                  f"{row['random']:7} {row['queue_overflow']:15}  "
                  f"{str(row['sha256_ok']):>9}")

    # If multiple seeds: print per-scenario mean, min/max, mean accuracy
    if len(seeds) > 1:
        print("\n" + "=" * 70)
        print(f"MULTI-SEED SUMMARY ({len(seeds)} seeds: {seeds})")
        print("=" * 70)
        for sc in scenarios:
            sc_rows = [r for r in all_rows if r["scenario"] == sc]
            if not sc_rows:
                continue
            thpts = [r["throughput_kbps"] for r in sc_rows]
            mean_thpt = sum(thpts) / len(thpts)
            min_thpt = min(thpts)
            max_thpt = max(thpts)
            accs = [r["accuracy"] for r in sc_rows if r["accuracy"] is not None]
            mean_acc_str = f"{sum(accs) / len(accs) * 100:.2f}%" if accs else "N/A"
            print(f"\nScenario: {sc}")
            print(f"  Throughput (kbps): mean={mean_thpt:.2f} (min={min_thpt:.2f}, max={max_thpt:.2f})")
            if controller == "adtp":
                print(f"  Accuracy         : mean={mean_acc_str}")
        print("=" * 70)

    # Print confusion matrix if single-seed ADTP
    elif controller == "adtp":
        print("\n" + "=" * 68)
        print("ADTP LOSS CLASSIFICATION ACCURACY & CONFUSION MATRICES")
        print("=" * 68)
        for row in all_rows:
            acc = row.get("accuracy_info")
            if not acc:
                continue
            scen = row["scenario"]
            acc_str = f"{acc['accuracy'] * 100:.2f}%" if acc["accuracy"] is not None else "N/A (no matched loss events)"
            print(f"\nScenario: {scen}")
            print(f"  Classified count : random={row['classified_random']}, congestion={row['classified_congestion']}")
            print(f"  Accuracy (ground-truth match): {acc_str} ({acc['matched']} matched, {acc['unmatched']} unmatched)")
            cm = acc["confusion"]
            print("  Confusion Matrix (Rows: ADTP classified, Columns: Emulator ground truth):")
            print(f"    {'':25} {'GT: random':15} {'GT: queue_overflow':18}")
            print(f"    {'Classified Random':25} {cm['random']['random']:<15} {cm['random']['queue_overflow']:<18}")
            print(f"    {'Classified Congestion':25} {cm['congestion']['random']:<15} {cm['congestion']['queue_overflow']:<18}")
        print("=" * 68)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Reno or ADTP through the emulator checkpoints.")
    parser.add_argument("--controller", choices=["reno", "adtp"], default="reno",
                        help="congestion controller to run (default: reno)")
    parser.add_argument("--size", type=int, default=2_000_000,
                        help="transfer size in bytes for each scenario (default: 2000000)")
    parser.add_argument("--timeout", type=float, default=60.0,
                        help="global timeout in seconds per scenario (default: 60)")
    parser.add_argument("--seed", type=int, default=None,
                        help="single random seed override")
    parser.add_argument("--seeds", type=str, default=None,
                        help="comma-separated list of random seeds, e.g. '1,2,3'")
    parser.add_argument("--scenarios", type=str, default=None,
                        help="comma-separated list of scenarios, e.g. 'lossy,congested' (default: all)")
    parser.add_argument("--threshold", type=float, default=config.ADTP_BACKLOG_THRESHOLD,
                        help=f"ADTP backlog threshold (default: {config.ADTP_BACKLOG_THRESHOLD})")
    parser.add_argument("--timeout-as-congestion", action="store_true", default=False,
                        help="classify timeout-triggered losses as congestion (default: false)")
    parser.add_argument("--debug-losses", action="store_true", default=False,
                        help="print detailed metrics per loss event")
    parser.add_argument("--sweep", action="store_true", default=False,
                        help="run parameter sweep comparing Reno vs ADTP variants across seeds")
    args = parser.parse_args()

    if args.size < 0:
        parser.error("--size must be non-negative")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    # Parse seeds
    if args.seeds:
        seed_list = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]
    elif args.seed is not None:
        seed_list = [args.seed]
    else:
        seed_list = [None]

    # Parse scenarios
    if args.scenarios:
        scenario_list = [s.strip() for s in args.scenarios.split(",") if s.strip()]
        for s in scenario_list:
            if s not in SCENARIOS:
                parser.error(f"unknown scenario '{s}', available: {list(SCENARIOS)}")
    else:
        scenario_list = ["clean", "lossy", "congested"] if not args.sweep else ["lossy", "congested"]

    asyncio.run(_main(
        controller=args.controller,
        size=args.size,
        timeout=args.timeout,
        seeds=seed_list,
        scenarios=scenario_list,
        threshold=args.threshold,
        timeout_as_congestion=args.timeout_as_congestion,
        debug_losses=args.debug_losses,
        sweep=args.sweep,
    ))


if __name__ == "__main__":
    main()
