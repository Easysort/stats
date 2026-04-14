"""Entry point for the hosted office dashboard."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from stats.office.server import create_app

HOST = os.environ.get("STATS_HOST", "0.0.0.0")
PORT = int(os.environ.get("STATS_PORT", os.environ.get("STATS_API_PORT", "8150")))
LOG_LEVEL = os.environ.get("STATS_LOG_LEVEL", "info")


def main() -> None:
  uvicorn.run(create_app(), host=HOST, port=PORT, log_level=LOG_LEVEL)


if __name__ == "__main__":
  main()
