# Logs and debugging on the Pi

All commands below assume you are SSH'd into the Pi (`ssh pi@192.168.50.1`).
Add `sudo` only where shown — most read-only journal queries don't need it
on Trixie, but `sudo` never hurts.

---

## tunnel-dmx (the app)

### Live tail

```sh
sudo journalctl -u tunnel-dmx -f
```

Press Ctrl-C to stop. Watch this while clicking around the UI to see every
request and DMX event.

### Last N lines, then follow

```sh
sudo journalctl -u tunnel-dmx -n 200 -f
```

### Logs since the last boot

```sh
sudo journalctl -u tunnel-dmx -b
```

### Errors and warnings only

```sh
sudo journalctl -u tunnel-dmx -p warning -b
```

Priority levels (lowest to highest noise): `emerg`, `alert`, `crit`, `err`,
`warning`, `notice`, `info`, `debug`. The level filter is *minimum*
severity, so `-p warning` shows warning and above.

### Time-windowed

```sh
sudo journalctl -u tunnel-dmx --since "10 min ago"
sudo journalctl -u tunnel-dmx --since "today"
sudo journalctl -u tunnel-dmx --since "2026-05-01 14:00" --until "2026-05-01 15:00"
```

### Filter by content

```sh
sudo journalctl -u tunnel-dmx -b | grep -i dmx
sudo journalctl -u tunnel-dmx -b | grep -i "write failed"
```

### Service status (state, last exit code, last few log lines)

```sh
systemctl status tunnel-dmx
```

---

## Run the app manually (best for development)

When you want immediate feedback and the ability to Ctrl-C:

```sh
sudo systemctl stop tunnel-dmx
cd /home/pi/runawaytrain
sudo uv run --no-sync tunnel-dmx
# Ctrl-C when done
sudo systemctl start tunnel-dmx
```

Stdout and stderr go straight to your terminal — every request, every DMX
error, every uncaught exception is visible immediately.

### Force unbuffered output

```sh
sudo PYTHONUNBUFFERED=1 uv run --no-sync tunnel-dmx
```

### Override the port (useful for non-root local testing)

```sh
sudo WEB_PORT=8080 uv run --no-sync tunnel-dmx
```

(Only works if the app reads `WEB_PORT` from the env. The current code
hardcodes 80 in `config.py`; if you want this, ask.)

---

## Network stack

If the AP, DHCP, or DNS misbehaves.

### NetworkManager (the AP itself)

```sh
sudo journalctl -u NetworkManager -f
sudo journalctl -u NetworkManager -b | grep -iE 'wlan0|tunneldmx|ap mode'

nmcli -f NAME,TYPE,DEVICE,STATE connection show
nmcli -f ipv4.method,ipv4.addresses connection show TunnelDMX
iw dev wlan0 info       # should show "type AP" and ssid TunnelDMX
iw dev wlan0 station dump   # MAC of every connected client
```

### dnsmasq (DHCP + dmx.local DNS alias)

```sh
sudo journalctl -u dnsmasq -f
sudo systemctl status dnsmasq
```

Watch live as a phone joins; you should see `DHCPDISCOVER` -> `DHCPOFFER`
-> `DHCPREQUEST` -> `DHCPACK` for the phone's MAC.

### Active DHCP leases

```sh
cat /var/lib/misc/dnsmasq.leases
```

---

## DMX (OLA + Enttec Open DMX USB)

The app sends DMX frames to a local OLA daemon (`olad`), which owns the
USB adapter and handles BREAK timing properly. So there are two layers
to check: USB-level (does Linux see the adapter?) and OLA-level (does
olad see it, is it patched to a universe?).

### USB layer

```sh
lsusb | grep -i 'future\|ftdi'
ls -l /dev/ttyUSB0
dmesg | grep -i ftdi | tail
```

### OLA layer

```sh
# olad service state and logs
sudo systemctl status olad
sudo journalctl -u olad -f

# Devices and ports OLA has discovered
ola_dev_info

# Universes and patches (port -> universe mappings)
ola_uni_info
ola_patch_info

# Plugin state
ola_plugin_info
```

### Sending DMX directly via OLA (independent of the app)

Useful to confirm OLA + adapter + cable + fixture are all wired correctly
without involving the app:

```sh
# Light fixture 1 solid red for 5 seconds
ola_streaming_client --universe 0 --dmx '255,0,0,0' &
sleep 5; kill %1

# Or interactive (type values, Enter to send, Ctrl-D to exit)
ola_streaming_client --universe 0
```

If `ola_streaming_client` lights the lamp but the app's UI doesn't,
the app is at fault. If neither works, check `ola_uni_info` — the
universe must be patched.

### Patching the Open DMX device

`scripts/install.sh` does this automatically if the adapter was plugged
in at install time. If you plugged in afterwards:

```sh
ola_dev_info                          # find the FTDI / Open DMX device id
ola_patch -d <DEVICE_ID> -p 0 -u 0    # patch port 0 of that device to universe 0
```

The patch persists across reboots.

### Common gotchas (resolved by scripts/install.sh, listed here for fresh diagnosis)

- **Wrong OLA plugin claims the adapter.** OLA ships several USB plugins that
  fight over `/dev/ttyUSB*`: Serial USB (id 5), Enttec Open DMX (id 6),
  StageProfi (id 8), FTDI USB DMX (id 13). Only id 13 produces correct DMX
  framing for an Enttec Open DMX adapter on Linux. Disable the others.
- **`ftdi_sio` kernel driver blocks libftdi.** If `/dev/ttyUSB0` exists,
  the kernel has the chip and OLA's FTDI plugin can't claim it. Blacklist
  the module: `echo blacklist ftdi_sio | sudo tee /etc/modprobe.d/blacklist-ftdi.conf`
  and reboot, or `sudo rmmod ftdi_sio` for an immediate test.
- **Universe not patched, or wrong port id.** The FTDI plugin reports its
  output as `port 1`, not `port 0`. Always read the actual port number from
  `ola_dev_info` before running `ola_patch`. Confirm with `ola_uni_info`:
  empty table = nothing patched = no DMX out.

### App's view of OLA

The web UI header shows the result of the app's own HTTP POSTs to olad:

- `DMX OK` — POST returned 200; OLA accepted the frame.
- `DEMO`   — never managed a successful POST since startup (olad not
  running, or refusing connections).
- `DMX ERR`— recent POST failed (transient OLA failure, or olad died).

---

## System-wide

### Everything since the last boot

```sh
sudo journalctl -b
```

### Boot-time problems / kernel messages

```sh
sudo dmesg | tail -50
sudo journalctl -b -k        # kernel messages this boot
```

### Disk and memory

```sh
df -h
free -h
```

### What's listening on which port

```sh
sudo ss -ltnp
```

Expect waitress on `0.0.0.0:80` and dnsmasq on `0.0.0.0:53`/`67`.

---

## From your laptop without SSHing in

Useful one-liners while you keep working in another terminal.

```sh
# Live app log
ssh pi@192.168.50.1 'sudo journalctl -u tunnel-dmx -f'

# Service state at a glance
ssh pi@192.168.50.1 'systemctl status tunnel-dmx --no-pager'

# Last 100 lines on demand
ssh pi@192.168.50.1 'sudo journalctl -u tunnel-dmx -n 100 --no-pager'
```

---

## Cheat sheet

| Want to                          | Command                                                |
|----------------------------------|--------------------------------------------------------|
| Watch app live                   | `sudo journalctl -u tunnel-dmx -f`                     |
| Last boot only                   | `sudo journalctl -u tunnel-dmx -b`                     |
| Errors only                      | `sudo journalctl -u tunnel-dmx -p warning -b`          |
| Service state                    | `systemctl status tunnel-dmx`                          |
| Run interactively                | `sudo systemctl stop tunnel-dmx && sudo uv run --no-sync tunnel-dmx` |
| Confirm DMX adapter              | `ls -l /dev/ttyUSB0`                                   |
| Confirm AP up                    | `iw dev wlan0 info`                                    |
| See connected phones             | `iw dev wlan0 station dump`                            |
| Watch DHCP exchanges             | `sudo journalctl -u dnsmasq -f`                        |
| What's listening                 | `sudo ss -ltnp`                                        |
