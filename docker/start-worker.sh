#!/usr/bin/env bash
set -euo pipefail

echo "Starting Dramatiq worker..."
exec python -m scripts.run_worker
