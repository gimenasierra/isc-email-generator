from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_INDEX = ROOT / "frontend" / "dist" / "index.html"
RUN_DIR = ROOT / ".run"
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "app.log"
STOP_SCRIPT_POWERSHELL = ROOT / "scripts" / "stop_app.ps1"
STOP_SCRIPT_SHELL = ROOT / "scripts" / "stop_app.sh"
sys.path.insert(0, str(BACKEND_DIR))
from app.runtime import DEFAULT_APP_PORT, app_port, runtime_signature


try:
    APP_PORT = app_port()
except ValueError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2) from exc

PID_FILE = RUN_DIR / ("app.pid" if APP_PORT == DEFAULT_APP_PORT else f"app-{APP_PORT}.pid")
APP_URL = f"http://127.0.0.1:{APP_PORT}"
HEALTH_URL = f"{APP_URL}/api/health"


EXPECTED_RUNTIME_SIGNATURE = runtime_signature()


def app_status(timeout: float = 0.75) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            ready = response.status == 200 and payload.get("status") == "ok"
            return ready, str(payload.get("runtime_signature", ""))
    except (OSError, ValueError, urllib.error.URLError):
        return False, ""


def app_is_ready(timeout: float = 0.75) -> bool:
    return app_status(timeout)[0]


def stop_outdated_instance() -> bool:
    print("Se detectó una versión anterior en ejecución. Actualizando la instancia local...")
    if os.name == "nt":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(STOP_SCRIPT_POWERSHELL),
        ]
        stop_hint = ROOT / "Detener app.cmd"
    else:
        command = ["bash", str(STOP_SCRIPT_SHELL)]
        stop_hint = ROOT / "Detener app.sh"
    try:
        completed = subprocess.run(command, cwd=ROOT, check=False)
    except OSError as exc:
        print(f"ERROR: no se pudo ejecutar el detenedor ({exc}).", file=sys.stderr)
        print(f"Ejecute manualmente {stop_hint} y vuelva a iniciar la aplicación.", file=sys.stderr)
        return False
    if completed.returncode != 0:
        print("ERROR: no se pudo detener de forma segura la instancia anterior.", file=sys.stderr)
        print(f"Ejecute {stop_hint} y vuelva a iniciar la aplicación.", file=sys.stderr)
        return False
    for _ in range(40):
        if not app_is_ready():
            return True
        time.sleep(0.25)
    print(f"ERROR: la instancia anterior no liberó el puerto {APP_PORT}.", file=sys.stderr)
    return False


def open_browser_when_ready() -> None:
    for _ in range(120):
        if app_is_ready():
            print(f"Aplicación disponible en {APP_URL}")
            webbrowser.open(APP_URL)
            return
        time.sleep(0.25)
    print(f"No se pudo confirmar el inicio. Revise {LOG_FILE}", file=sys.stderr)


def logging_config() -> dict:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
            "access": {"format": "%(asctime)s %(levelname)s %(message)s"},
        },
        "handlers": {
            "console": {"class": "logging.StreamHandler", "formatter": "default", "stream": "ext://sys.stderr"},
            "console_access": {"class": "logging.StreamHandler", "formatter": "access", "stream": "ext://sys.stdout"},
            "file": {"class": "logging.FileHandler", "formatter": "default", "filename": str(LOG_FILE), "encoding": "utf-8"},
            "file_access": {"class": "logging.FileHandler", "formatter": "access", "filename": str(LOG_FILE), "encoding": "utf-8"},
        },
        "loggers": {
            "uvicorn": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["console_access", "file_access"], "level": "INFO", "propagate": False},
        },
    }


def main() -> int:
    ready, running_signature = app_status()
    if ready:
        if running_signature == EXPECTED_RUNTIME_SIGNATURE:
            print("ISC Email Generator ya está ejecutándose. Abriendo la instancia existente...")
            webbrowser.open(APP_URL)
            return 0
        if not stop_outdated_instance():
            return 5

    if not FRONTEND_INDEX.exists():
        print("ERROR: el frontend no está compilado.", file=sys.stderr)
        print(f"Abra una terminal en {ROOT / 'frontend'} y ejecute:", file=sys.stderr)
        npm = "npm.cmd" if os.name == "nt" else "npm"
        print(f"  {npm} install", file=sys.stderr)
        print(f"  {npm} run build", file=sys.stderr)
        return 3

    try:
        import uvicorn
    except ImportError as exc:
        print(f"ERROR: faltan dependencias Python: {exc}", file=sys.stderr)
        print(f"Ejecute: {sys.executable} -m pip install -r {BACKEND_DIR / 'requirements.txt'}", file=sys.stderr)
        return 2

    LOG_DIR.mkdir(exist_ok=True)
    RUN_DIR.mkdir(exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    browser_thread = threading.Thread(target=open_browser_when_ready, daemon=True)
    browser_thread.start()
    try:
        uvicorn.run(
            "app.main:app",
            host="127.0.0.1",
            port=APP_PORT,
            log_config=logging_config(),
            access_log=True,
        )
        return 0
    finally:
        try:
            if PID_FILE.exists() and PID_FILE.read_text(encoding="ascii").strip() == str(os.getpid()):
                PID_FILE.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
