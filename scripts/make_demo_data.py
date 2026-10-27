"""Generate benchmark runs needed for the dashboard demo.

Runs:
  - run_all(seed=42, file_bytes=500_000): clean, lossy, congested, dynamic for both Reno and ADTP
  - side_by_side("lossy", seed=42, file_bytes=500_000)
  - side_by_side("dynamic", seed=42, file_bytes=500_000)

Usage:
    python scripts/make_demo_data.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from adtp.runner import run_all, run_side_by_side


async def main() -> None:
    print("Generating demo benchmark runs in results/...")
    print("\n1. Running run_all (clean, lossy, congested, dynamic for Reno and ADTP, 500 KB)...")
    await run_all(seed=42, file_bytes=500_000)

    print("\n2. Running side-by-side for lossy (500 KB)...")
    await run_side_by_side("lossy", seed=42, file_bytes=500_000)

    print("\n3. Running side-by-side for dynamic (500 KB)...")
    await run_side_by_side("dynamic", seed=42, file_bytes=500_000)

    print("\n[Demo data generation complete! Files saved to results/]")


if __name__ == "__main__":
    asyncio.run(main())
