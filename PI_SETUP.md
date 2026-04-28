# Raspberry Pi Setup & Deployment Guide

End-to-end instructions for preparing a Raspberry Pi 4B and deploying the
Tunnel DMX Chase Controller to it.

---

## 1. Flash the SD card

1. Download Raspberry Pi Imager: https://www.raspberrypi.com/software/
2. Choose:
   - Device: Raspberry Pi 4
   - OS: Raspberry Pi OS Lite (64-bit)
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
PI_HOST=pi@tunneldmx.local ./sync.sh --no-restart
```

`sync.sh` uses an explicit allowlist (see the `INCLUDES` array at the top of
the script); add new files there as the project grows. `--no-restart` skips
the service restart, which is useful before the systemd unit is installed.

## 4. Configure the hotspot password

On the Pi, edit the password variable before running the installer:

```sh
cd /home/pi/repos/runawaytrain
nano install.sh
# Change HOTSPOT_PASS="..." to your chosen password (min 8 chars)
```

## 5. Run the installer

```sh
sudo bash /home/pi/repos/runawaytrain/install.sh
```

The script will install dependencies, configure the hotspot, and enable the
systemd service. It prints a summary at the end with the SSID, password, and
URL.

Reboot to bring up the hotspot:

```sh
sudo reboot
```

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

## 8. Updating code on a deployed Pi

Join the `TunnelDMX` WiFi, then from your laptop:

```sh
./sync.sh
```

That syncs the allowlisted files and restarts `tunnel-dmx`. Override the
default target with env vars if needed:

```sh
PI_HOST=pi@192.168.50.1 PI_PATH=/home/pi/repos/runawaytrain ./sync.sh
```

Or on the Pi via git:

```sh
cd /home/pi/repos/runawaytrain
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
sudo systemctl status hostapd dnsmasq
iw dev wlan0 info
```

## 10. Troubleshooting

- **`/dev/ttyUSB0` missing**: unplug/replug the Enttec adapter, check `dmesg`.
  The service runs in demo mode (no DMX output) if the port is missing.
- **Hotspot not appearing**: `sudo systemctl status hostapd`. Common cause is
  WiFi country not set; run `sudo raspi-config` -> Localisation -> WLAN Country.
- **Web UI unreachable**: confirm phone is on `TunnelDMX` SSID, then
  `ping 192.168.50.1`. If that works but the page does not load,
  `sudo systemctl status tunnel-dmx`.
- **Lights show "no signal"**: the DMX thread may not be running. Check logs.
  Frames must be sent continuously, even when the chase is stopped.
- **Chase did not auto-start after power cut**: this is intentional. By design
  `running` is always `False` on boot for safety. Press Run in the UI.

## 11. Pre-venue checklist

- [ ] Hotspot password changed from default
- [ ] Connected to `TunnelDMX` and loaded the UI from a phone
- [ ] DMX adapter recognised (`/dev/ttyUSB0` present)
- [ ] Test fixture responds to a manual Step
- [ ] Service survives a power-cycle (pull the plug, confirm it comes back)
- [ ] `state.json` persists settings across reboot (excluding `running`)
- [ ] 120Ω terminator fitted on the last fixture
