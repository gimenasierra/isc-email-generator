#!/usr/bin/env bash
# Detiene unicamente la instancia de ISC Email Generator y valida su identidad
# antes de senalar el proceso. Equivalente Linux de scripts/stop_app.ps1.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT/.run/app.pid"
VENV_PYTHON="$ROOT/backend/.venv/bin/python"
RUNNER="$ROOT/backend/run.py"

app_pid=0
recovered_from_port=false

if [ -f "$PID_FILE" ]; then
  pid_text="$(tr -d ' \t\r\n' < "$PID_FILE" 2>/dev/null || true)"
  case "$pid_text" in
    ''|*[!0-9]*)
      rm -f "$PID_FILE"
      app_pid=0
      ;;
    *)
      app_pid="$pid_text"
      ;;
  esac
fi

if [ "$app_pid" -gt 0 ] && ! kill -0 "$app_pid" 2>/dev/null; then
  rm -f "$PID_FILE"
  app_pid=0
fi

if [ "$app_pid" -eq 0 ]; then
  listener_pid=""
  if command -v ss >/dev/null 2>&1; then
    listener_pid="$(ss -ltnpH 'sport = :8000' 2>/dev/null \
      | grep -E '127\.0\.0\.1:8000|\[::1\]:8000|::1:8000' \
      | head -n 1 \
      | sed -n 's/.*pid=\([0-9]\{1,\}\).*/\1/p')"
  fi
  if [ -z "$listener_pid" ] && command -v lsof >/dev/null 2>&1; then
    listener_pid="$(lsof -nP -iTCP:8000 -sTCP:LISTEN -t 2>/dev/null | head -n 1)"
  fi
  if [ -z "$listener_pid" ]; then
    echo "La aplicacion ya estaba detenida."
    exit 0
  fi
  app_pid="$listener_pid"
  recovered_from_port=true
fi

if [ ! -x "$VENV_PYTHON" ] || [ ! -f "$RUNNER" ]; then
  echo "No se pudo validar de forma segura el proceso. No se finalizo ningun proceso." >&2
  exit 1
fi

expected_python="$(readlink -f "$VENV_PYTHON")"
expected_runner="$(readlink -f "$RUNNER")"
base_python="$("$VENV_PYTHON" -c 'import sys; print(sys._base_executable)' 2>/dev/null || true)"
if [ -n "$base_python" ]; then
  base_python="$(readlink -f "$base_python" 2>/dev/null || printf '%s' "$base_python")"
fi

process_exe="$(readlink -f "/proc/$app_pid/exe" 2>/dev/null || true)"
process_cmd="$(tr '\0' ' ' < "/proc/$app_pid/cmdline" 2>/dev/null || true)"

same_executable=false
if [ -n "$process_exe" ]; then
  if [ "$process_exe" = "$expected_python" ]; then
    same_executable=true
  elif [ -n "$base_python" ] && [ "$process_exe" = "$base_python" ]; then
    same_executable=true
  fi
fi

same_runner=false
case "$process_cmd" in
  *"$expected_runner"*) same_runner=true ;;
esac

if [ "$same_executable" != true ] || [ "$same_runner" != true ]; then
  if [ "$recovered_from_port" = true ]; then
    echo "El puerto 8000 esta ocupado por otro proceso. No se finalizo ningun proceso." >&2
  else
    echo "El PID pertenece a otro proceso. No se finalizo ningun proceso." >&2
  fi
  exit 1
fi

kill "$app_pid" 2>/dev/null || true
for _ in {1..40}; do
  kill -0 "$app_pid" 2>/dev/null || break
  sleep 0.25
done
if kill -0 "$app_pid" 2>/dev/null; then
  kill -9 "$app_pid" 2>/dev/null || true
fi
rm -f "$PID_FILE"
if [ "$recovered_from_port" = true ]; then
  echo "Se recupero de forma segura la instancia que habia perdido su archivo PID."
fi
echo "ISC Email Generator se detuvo correctamente."
exit 0
