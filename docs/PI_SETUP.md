# Raspberry Pi Setup & Deployment Guide

End-to-end instructions for preparing a Raspberry Pi 4B and deploying the
Tunnel DMX Chase Controller to it.

---

## 1. Flash the SD card

1. Download Raspberry Pi Imager: https://www.raspberrypi.com/software/
2. Choose:
   - Device: Raspberry Pi 4
   - OS: Raspberry Pi OS Lite (64-bit, Trixie)
   - Storage: your microSD card
3. Click the gear icon (advanced options) and set:
   - Hostname: `tunneldmx`
   - Enable SSH (use password authentication)
   - Username: `pi`, Password: (your choice, remember it)
   - Configure WiFi: your home/bench WiFi (used only for initial setup, not the venue)
   - Set locale / timezone
4. Write the image and eject the card.

## 2. First boot

1. Insert SD card into the Pi, connect power.
2. Wait ~60 seconds for first boot (it will resize the filesystem and reboot once).
3. From your laptop on the same WiFi:

   ```sh
   ssh pi@tunneldmx.local
   ```

   If `.local` does not resolve, find the IP from your router and use that.

4. Update the system:

   ```sh
   sudo apt-get update && sudo apt-get upgrade -y
   ```

## 3. Deploy the code

From your laptop (in the project directory), use the bundled sync script:

```sh
# First-time deploy over your home WiFi
PI_HOST=pi@tunneldmx.local ./scripts/sync.sh --no-restart
```

`scripts/sync.sh` uses an explicit allowlist (see the `INCLUDES` array at the top of
the script); add new files there as the project grows. `--no-restart` skips
the service restart, which is useful before the systemd unit is installed.

## 4. Configure the hotspot password

On the Pi, edit the password variable before running the installer:

```sh
cd /home/pi/runawaytrain
nano scripts/install.sh
# Change HOTSPOT_PASS="..." to your chosen password (min 8 chars)
```

## 5. Run the installer

```sh
sudo bash /home/pi/runawaytrain/scripts/install.sh
```

The script will install dependencies, configure the hotspot, and enable the
systemd service. It prints a summary at the end with the SSID, password, and
URL.

Reboot to bring up the hotspot:

```sh
sudo reboot
```

## 5b. Patch DMX (only if adapter wasn't plugged in during install)

If the Enttec Open DMX adapter was plugged in when `scripts/install.sh` ran, the
DMX universe is already patched and you can skip this step.

If you plugged in afterwards, run once on the Pi:

```sh
ola_dev_info                          # note the device id of the FTDI / Open DMX entry
sudo ola_patch -d <ID> -p 0 -u 0      # patch port 0 of that device to universe 0
sudo systemctl restart tunnel-dmx
```

The patch persists across reboots.

## 6. Verify

After reboot, the Pi is no longer on your home WiFi (it is now an access point).

1. On your phone, join WiFi `TunnelDMX` with the password you set.
2. Open `http://dmx.local` (or `http://192.168.50.1`) in the browser.
3. The control UI should load.

## 7. SSH after deployment

The Pi is now a hotspot, so SSH from your laptop by joining `TunnelDMX` first:

```sh
ssh pi@192.168.50.1
```

### Passwordless deploy (recommended)

`scripts/sync.sh` opens an SSH session and runs `sudo systemctl restart tunnel-dmx`.
By default that prompts twice (SSH password, then sudo password) on every
deploy. Two one-time setup steps eliminate both prompts.

**1. SSH key auth.** From your laptop:

```sh
ssh-keygen -t ed25519 -f ~/.ssh/tunnel_dmx -N ""    # skip if you already have a key
ssh-copy-id -i ~/.ssh/tunnel_dmx.pub pi@192.168.50.1
```

Optionally add a host alias to `~/.ssh/config`:

```
Host tunneldmx
    HostName 192.168.50.1
    User pi
    IdentityFile ~/.ssh/tunnel_dmx
```

**2. NOPASSWD sudo for the two systemctl commands `scripts/sync.sh` invokes.** On
the Pi:

```sh
sudo tee /etc/sudoers.d/tunnel-dmx-deploy >/dev/null <<'EOF'
pi ALL=(root) NOPASSWD: /bin/systemctl restart tunnel-dmx, /bin/systemctl is-active tunnel-dmx
EOF
sudo chmod 440 /etc/sudoers.d/tunnel-dmx-deploy
```

This grants the `pi` user the right to run *only* those two commands without
a password. Anything else still requires sudo as normal.

`scripts/sync.sh` uses `sudo -n` (non-interactive) for these calls, so if the
sudoers rule is missing it will fail loudly rather than hang waiting for a
password prompt that the script can't see.

## 8. Updating code on a deployed Pi

Join the `TunnelDMX` WiFi, then from your laptop:

```sh
./scripts/sync.sh
```

That syncs the allowlisted files and restarts `tunnel-dmx`. Override the
default target with env vars if needed:

```sh
PI_HOST=pi@192.168.50.1 PI_PATH=/home/pi/runawaytrain ./scripts/sync.sh
```

Or on the Pi via git:

```sh
cd /home/pi/runawaytrain
git pull
sudo systemctl restart tunnel-dmx
```

## 9. Useful commands (on the Pi)

```sh
# Live logs
sudo journalctl -u tunnel-dmx -f

# Service control
sudo systemctl status tunnel-dmx
sudo systemctl restart tunnel-dmx
sudo systemctl stop tunnel-dmx

# Confirm DMX adapter is detected
ls -l /dev/ttyUSB0
dmesg | grep -i ftdi

# Confirm hotspot is up
nmcli connection show TunnelDMX
nmcli device status
sudo systemctl status dnsmasq
iw dev wlan0 info

# Re-provision Python deps (rare)
cd /home/pi/runawaytrain
sudo -u pi uv sync
sudo systemctl restart tunnel-dmx
```

## 10. Troubleshooting

- **`/dev/ttyUSB0` missing**: unplug/replug the Enttec adapter, check `dmesg`.
  The service runs in demo mode (no DMX output) if the port is missing.
- **Hotspot not appearing**: `nmcli connection show TunnelDMX --active` —
  if missing, `sudo nmcli connection up TunnelDMX`. Common cause is WiFi
  country not set; run `sudo raspi-config` -> Localisation -> WLAN Country.
- **dnsmasq fails to start**: it must bind to `wlan0` after NetworkManager
  brings up the static IP. Check `sudo systemctl status dnsmasq`. The install
  script adds an `After=NetworkManager-wait-online.service` override; if you
  edited it, make sure that ordering is preserved.
- **Web UI unreachable**: confirm phone is on `TunnelDMX` SSID, then
  `ping 192.168.50.1`. If that works but the page does not load,
  `sudo systemctl status tunnel-dmx`.
- **Lights show "no signal"**: the DMX thread may not be running. Check logs.
  Frames must be sent continuously, even when the chase is stopped.
- **Chase auto-started after power cut**: this is intentional. `running`
  defaults to `True` on boot so the tunnel comes back up after a generator
  cycle without operator intervention. Press Stop in the UI if you do not
  want it running.

## 11. Pre-venue checklist

- [ ] Hotspot password changed from default
- [ ] Connected to `TunnelDMX` and loaded the UI from a phone
- [ ] DMX adapter recognised (`/dev/ttyUSB0` present)
- [ ] Test fixture responds to a manual Step
- [ ] Service survives a power-cycle (pull the plug, confirm it comes back)
- [ ] `state.json` persists settings across reboot (excluding `running`)
- [ ] 120Ω terminator fitted on the last fixture
