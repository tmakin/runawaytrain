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
RESTART=1

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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Explicit allowlist: only these paths get synced to the Pi.
# Add new files/dirs here as the project grows.
INCLUDES=(
    chase.py
    pyproject.toml
    requirements.txt
    tunnel-dmx.service
    install.sh
    templates
    static
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
    SOURCES+=("$SCRIPT_DIR/./$path")
done

if [ "${#SOURCES[@]}" -eq 0 ]; then
    echo "Nothing to sync." >&2
    exit 1
fi

rsync -av --relative "${SOURCES[@]}" "$PI_HOST:$PI_PATH/"

if [ "$RESTART" -eq 1 ]; then
    echo "==> Restarting tunnel-dmx service"
    ssh "$PI_HOST" 'sudo systemctl restart tunnel-dmx && sudo systemctl is-active tunnel-dmx'
    echo "==> Done. Tail logs with:"
    echo "    ssh $PI_HOST 'sudo journalctl -u tunnel-dmx -f'"
else
    echo "==> Sync complete (service not restarted)"
fi
