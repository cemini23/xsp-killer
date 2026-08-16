#!/usr/bin/env bash
# Unattended paper tick (Lane A + Lane PC). LIVE_* forced false in-process.
set -uo pipefail
XSP_KILLER_DIR="${XSP_KILLER_DIR:-/opt/xsp-killer}"
cd "${XSP_KILLER_DIR}"
export PYTHONPATH="${XSP_KILLER_DIR}"
/usr/bin/python3 "${XSP_KILLER_DIR}/scripts/paper_tick.py" "$@" || true
