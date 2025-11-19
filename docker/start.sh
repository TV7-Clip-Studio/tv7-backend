#!/usr/bin/env bash
set -m  # Enable job control

echo "Starting application processes..."

# Start the worker in background
echo "Starting Dramatiq worker..."
python -u -m scripts.run_worker 2>&1 | sed 's/^/[worker] /' &
WORKER_PID=$!
echo "Worker started with PID $WORKER_PID"

# Start uvicorn in foreground (this keeps the container alive)
echo "Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir src
