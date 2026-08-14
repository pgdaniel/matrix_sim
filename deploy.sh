#!/usr/bin/env bash
# Copies this project to the Pi's home directory with rsync, matching the
# flat layout systemd/matrix-server.service and matrix-settings.service
# expect (matrix_server.py, settings_app.py, screens/, etc. directly under
# /home/pi).
set -euo pipefail

PI_HOST="${PI_HOST:-pi@192.168.1.109}"
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
  --exclude="screen_config.json"  # runtime state the Pi writes itself — never overwrite it from a local dev checkout
)

if [[ "${1:-}" == "--delete" ]]; then
  echo "Will also delete files on the Pi that no longer exist locally."
  RSYNC_ARGS+=(--delete)
fi

echo "Syncing $SCRIPT_DIR/ -> $PI_HOST:$PI_DEST"
rsync "${RSYNC_ARGS[@]}" "$SCRIPT_DIR"/ "$PI_HOST:$PI_DEST"

echo "Restarting services on $PI_HOST..."
ssh "$PI_HOST" '
  sudo systemctl restart matrix-server
  if [ -f /etc/systemd/system/matrix-settings.service ]; then
    sudo systemctl restart matrix-settings
  else
    echo "(matrix-settings.service not installed yet; see README for one-time setup)"
  fi
'

cat <<EOF

Done.

If dependencies changed, install them and restart again:
  ssh $PI_HOST 'cd ${PI_DEST%/} && venv/bin/pip install -r requirements.txt && sudo systemctl restart matrix-server matrix-settings'
EOF
