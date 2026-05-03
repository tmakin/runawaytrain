#!/usr/bin/env bash
# Sync local repo to the Pi and restart the service.
#
# Usage:
#   ./sync.sh                # sync to default host, restart service
#   ./sync.sh --no-restart   # sync only, don't restart
#   PI_HOST=pi@192.168.50.1 ./sync.sh
#
# Defaults assume you are joined to the TunnelDMX hotspot.

set -euo pipefail

PI_HOST="${PI_HOST:-pi@192.168.50.1}"
PI_PATH="${PI_PATH:-/home/pi/runawaytrain}"
PI_PASS="${PI_PASS:-indatunnel}"
RESTART=1

if ! command -v sshpass >/dev/null 2>&1; then
    echo "sshpass not found. Install with: brew install hudochenkov/sshpass/sshpass" >&2
    exit 1
fi
SSHPASS_CMD=(sshpass -p "$PI_PASS")
SSH_OPTS=(
    -o StrictHostKeyChecking=no
    -o UserKnownHostsFile=/dev/null
    -o LogLevel=ERROR
    -o PubkeyAuthentication=no
    -o PreferredAuthentications=password
    -o IdentitiesOnly=yes
)

for arg in "$@"; do
    case "$arg" in
        --no-restart) RESTART=0 ;;
        -h|--help)
            sed -n '2,9p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown arg: $arg" >&2
            exit 1
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Explicit allowlist: only these paths get synced to the Pi.
# Add new files/dirs here as the project grows.
INCLUDES=(
    src
    pyproject.toml
    tunnel-dmx.service
    scripts
    docs
    README.md
)

echo "==> Syncing to $PI_HOST:$PI_PATH"
SOURCES=()
for path in "${INCLUDES[@]}"; do
    if [ ! -e "$SCRIPT_DIR/$path" ]; then
        echo "  skip (missing): $path"
        continue
    fi
    echo "  + $path"
    SOURCES+=("$path")
done

if [ "${#SOURCES[@]}" -eq 0 ]; then
    echo "Nothing to sync." >&2
    exit 1
fi

# Run rsync from SCRIPT_DIR with relative paths so files land at the dest root,
# not under a recreated absolute-path tree.
( cd "$SCRIPT_DIR" && "${SSHPASS_CMD[@]}" rsync -av -e "ssh ${SSH_OPTS[*]}" "${SOURCES[@]}" "$PI_HOST:$PI_PATH/" )

if [ "$RESTART" -eq 1 ]; then
    echo "==> Syncing Python deps and restarting service"
    # Single SSH session: uv sync (as the login user, no sudo) + service restart.
    # The systemctl commands need a /etc/sudoers.d/tunnel-dmx-deploy NOPASSWD
    # rule so this runs unattended (see PI_SETUP.md).
    "${SSHPASS_CMD[@]}" ssh "${SSH_OPTS[@]}" "$PI_HOST" "cd '$PI_PATH' && uv sync && sudo -n systemctl restart tunnel-dmx && sudo -n systemctl is-active tunnel-dmx"
    echo "==> Done. Tail logs with:"
    echo "    sshpass -p '$PI_PASS' ssh $PI_HOST 'sudo journalctl -u tunnel-dmx -f'"
else
    echo "==> Sync complete (deps not synced, service not restarted)"
fi
