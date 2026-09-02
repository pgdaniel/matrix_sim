#!/usr/bin/env bash
# Installs/updates the systemd --user units in systemd-user/ for the current
# user and (re)starts them. Run this after cloning, and again any time a
# unit file in systemd-user/ changes.
#
# These run as your normal login user (no sudo) — this is the desktop/dev
# setup (matrix-display in --simulate mode, plus the three audio senders
# feeding the real panel on the Pi). For driving GPIO-attached hardware
# directly from this machine, that needs a root systemd service instead;
# see systemd/ (the Pi's units) for the shape that takes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
SERVICES=(matrix-display matrix-view matrix-settings audio-spectrum audio-oscope audio-mondrian)

mkdir -p "$UNIT_DIR"
cp "$SCRIPT_DIR"/systemd-user/*.service "$UNIT_DIR"/

systemctl --user daemon-reload
systemctl --user enable --now "${SERVICES[@]/%/.service}"

cat <<EOF

Installed. Status:
EOF
systemctl --user status --no-pager "${SERVICES[@]/%/.service}" || true

cat <<EOF

If you want these to keep running (and start at boot) even when you're
logged out, enable lingering once:

  loginctl enable-linger \$USER

Logs:  journalctl --user -u matrix-display -u matrix-view -u matrix-settings -f
       journalctl --user -u audio-spectrum -u audio-oscope -u audio-mondrian -f
EOF
