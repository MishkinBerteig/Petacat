#!/usr/bin/env bash
#
# Petacat development stack, natively on macOS (WP2.1).
#
# Replaces `docker compose -f docker-compose.dev.yml up`.  The container stack was
# removed because Phase 0 is measurement-driven and the parallelism work needs the
# engine on the host's own cores: a Linux VM between the engine and an M-series chip
# hides exactly the properties Workstream B is trying to exploit, and it kept the e2e
# suite behind a `docker compose exec` that most runs simply skipped.
#
#   scripts/dev.sh          start Postgres, API and client
#   scripts/dev.sh api      API only
#   scripts/dev.sh client   client only
#   scripts/dev.sh db       ensure Postgres is running, then exit
#   scripts/dev.sh stop     stop the API and client (Postgres is left running)
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

PG_FORMULA="postgresql@17"
PG_BIN="/opt/homebrew/opt/${PG_FORMULA}/bin"
VENV="$REPO/.venv"
API_PORT="${PORT:-8100}"
CLIENT_PORT="${CLIENT_PORT:-59595}"

export PATH="$PG_BIN:$PATH"
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://petacat:dev@localhost:5432/petacat}"
export SEED_DATA_DIR="${SEED_DATA_DIR:-$REPO/seed_data}"

die() { echo "error: $*" >&2; exit 1; }

ensure_venv() {
    [ -x "$VENV/bin/python" ] || die "no venv at $VENV — run: python3.14 -m venv .venv && .venv/bin/pip install -e '.[dev]'"
}

ensure_db() {
    if ! pg_isready -h localhost -p 5432 -q 2>/dev/null; then
        echo "starting $PG_FORMULA..."
        brew services start "$PG_FORMULA" >/dev/null
        for _ in $(seq 1 30); do
            pg_isready -h localhost -p 5432 -q 2>/dev/null && break
            sleep 1
        done
    fi
    pg_isready -h localhost -p 5432 -q || die "Postgres did not come up on localhost:5432"

    # The role and both databases are created if absent, so a fresh clone needs no
    # manual setup step.  petacat_test is separate from petacat precisely so that an
    # e2e run cannot touch the Training Session in the development database.
    psql -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='petacat'" | grep -q 1 \
        || psql -d postgres -qc "CREATE ROLE petacat LOGIN PASSWORD 'dev' CREATEDB"
    for db in petacat petacat_test; do
        psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 \
            || createdb -O petacat "$db"
    done
    echo "postgres ready on localhost:5432 (petacat, petacat_test)"
}

start_api() {
    ensure_venv
    echo "api      http://localhost:$API_PORT"
    exec "$VENV/bin/uvicorn" server.main:app --host 127.0.0.1 --port "$API_PORT" --reload
}

start_client() {
    [ -d client/node_modules ] || (cd client && npm install)
    echo "client   http://localhost:$CLIENT_PORT"
    cd client && exec npm run dev -- --port "$CLIENT_PORT"
}

case "${1:-all}" in
    db)     ensure_db ;;
    api)    ensure_db; start_api ;;
    client) start_client ;;
    stop)
        pkill -f "uvicorn server.main:app" 2>/dev/null && echo "stopped api" || true
        pkill -f "vite.*$CLIENT_PORT" 2>/dev/null && echo "stopped client" || true
        echo "postgres left running — stop it with: brew services stop $PG_FORMULA"
        ;;
    all)
        ensure_db
        ensure_venv
        [ -d client/node_modules ] || (cd client && npm install)
        "$VENV/bin/uvicorn" server.main:app --host 127.0.0.1 --port "$API_PORT" --reload &
        API_PID=$!
        (cd client && npm run dev -- --port "$CLIENT_PORT") &
        CLIENT_PID=$!
        trap 'kill $API_PID $CLIENT_PID 2>/dev/null || true' INT TERM
        echo
        echo "  GUI  http://localhost:$CLIENT_PORT"
        echo "  API  http://localhost:$API_PORT"
        echo "  ctrl-c to stop (Postgres keeps running)"
        echo
        wait
        ;;
    *) die "unknown command: $1 (expected: all, api, client, db, stop)" ;;
esac
