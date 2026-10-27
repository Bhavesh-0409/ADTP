"""Tests for the scenario runner and CLI runner."""

import pytest

from adtp.metrics import RunLog
from adtp.runner import run_scenario, run_side_by_side


@pytest.mark.asyncio
async def test_runner_executes_scenario_and_saves_results(tmp_path):
    log = await run_scenario(
        "clean",
        "reno",
        seed=123,
        file_bytes=20_000,
        out_dir=tmp_path / "results",
        timeout=10.0,
    )
    assert isinstance(log, RunLog)
    assert log.summary["throughput_kbps"] > 0
    assert (tmp_path / "results" / "clean_reno_123.json").exists()
    assert (tmp_path / "results" / "clean_reno_123.csv").exists()


@pytest.mark.asyncio
async def test_runner_side_by_side_executes_concurrently(tmp_path):
    reno_log, adtp_log = await run_side_by_side(
        "clean",
        seed=42,
        file_bytes=10_000,
        out_dir=tmp_path / "results",
        timeout=10.0,
    )
    assert reno_log.summary["throughput_kbps"] > 0
    assert adtp_log.summary["throughput_kbps"] > 0
    assert (tmp_path / "results" / "clean_reno_42.json").exists()
    assert (tmp_path / "results" / "clean_adtp_42.json").exists()
