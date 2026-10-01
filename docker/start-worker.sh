#!/usr/bin/env bash
set -euo pipefail

echo "Starting schedule worker..."
exec python -m scripts.run_schedule_worker
