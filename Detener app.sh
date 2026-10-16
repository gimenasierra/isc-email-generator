#!/usr/bin/env bash
# Detiene solo la instancia de ISC Email Generator. Equivalente de "Detener app.cmd".
set -u
cd "$(dirname "$0")"
bash scripts/stop_app.sh
exit $?
