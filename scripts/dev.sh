#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python || ! -d frontend/node_modules ]]; then
  echo 'Install dependencies first: uv sync && npm --prefix frontend ci'
  exit 1
fi
export PYTHONPATH="$PWD/backend"
export DATABASE_URL="${DATABASE_URL:-sqlite:///$PWD/meditron.db}"
api_port="${MEDITRON_API_PORT:-8000}"
web_port="${MEDITRON_WEB_PORT:-5173}"
.venv/bin/python - "$api_port" "$web_port" <<'PY'
import socket
import sys

ports = {"API": sys.argv[1], "интерфейс": sys.argv[2]}
if len(set(ports.values())) != len(ports):
    raise SystemExit("API и интерфейсу нужны разные порты")
for label, raw in ports.items():
    try:
        port = int(raw)
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise SystemExit(f"Некорректный порт для {label}: {raw}") from None
    with socket.socket() as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(
                f"Порт {port} ({label}) уже занят. "
                "Остановите прежний сервер или задайте MEDITRON_API_PORT и MEDITRON_WEB_PORT."
            )
PY
demo_db="$PWD/meditron.db"
if [[ "${MEDITRON_DEMO_RESET:-1}" != "0" && "$DATABASE_URL" == "sqlite:///$demo_db" ]]; then
  if [[ -e "$demo_db" ]] && command -v lsof >/dev/null 2>&1 && lsof -t "$demo_db" >/dev/null 2>&1; then
    echo 'Демонстрационная база ещё открыта другим процессом. Остановите прежний сервер перед запуском.' >&2
    exit 1
  fi
  rm -f -- "$demo_db" "$demo_db-wal" "$demo_db-shm"
  echo 'Предыдущие случаи удалены; создаём новый набор пациентов.'
fi
.venv/bin/alembic upgrade head
.venv/bin/python -m app.seed
pids=()
cleanup() { for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM
.venv/bin/python -m uvicorn app.api:app --host 127.0.0.1 --port "$api_port" --no-access-log &
pids+=("$!")
.venv/bin/python -m app.worker &
pids+=("$!")
./frontend/node_modules/.bin/vite --config frontend/vite.config.ts frontend &
pids+=("$!")
if ! .venv/bin/python - "$api_port" "$web_port" <<'PY'
import sys
import time
import urllib.error
import urllib.request

api_port, web_port = sys.argv[1:]
deadline = time.monotonic() + 20
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{api_port}/health", timeout=1) as response:
            api_ok = response.status == 200
        with urllib.request.urlopen(f"http://127.0.0.1:{web_port}/", timeout=1) as response:
            page = response.read().decode("utf-8")
        if api_ok and "<title>Patient pathway — маршрут пациента</title>" in page:
            break
    except (OSError, urllib.error.URLError, UnicodeError):
        pass
    time.sleep(0.25)
else:
    raise SystemExit("Текущая версия API и интерфейса не ответила за 20 секунд; проверьте ошибки выше")
PY
then
  exit 1
fi
echo "Patient pathway из $PWD: http://127.0.0.1:$web_port · API: http://127.0.0.1:$api_port/docs"
# Stop all children if one exits; works with macOS Bash 3.2 as well.
while true; do
  for pid in "${pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then exit 1; fi
  done
  sleep 1
done
