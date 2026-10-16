#!/usr/bin/env bash
# Lanzador de ISC Email Generator para Linux. Equivalente de "Iniciar app.cmd".
set -u
cd "$(dirname "$0")"
ROOT="$(pwd)"
PORT="${ISC_EMAIL_GENERATOR_PORT:-8000}"
PYTHON="$ROOT/backend/.venv/bin/python"
RUNNER="$ROOT/backend/run.py"
READY_CHECK="$ROOT/backend/check_ready.py"
LOG_FILE="$ROOT/logs/app.log"

mkdir -p "$ROOT/logs" "$ROOT/.run"

log_event() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$LOG_FILE" 2>/dev/null || true
}

if [ ! -x "$PYTHON" ]; then
  cat >&2 <<'EOF'
ERROR: falta el entorno virtual backend/.venv.
Instale Python 3.11 o superior y ejecute desde esta carpeta:
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -r backend/requirements.txt
EOF
  log_event "Inicio fallido: falta backend/.venv"
  exit 2
fi

if [ ! -f "$ROOT/frontend/dist/index.html" ]; then
  cat >&2 <<'EOF'
ERROR: falta la compilacion del frontend.
Ejecute desde esta carpeta:
  cd frontend
  npm install
  npm run build
EOF
  log_event "Inicio fallido: falta frontend/dist"
  exit 3
fi

if ! "$PYTHON" -c "import fastapi, uvicorn, pydantic" >/dev/null 2>&1; then
  echo "ERROR: faltan dependencias Python en backend/.venv." >&2
  echo "Ejecute: $PYTHON -m pip install -r backend/requirements.txt" >&2
  log_event "Inicio fallido: faltan dependencias Python"
  exit 4
fi

nohup "$PYTHON" "$RUNNER" >> "$LOG_FILE" 2>&1 &
APP_PID=$!

attempts=0
while [ "$attempts" -lt 40 ]; do
  if "$PYTHON" "$READY_CHECK" >/dev/null 2>&1; then
    echo "ISC Email Generator esta disponible en http://127.0.0.1:$PORT"
    exit 0
  fi
  if ! kill -0 "$APP_PID" 2>/dev/null; then
    break
  fi
  attempts=$((attempts + 1))
  sleep 1
done

{
  echo "ERROR: la aplicacion no respondio con la version esperada dentro de 40 segundos."
  echo "Ultimas lineas del log:"
  tail -n 20 "$LOG_FILE" 2>/dev/null
} >&2
log_event "Inicio fallido: no respondio en 40 segundos"
exit 6
