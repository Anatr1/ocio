#!/usr/bin/env bash
# Push code + models (+ optional offline wheels) from the laptop to the UNO Q, then run setup on the board.
#
#   tools/deploy.sh arduino@<board-ip>                 # code + models
#   tools/deploy.sh arduino@<board-ip> --wheels DIR    # also copy offline wheels (no internet at the venue)
#   tools/deploy.sh arduino@<board-ip> --setup         # and run tools/board_setup.sh remotely
#
# Works from Git Bash on Windows (uses tar over ssh, no rsync needed).
set -euo pipefail
HOST="${1:?usage: deploy.sh user@host [--wheels DIR] [--setup]}"
shift
WHEELS=""
SETUP=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --wheels) WHEELS="$2"; shift 2 ;;
    --setup) SETUP=1; shift ;;
    *) echo "unknown arg $1"; exit 1 ;;
  esac
done
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
echo "[deploy] packing code + models -> $HOST:~/occhio"
tar czf - \
  --exclude='./.git' --exclude='./.venv' --exclude='./runs' --exclude='./datasets' --exclude='*.pt' \
  --exclude='./data/recordings' --exclude='./data/frames' --exclude='__pycache__' \
  crosswalk sim tools dashboard configs firmware models data/videos requirements-board.txt README.md 2>/dev/null \
  | ssh "$HOST" 'mkdir -p ~/occhio && tar xzf - -C ~/occhio'
if [[ -n "$WHEELS" ]]; then
  echo "[deploy] copying offline wheels from $WHEELS"
  tar czf - -C "$WHEELS" . | ssh "$HOST" 'mkdir -p ~/occhio/wheels && tar xzf - -C ~/occhio/wheels'
fi
if [[ $SETUP -eq 1 ]]; then
  ssh -t "$HOST" 'cd ~/occhio && bash tools/board_setup.sh'
fi
echo "[deploy] done. On the board:  cd ~/occhio && .venv/bin/python -m crosswalk --config configs/board.yaml"
