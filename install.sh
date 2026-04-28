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
    curl ca-certificates

echo "==> Installing uv (system-wide)"
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | \
        env UV_INSTALL_DIR=/usr/local/bin sh
fi
uv --version

echo "==> Provisioning Python environment via uv"
cd "$APP_DIR"
sudo -u "$APP_USER" env HOME="/home/$APP_USER" uv sync --frozen 2>/dev/null || \
    sudo -u "$APP_USER" env HOME="/home/$APP_USER" uv sync

echo "==> Configuring NetworkManager AP on wlan0"
# Trixie ships NetworkManager as the default network stack. We use NM to bring
# wlan0 up as an AP with a static IP, then run our own dnsmasq for DHCP and
# the dmx.local alias (NM's built-in 'shared' mode would conflict with that).
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
