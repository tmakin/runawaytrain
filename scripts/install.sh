#!/usr/bin/env bash
# One-shot setup script for a fresh Raspberry Pi OS Lite (Trixie) install.
# Run as root: sudo bash install.sh

set -euo pipefail

# === CHECK BEFORE RUNNING =====================================================
HOTSPOT_PASS="indatunnel"
# =============================================================================

HOTSPOT_SSID="TunnelDMX"
HOTSPOT_CHANNEL=6
PI_IP="192.168.50.1"
PI_CIDR="192.168.50.1/24"
DHCP_START="192.168.50.10"
DHCP_END="192.168.50.50"
APP_DIR="/home/pi/runawaytrain"
APP_USER="pi"
NM_CON="TunnelDMX"

if [ "$(id -u)" -ne 0 ]; then
    echo "Must be run as root (sudo bash install.sh)" >&2
    exit 1
fi

echo "==> Installing apt packages"
apt-get update
apt-get install -y \
    network-manager dnsmasq avahi-daemon \
    ola \
    curl ca-certificates

echo "==> Blacklisting kernel ftdi_sio so libftdi can claim the adapter"
# OLA's FTDI USB DMX plugin uses libftdi to talk to the chip directly, which
# requires the kernel ftdi_sio driver NOT to have grabbed the device. Without
# this, /dev/ttyUSB0 appears and OLA's USB plugins fight over it (Serial USB,
# StageProfi, Enttec Open DMX) — none of them produce valid DMX framing for
# this adapter. Blacklist the kernel module permanently and unload it now.
echo "blacklist ftdi_sio" > /etc/modprobe.d/blacklist-ftdi.conf
rmmod ftdi_sio 2>/dev/null || true

echo "==> Enabling olad (Open Lighting daemon)"
systemctl enable olad
systemctl restart olad
sleep 3

echo "==> Configuring OLA plugins (FTDI USB DMX only, others off)"
# Disable every plugin that could compete with FTDI USB DMX for the adapter.
# - 5  Serial USB        (auto-tries multiple protocols on /dev/ttyUSB*)
# - 6  Enttec Open DMX   (no auto-discovery; needs explicit config)
# - 8  StageProfi        (different vendor, claims /dev/ttyUSB0 anyway)
# Enable plugin 13 (FTDI USB DMX), which uses libftdi directly.
ola_plugin_state -p 5  -s disable || true
ola_plugin_state -p 6  -s disable || true
ola_plugin_state -p 8  -s disable || true
ola_plugin_state -p 13 -s enable  || true
systemctl restart olad
sleep 3

echo "==> Patching FTDI USB DMX device to universe 0 (if discovered)"
# ola_dev_info output for the FTDI plugin is e.g.:
#   Device 8: FT232R USB UART with serial number : XXXX
#     port 1, OUT FT232R USB UART with serial number : XXXX
# Note: port number is NOT necessarily 0. Parse both device id and port id.
DEV_LINE=$(ola_dev_info 2>/dev/null | awk '/^Device [0-9]+:.*FT[0-9]/ {print; exit}')
DEV_ID=$(echo "$DEV_LINE" | sed -E 's/^Device ([0-9]+):.*/\1/')
# Port line for that device: the next line starting with "  port"
PORT_ID=$(ola_dev_info 2>/dev/null | awk -v want="$DEV_ID" '
    /^Device [0-9]+:/ { in_dev = ($2 == want":") }
    in_dev && /^  port [0-9]+, OUT/ { gsub(/,/,"",$2); print $2; exit }
')
if [ -n "${DEV_ID:-}" ] && [ -n "${PORT_ID:-}" ]; then
    echo "  patching device $DEV_ID port $PORT_ID -> universe 0"
    ola_patch -d "$DEV_ID" -p "$PORT_ID" -u 0 || \
        echo "  (patch failed; run manually after plugging in the adapter)"
else
    echo "  (no FTDI device found yet; plug in the adapter and run:"
    echo "     ola_dev_info        # note the FT232R device id and port id"
    echo "     ola_patch -d <DEV_ID> -p <PORT_ID> -u 0"
    echo "   then: sudo systemctl restart tunnel-dmx)"
fi

echo "==> Installing uv (system-wide)"
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | \
        env UV_INSTALL_DIR=/usr/local/bin sh
fi
uv --version

echo "==> Provisioning Python environment via uv"
cd "$APP_DIR"
# The systemd unit now runs as the pi user (with CAP_NET_BIND_SERVICE for
# port 80), so the venv must be pi-owned. Reset ownership in case an earlier
# install ran the service as root and dropped root-owned __pycache__ files.
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
sudo -u "$APP_USER" env HOME="/home/$APP_USER" uv sync --frozen 2>/dev/null || \
    sudo -u "$APP_USER" env HOME="/home/$APP_USER" uv sync

echo "==> Configuring NetworkManager AP on wlan0"
# Trixie ships NetworkManager as the default network stack. We use NM to bring
# wlan0 up as an AP with a static IP, then run our own dnsmasq for DHCP and
# the dmx.local alias (NM's built-in 'shared' mode would conflict with that).

# Disable autoconnect on any other wifi profile bound to wlan0 (e.g. the
# Imager-created home WiFi connection). A radio can only be in one mode at
# a time, so a client connection holding wlan0 prevents the AP from coming up.
echo "  - releasing wlan0 from other wifi profiles"
while IFS=: read -r name type; do
    [ "$type" = "802-11-wireless" ] || continue
    [ "$name" = "$NM_CON" ] && continue
    echo "    disabling autoconnect on '$name'"
    nmcli connection modify "$name" connection.autoconnect no || true
    nmcli connection down "$name" 2>/dev/null || true
done < <(nmcli -t -f NAME,TYPE connection show)

nmcli connection delete "$NM_CON" 2>/dev/null || true
nmcli connection add \
    type wifi ifname wlan0 con-name "$NM_CON" autoconnect yes ssid "$HOTSPOT_SSID"
nmcli connection modify "$NM_CON" \
    802-11-wireless.mode ap \
    802-11-wireless.band bg \
    802-11-wireless.channel "$HOTSPOT_CHANNEL" \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$HOTSPOT_PASS" \
    ipv4.method manual \
    ipv4.addresses "$PI_CIDR" \
    ipv4.never-default yes \
    ipv6.method disabled

echo "==> Configuring dnsmasq (DHCP + dmx.local alias)"
# Stop NM from launching its own dnsmasq for split DNS — we run a dedicated one.
mkdir -p /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/no-dnsmasq.conf <<EOF
[main]
dns=default
EOF

cat > /etc/dnsmasq.conf <<EOF
interface=wlan0
bind-interfaces
except-interface=lo
domain-needed
bogus-priv
dhcp-range=$DHCP_START,$DHCP_END,255.255.255.0,24h
dhcp-option=3,$PI_IP
dhcp-option=6,$PI_IP
address=/dmx.local/$PI_IP
EOF

# dnsmasq must wait for wlan0 to come up with its static IP before binding.
mkdir -p /etc/systemd/system/dnsmasq.service.d
cat > /etc/systemd/system/dnsmasq.service.d/override.conf <<EOF
[Unit]
After=NetworkManager-wait-online.service
Wants=NetworkManager-wait-online.service
EOF

echo "==> Installing systemd unit for tunnel-dmx"
cp "$APP_DIR/tunnel-dmx.service" /etc/systemd/system/tunnel-dmx.service

systemctl daemon-reload
systemctl enable NetworkManager dnsmasq tunnel-dmx
systemctl enable NetworkManager-wait-online.service || true

cat <<EOF

============================================================
Install complete.

  WiFi SSID:  $HOTSPOT_SSID
  Password:   $HOTSPOT_PASS
  URL:        http://dmx.local  (or http://$PI_IP)

Reboot now: sudo reboot
============================================================
EOF
