"""Scenario runner for ADTP and Reno benchmarks.

    run_scenario: runs a single scenario with a chosen controller and saves JSON + CSV.
    run_all: runs clean, lossy, congested, dynamic for reno and adtp, printing a comparison table.
    run_side_by_side: runs ADTP and Reno concurrently on the same scenario/seed.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import random
import socket
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional

from .congestion import make_controller
from .emulator import Emulator
from .metrics import RunLog, classification_accuracy, summarize
from .receiver import Receiver
from .scenarios import SCENARIOS, Scenario
from .sender import Sender


def _free_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


async def _apply_condition_changes(changes: list[tuple[float, dict]],
                                   emulator: Emulator,
                                   log: RunLog,
                                   effective_bytes: int,
                                   scenario_file_bytes: int,
                                   cancel_event: asyncio.Event) -> None:
    """Schedule dynamic condition changes mid-transfer."""
    scale = (effective_bytes / scenario_file_bytes) if scenario_file_bytes > 0 else 1.0
    for delay_s, change_dict in changes:
        effective_delay = delay_s * scale
        # If transfer is short (e.g. 1 MB clean takes ~1.0s), ensure mid-transfer trigger
        if effective_bytes <= 1_000_000 and delay_s >= 2.0:
            effective_delay = 0.5

        try:
            await asyncio.wait_for(cancel_event.wait(), timeout=max(0.01, effective_delay))
            # If cancel_event fired, transfer finished early
            return
        except asyncio.TimeoutError:
            # Deadline reached, apply condition change
            emulator.set_conditions(**change_dict)
            log.add("condition_change", **change_dict)


async def run_scenario(scenario_key: str,
                       controller: str,
                       *,
                       seed: Optional[int] = None,
                       file_bytes: Optional[int] = None,
                       out_dir: str | Path = "results",
                       overrides: Optional[dict[str, Any]] = None,
                       log_listener: Optional[Callable[[dict], None]] = None,
                       timeout: float = 60.0) -> RunLog:
    """Run one scenario end-to-end, verify SHA-256, and save JSON + CSV."""
    if scenario_key not in SCENARIOS:
        raise ValueError(f"Unknown scenario '{scenario_key}'. Choose from: {list(SCENARIOS)}")

    scenario = SCENARIOS[scenario_key]
    effective_seed = scenario.seed if seed is None else seed
    effective_bytes = scenario.file_bytes if file_bytes is None else file_bytes

    # Generate payload in memory and save to data/
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    input_file = data_dir / f"{scenario_key}_{effective_seed}.bin"
    payload = random.Random(effective_seed).randbytes(effective_bytes)
    input_file.write_bytes(payload)

    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="adtp-run-") as tmpdir:
        output_file = Path(tmpdir) / "output.bin"

        receiver_port = _free_udp_port()
        emulator_port = _free_udp_port()

        log = RunLog(meta={
            "scenario": scenario_key,
            "controller": controller,
            "seed": effective_seed,
            "file_bytes": effective_bytes,
        })
        if log_listener is not None:
            log.listeners.append(log_listener)

        cond = copy.deepcopy(scenario.initial)
        if overrides:
            for k, v in overrides.items():
                if hasattr(cond, k):
                    setattr(cond, k, v)

        emulator = Emulator(
            ("127.0.0.1", emulator_port),
            ("127.0.0.1", receiver_port),
            cond,
            log,
            seed=effective_seed,
        )
        await emulator.start()

        receiver = Receiver(
            ("127.0.0.1", receiver_port),
            str(output_file),
            log,
            transfer_timeout=timeout,
        )
        receiver_task = asyncio.create_task(receiver.receive_file())
        await asyncio.sleep(0)  # let receiver bind

        cancel_changes = asyncio.Event()
        changes_task = None
        if scenario.changes:
            changes_task = asyncio.create_task(
                _apply_condition_changes(
                    scenario.changes,
                    emulator,
                    log,
                    effective_bytes,
                    scenario.file_bytes,
                    cancel_changes,
                )
            )

        try:
            ctrl = make_controller(controller)
            sender = Sender(ctrl, ("127.0.0.1", emulator_port), log, transfer_timeout=timeout)
            started = time.monotonic()
            summary = await asyncio.wait_for(sender.send_file(str(input_file)), timeout=timeout)
            cancel_changes.set()
            if changes_task is not None:
                changes_task.cancel()
                try:
                    await changes_task
                except asyncio.CancelledError:
                    pass

            received = await receiver_task
            expected_hash = hashlib.sha256(payload).hexdigest()
            if received["sha256"] != expected_hash or output_file.read_bytes() != payload:
                raise RuntimeError(f"{scenario_key} ({controller}): SHA-256 verification failed")

            # Add accuracy and confusion matrix to summary if applicable
            drops = log.of_kind("drop")
            losses = log.of_kind("loss")
            acc_info = classification_accuracy(losses, drops)
            summary["accuracy"] = acc_info["accuracy"]
            summary["confusion"] = acc_info["confusion"]
            log.summary.update(summary)

            # Save JSON and CSV
            json_path = out_dir_path / f"{scenario_key}_{controller}_{effective_seed}.json"
            csv_path = out_dir_path / f"{scenario_key}_{controller}_{effective_seed}.csv"
            log.save_json(json_path)
            log.save_csv(csv_path)

            return log
        finally:
            cancel_changes.set()
            if changes_task is not None and not changes_task.done():
                changes_task.cancel()
            await emulator.stop()
            if not receiver_task.done():
                receiver_task.cancel()
                try:
                    await receiver_task
                except asyncio.CancelledError:
                    pass


async def run_all(controllers: tuple[str, ...] = ("reno", "adtp"),
                  scenarios: tuple[str, ...] = ("clean", "lossy", "congested", "dynamic"),
                  seed: int = 42,
                  file_bytes: int = 1_000_000,
                  out_dir: str | Path = "results",
                  timeout: float = 60.0) -> list[RunLog]:
    """Run all specified scenarios for Reno and ADTP, print a comparison table, and save results."""
    logs: list[RunLog] = []
    results_by_scenario: dict[str, dict[str, dict]] = {s: {} for s in scenarios}

    for sc in scenarios:
        for ctrl in controllers:
            print(f"Running {sc:<10} with {ctrl:<5} (seed={seed}, size={file_bytes} B)...", flush=True)
            log = await run_scenario(
                sc, ctrl, seed=seed, file_bytes=file_bytes, out_dir=out_dir, timeout=timeout
            )
            logs.append(log)
            results_by_scenario[sc][ctrl] = log.summary

    # Print comparative table
    lines = []
    lines.append("=" * 105)
    lines.append(f"ADTP vs Reno Comparison (seed={seed}, size={file_bytes:,} B)")
    lines.append("=" * 105)
    header = f"{'Scenario':<12} {'Controller':<10} {'Thpt (kbps)':>12} {'Time (s)':>10} {'Retrans':>9} {'Losses':>8} {'Accuracy':>10} {'Ratio':>10}"
    lines.append(header)
    lines.append("-" * 105)

    for sc in scenarios:
        reno_res = results_by_scenario[sc].get("reno", {})
        reno_thpt = reno_res.get("throughput_kbps", 0.0) or 1.0

        for ctrl in controllers:
            res = results_by_scenario[sc].get(ctrl, {})
            thpt = res.get("throughput_kbps", 0.0)
            comp_time = res.get("completion_time_s", 0.0)
            retrans = res.get("retransmissions", 0)
            matching_log = next(l for l in logs if l.meta["scenario"] == sc and l.meta["controller"] == ctrl)
            n_losses = len(matching_log.of_kind("loss"))
            acc = res.get("accuracy")
            acc_str = f"{acc * 100:.1f}%" if acc is not None else "N/A"
            ratio = (thpt / reno_thpt) if reno_thpt > 0 else 0.0
            ratio_str = f"{ratio:.2f}x"

            line = f"{sc:<12} {ctrl:<10} {thpt:>12.2f} {comp_time:>10.2f} {retrans:>9} {n_losses:>8} {acc_str:>10} {ratio_str:>10}"
            lines.append(line)
        lines.append("-" * 105)

    lines.append("=" * 105)
    table_text = "\n".join(lines)
    print("\n" + table_text + "\n")
    return logs


async def run_side_by_side(scenario_key: str,
                           seed: int = 42,
                           file_bytes: int = 1_000_000,
                           out_dir: str | Path = "results",
                           log_listener: Optional[Callable[[dict], None]] = None,
                           timeout: float = 60.0) -> tuple[RunLog, RunLog]:
    """Run ADTP and Reno concurrently on the same scenario and seed, saving both results."""
    print(f"Running side-by-side: {scenario_key} (ADTP and Reno concurrently, seed={seed})...", flush=True)
    reno_task = asyncio.create_task(
        run_scenario(scenario_key, "reno", seed=seed, file_bytes=file_bytes,
                     out_dir=out_dir, log_listener=log_listener, timeout=timeout)
    )
    adtp_task = asyncio.create_task(
        run_scenario(scenario_key, "adtp", seed=seed, file_bytes=file_bytes,
                     out_dir=out_dir, log_listener=log_listener, timeout=timeout)
    )
    reno_log, adtp_log = await asyncio.gather(reno_task, adtp_task)
    return reno_log, adtp_log
