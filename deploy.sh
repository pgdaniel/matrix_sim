#!/usr/bin/env bash
# Copies this project to the Pi's home directory with rsync, matching the
# flat layout systemd/matrix-server.service expects (matrix_server.py,
# screens/, etc. directly under /home/pi).
set -euo pipefail

PI_HOST="${PI_HOST:-pi@192.168.1.160}"
PI_DEST="${PI_DEST:-/home/pi/}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RSYNC_ARGS=(
  -avz --progress
  --exclude=".git/"
  --exclude=".venv/"
  --exclude="venv/"        # the Pi's own venv (per the systemd unit) — never touch it
  --exclude="__pycache__/"
  --exclude="*.pyc"
  --exclude=".claude/"
)

if [[ "${1:-}" == "--delete" ]]; then
  echo "Will also delete files on the Pi that no longer exist locally."
  RSYNC_ARGS+=(--delete)
fi

echo "Syncing $SCRIPT_DIR/ -> $PI_HOST:$PI_DEST"
rsync "${RSYNC_ARGS[@]}" "$SCRIPT_DIR"/ "$PI_HOST:$PI_DEST"

echo "Restarting matrix-server on $PI_HOST..."
ssh "$PI_HOST" 'sudo systemctl restart matrix-server'

cat <<EOF

Done.

If dependencies changed, install them and restart again:
  ssh $PI_HOST 'cd ${PI_DEST%/} && venv/bin/pip install -r requirements.txt && sudo systemctl restart matrix-server'
EOF
