#!/usr/bin/env bash
# Tune the NetworkManager AP connection on wlan0 for stable phone clients.
#
# Pi OS Bookworm uses NetworkManager + wpa_supplicant in AP mode rather than
# hostapd, so tuning is via nmcli. Some hostapd-level knobs (DTIM, beacon
# interval, U-APSD) are not exposed by NM; what NM does expose covers the
# main wins: channel, powersave, band.
#
# Idempotent. Safe to re-run.
# Run as root: sudo ./apsetup.sh

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Must run as root (use sudo)." >&2
    exit 1
fi

WLAN_IFACE="${WLAN_IFACE:-wlan0}"
CHANNEL="${CHANNEL:-11}"
BAND="${BAND:-bg}"   # bg = 2.4 GHz, a = 5 GHz

# Find the AP-mode NM connection on the interface, unless overridden.
if [ -n "${AP_CONN:-}" ]; then
    :
else
    AP_CONN=$(nmcli -t -f NAME,DEVICE,TYPE connection show \
        | awk -F: -v dev="$WLAN_IFACE" '$2==dev && $3=="802-11-wireless"{print $1; exit}')
fi

if [ -z "$AP_CONN" ]; then
    echo "No NM Wi-Fi connection found on $WLAN_IFACE." >&2
    echo "List connections with: nmcli connection show" >&2
    exit 1
fi

echo "==> Tuning NM connection '$AP_CONN' on $WLAN_IFACE"
echo "    band=$BAND channel=$CHANNEL"

# 802-11-wireless.powersave: 2 = disable. AP interfaces should never sleep.
nmcli connection modify "$AP_CONN" \
    802-11-wireless.band "$BAND" \
    802-11-wireless.channel "$CHANNEL" \
    802-11-wireless.powersave 2

# Bounce the connection so the new channel takes effect.
echo "==> Re-activating connection"
nmcli connection down "$AP_CONN" >/dev/null 2>&1 || true
sleep 1
nmcli connection up "$AP_CONN"

# Belt-and-braces: tell the device-level power save to stay off too. NM may
# override per-connection settings on some builds, this re-asserts at the
# device layer.
iw dev "$WLAN_IFACE" set power_save off 2>/dev/null || true

echo
echo "==> Current $WLAN_IFACE state"
iw dev "$WLAN_IFACE" info | grep -E "channel|txpower|type" || true
echo -n "    "; iw dev "$WLAN_IFACE" get power_save || true

echo
echo "==> Connected clients (re-run later to see fresh stats):"
iw dev "$WLAN_IFACE" station dump || true

echo
echo "Done. Reconnect the phone, then run:"
echo "    sudo iw dev $WLAN_IFACE station dump"
echo "to compare tx failed / tx packets under the new config."
