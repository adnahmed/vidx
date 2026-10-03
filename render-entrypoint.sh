#!/bin/bash
set -e

# ─────────────────────────────────────────────────────────────────────────────
# Render-friendly entrypoint.
#
# Render provides no managed MongoDB or RabbitMQ. For self-contained demo
# deployments this script can start embedded MongoDB and Redis plus the Celery
# worker (with beat) inside the same container, then exec the web server.
#
# Production deployments should instead point VIDX_DB_* / RABBITMQ_* (or
# REDIS_*) at external services and leave the VIDX_EMBEDDED_* flags off.
#
# Environment:
#   VIDX_EMBEDDED_MONGO=true   start mongod (dbpath VIDX_MONGO_DBPATH)
#   VIDX_EMBEDDED_REDIS=true   start redis-server on REDIS_PORT
#   VIDX_RUN_WORKER=true       start celery worker -B
#   PORT                       provided by Render; mapped to VIDX_PORT
# ─────────────────────────────────────────────────────────────────────────────

export VIDX_PORT="${VIDX_PORT:-${PORT:-8000}}"
export VIDX_HOST="${VIDX_HOST:-0.0.0.0}"

wait_for_port() {
  local host="$1" port="$2" attempts="${3:-60}"
  for _ in $(seq 1 "$attempts"); do
    if bash -c "echo > /dev/tcp/${host}/${port}" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for ${host}:${port}" >&2
  return 1
}

if [ "${VIDX_EMBEDDED_MONGO:-false}" = "true" ]; then
  MONGO_DATA="${VIDX_MONGO_DBPATH:-/tmp/vidx-mongo}"
  mkdir -p "$MONGO_DATA"
  echo "Starting embedded MongoDB (dbpath=${MONGO_DATA})..."
  mongod --dbpath "$MONGO_DATA" \
    --bind_ip 127.0.0.1 \
    --port "${VIDX_DB_PORT:-27017}" \
    --wiredTigerCacheSizeGB "${VIDX_MONGO_CACHE_GB:-0.25}" \
    --auth \
    --quiet &
  export VIDX_DB_HOST="${VIDX_DB_HOST:-127.0.0.1}"
  wait_for_port "${VIDX_DB_HOST}" "${VIDX_DB_PORT:-27017}"

  # Create the application user through MongoDB's localhost exception so the
  # API/worker can authenticate. Safe to re-run when the user already exists.
  python - <<'PY'
import os
import sys

from pymongo import MongoClient
from pymongo.errors import OperationFailure, PyMongoError

host = os.environ.get("VIDX_DB_HOST", "127.0.0.1")
port = int(os.environ.get("VIDX_DB_PORT", "27017"))
user = os.environ.get("VIDX_DB_USER", "vidx")
password = os.environ.get("VIDX_DB_PASS", "vidx")
try:
    client = MongoClient(
        f"mongodb://{host}:{port}/", serverSelectionTimeoutMS=15000
    )
    client.admin.command(
        "createUser", user, pwd=password, roles=[{"role": "root", "db": "admin"}]
    )
    print("Created embedded MongoDB application user")
except OperationFailure as exc:
    if exc.code == 51003:  # UserAlreadyExists
        print("Embedded MongoDB application user already exists")
    else:
        print(f"Could not create MongoDB user: {exc}", file=sys.stderr)
        sys.exit(1)
except PyMongoError as exc:
    print(f"MongoDB user bootstrap failed: {exc}", file=sys.stderr)
    sys.exit(1)
PY
fi

if [ "${VIDX_EMBEDDED_REDIS:-false}" = "true" ]; then
  echo "Starting embedded Redis..."
  redis-server \
    --port "${REDIS_PORT:-6379}" \
    --maxmemory "${VIDX_REDIS_MAXMEMORY:-96mb}" \
    --maxmemory-policy allkeys-lru \
    --save "" \
    --appendonly no &
  export REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
  wait_for_port "${REDIS_HOST}" "${REDIS_PORT:-6379}" 30
fi

if [ "${VIDX_RUN_WORKER:-false}" = "true" ]; then
  echo "Starting Celery worker with beat..."
  python -m celery -A vidx.services.celery.worker.celery worker \
    --loglevel="${VIDX_WORKER_LOGLEVEL:-info}" \
    --concurrency "${VIDX_WORKER_CONCURRENCY:-1}" \
    --pool "${VIDX_WORKER_POOL:-solo}" \
    -B &
fi

if [ $# -eq 0 ]; then
  set -- python -m uvicorn vidx.web.application:get_app \
    --host "$VIDX_HOST" --port "$VIDX_PORT" --factory
fi

echo "Starting: $*"
exec "$@"
