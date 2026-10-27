"""FastAPI backend layer for ADTP live events and replay dashboard.

Run:
    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from adtp.congestion import CONTROLLERS
from adtp.runner import run_scenario, run_side_by_side
from adtp.scenarios import SCENARIOS

app = FastAPI(title="ADTP API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

active_runs: dict[str, dict] = {}
active_listeners: dict[str, list[asyncio.Queue]] = {}


class RunRequest(BaseModel):
    scenario: str = "clean"
    controller: str = "adtp"
    seed: Optional[int] = 42
    size: Optional[int] = 500_000
    overrides: Optional[dict[str, Any]] = None


class SideBySideRequest(BaseModel):
    scenario: str = "lossy"
    seed: Optional[int] = 42
    size: Optional[int] = 500_000


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/meta")
def meta() -> dict:
    return {
        "controllers": list(CONTROLLERS),
        "scenarios": {k: s.to_dict() for k, s in SCENARIOS.items()},
    }


@app.get("/api/results")
def list_results() -> list[dict]:
    """List all saved benchmark runs in the results directory."""
    items = []
    for file in sorted(RESULTS_DIR.glob("*.json")):
        try:
            data = json.loads(file.read_text())
            items.append({
                "name": file.stem,
                "filename": file.name,
                "scenario": data.get("meta", {}).get("scenario", file.stem.split("_")[0]),
                "controller": data.get("meta", {}).get("controller", ""),
                "seed": data.get("meta", {}).get("seed"),
                "file_bytes": data.get("meta", {}).get("file_bytes"),
                "summary": data.get("summary", {}),
            })
        except Exception:
            continue
    return items


@app.get("/api/results/{name}")
def get_result(name: str) -> dict:
    """Retrieve full run JSON for replay."""
    filename = name if name.endswith(".json") else f"{name}.json"
    file_path = (RESULTS_DIR / filename).resolve()
    if file_path.parent != RESULTS_DIR.resolve() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Result '{name}' not found")
    try:
        return json.loads(file_path.read_text())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read result: {e}")


@app.post("/api/runs")
async def start_run(req: RunRequest) -> dict:
    """Start a benchmark run in the background."""
    if req.scenario not in SCENARIOS:
        raise HTTPException(status_code=400, detail=f"Unknown scenario '{req.scenario}'")
    if req.controller not in CONTROLLERS:
        raise HTTPException(status_code=400, detail=f"Unknown controller '{req.controller}'")

    run_id = str(uuid.uuid4())[:8]
    active_runs[run_id] = {
        "id": run_id,
        "status": "running",
        "scenario": req.scenario,
        "controller": req.controller,
        "seed": req.seed,
        "size": req.size,
        "summary": None,
        "result_name": None,
        "error": None,
    }
    active_listeners[run_id] = []

    def on_event(ev: dict) -> None:
        for q in active_listeners.get(run_id, []):
            try:
                q.put_nowait(ev)
            except Exception:
                pass

    async def _execute() -> None:
        try:
            log = await run_scenario(
                req.scenario,
                req.controller,
                seed=req.seed,
                file_bytes=req.size,
                out_dir=RESULTS_DIR,
                overrides=req.overrides,
                log_listener=on_event,
            )
            active_runs[run_id]["status"] = "completed"
            active_runs[run_id]["summary"] = log.summary
            active_runs[run_id]["result_name"] = f"{req.scenario}_{req.controller}_{log.meta['seed']}"
        except Exception as e:
            active_runs[run_id]["status"] = "failed"
            active_runs[run_id]["error"] = str(e)

    asyncio.create_task(_execute())
    return {"run_id": run_id, "status": "running"}


@app.get("/api/runs/{run_id}")
def get_run_status(run_id: str) -> dict:
    if run_id not in active_runs:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return active_runs[run_id]


@app.post("/api/side-by-side")
async def execute_side_by_side(req: SideBySideRequest) -> dict:
    """Execute ADTP and Reno concurrently on the same scenario and seed."""
    if req.scenario not in SCENARIOS:
        raise HTTPException(status_code=400, detail=f"Unknown scenario '{req.scenario}'")

    seed = req.seed if req.seed is not None else 42
    size = req.size if req.size is not None else 500_000

    try:
        reno_log, adtp_log = await run_side_by_side(
            req.scenario,
            seed=seed,
            file_bytes=size,
            out_dir=RESULTS_DIR,
        )
        return {
            "status": "completed",
            "scenario": req.scenario,
            "seed": seed,
            "reno_result": f"{req.scenario}_reno_{seed}",
            "adtp_result": f"{req.scenario}_adtp_{seed}",
            "reno_summary": reno_log.summary,
            "adtp_summary": adtp_log.summary,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Side-by-side run failed: {e}")


@app.websocket("/ws/runs/{run_id}")
async def websocket_run(websocket: WebSocket, run_id: str) -> None:
    """Live stream of RunLog events for an in-flight run."""
    if run_id not in active_runs:
        await websocket.close(code=1008, reason="Unknown run")
        return
    await websocket.accept()
    queue: asyncio.Queue = asyncio.Queue()
    if run_id not in active_listeners:
        active_listeners[run_id] = []
    active_listeners[run_id].append(queue)

    try:
        while True:
            # Check if run completed and queue is empty
            if queue.empty() and run_id in active_runs and active_runs[run_id]["status"] != "running":
                await websocket.send_json({"kind": "done", "status": active_runs[run_id]["status"]})
                break
            try:
                ev = await asyncio.wait_for(queue.get(), timeout=1.0)
                await websocket.send_json(ev)
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        pass
    finally:
        if run_id in active_listeners and queue in active_listeners[run_id]:
            active_listeners[run_id].remove(queue)
