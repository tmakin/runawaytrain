# Tunnel DMX Chase Controller — Project Spec

## Overview

Build a headless DMX lighting chase controller that runs on a Raspberry Pi 4B
at boot, serves a phone-optimised web UI over a self-hosted WiFi hotspot, and
persists all settings across reboots via a JSON state file.

The installation is a 120m railway tunnel lit with RGBW PAR cans powered from
a generator at one end only. The Pi must recover gracefully from unexpected
power loss (generator cuts out and restarts) and resume the last-known state
with no human intervention.

---

## Hardware

- Raspberry Pi 4B (any RAM)
- Enttec Open DMX USB adapter (`/dev/ttyUSB0`)
- Up to 16 × RGBW PAR fixtures in DMX daisy-chain
- 120Ω terminator on the last fixture
- No monitor, keyboard, or mouse ever attached

## DMX layout

- 4 channels per fixture (R, G, B, W)
- Fixture 1: ch 1–4, Fixture 2: ch 5–8, etc.
- Standard DMX512 framing: 250000 baud, 8 data bits, 2 stop bits, no parity
- Break + MAB before each frame, slot 0 = start code 0x00

---

## Project structure

```
runawaytrain/
├── chase.py                  # Main application
├── templates/
│   └── index.html            # Web UI (Jinja2 template)
├── static/                   # Empty, reserved for future assets
├── tunnel-dmx.service        # systemd unit file
├── install.sh                # One-shot Pi setup script
├── pyproject.toml            # uv project definition + dependencies
├── requirements.txt          # Mirror of deps for reference
├── sync.sh                   # Laptop -> Pi rsync helper
├── PI_SETUP.md               # Pi setup and deployment guide
├── state.json                # Auto-created at runtime, do not commit
└── README.md                 # Setup and usage documentation
```

Deployed location on the Pi: `/home/pi/runawaytrain/`.

---

## chase.py — detailed spec

### Configuration block (top of file, easy to edit)

```python
DMX_PORT     = "/dev/ttyUSB0"
MAX_FIXTURES = 16
CHANNELS_PER = 4
STATE_FILE   = "state.json"
WEB_PORT     = 80
```

### Default state

```python
DEFAULT_STATE = {
    "running":   False,
    "blackout":  False,
    "pattern":   "single",
    "bpm":       60,
    "step_size": 1,
    "fixtures":  8,
    "color":     [255, 140, 40, 0],   # R, G, B, W — warm white
    "dimmer":    255,
}
```

### State persistence

- On startup: read `state.json` if it exists, merge into DEFAULT_STATE
  (so new keys added in future versions fall back to defaults gracefully)
- On any change via API: write only the DEFAULT_STATE keys to `state.json`
- Runtime-only fields (`step`, `active`, `sequence`) are never persisted
- If `state.json` is missing or corrupt: log a warning, continue with defaults
- `running` is persisted as `False` always — operator must manually restart
  the chase after a reboot (safety: lights don't unexpectedly start in a tunnel)

### DMX thread

- Runs as a daemon thread alongside Flask
- Protected shared state via `threading.Lock()`
- When running: send a DMX frame, sleep `60 / bpm` seconds, advance step
- When stopped: send a blank frame (all zeros) every 50ms to keep DMX alive
- If serial port fails to open: log error, continue in demo mode (no output)
- Do not crash if serial write fails mid-run — log and continue

### Chase patterns

All patterns take `n` (number of active fixtures) and return a list of steps,
where each step is a list of zero-indexed fixture indices that should be ON.

| Pattern  | Description |
|----------|-------------|
| single   | One fixture at a time, steps forward |
| double   | Two adjacent fixtures, wraps around |
| triple   | Three adjacent fixtures, wraps around |
| bounce   | Single fixture travels forward then back (ping-pong) |
| odd_even | Alternates all odd-indexed and all even-indexed fixtures |
| build    | Accumulates fixtures one by one, then strips back down |
| random   | Random single fixture each step (regenerated each time pattern is selected) |
| all      | All fixtures on simultaneously (single step sequence) |

### Flask API

All endpoints return JSON. POST endpoints with no body still require
`Content-Type: application/json` or use `request.get_json(force=True)`.

| Method | Endpoint      | Body (JSON)                         | Effect |
|--------|---------------|-------------------------------------|--------|
| GET    | /             | —                                   | Serve index.html |
| GET    | /api/status   | —                                   | Return full state snapshot |
| POST   | /api/run      | —                                   | Start chase, rebuild sequence, reset step to 0, save state |
| POST   | /api/stop     | —                                   | Stop chase, blank active fixtures, save state |
| POST   | /api/step     | —                                   | Advance one step manually (only when stopped) |
| POST   | /api/blackout | —                                   | Toggle blackout on/off, save state |
| POST   | /api/set      | Any subset of configurable fields   | Update one or more settings, rebuild sequence if pattern/fixtures changed, save state |

`/api/status` response shape:
```json
{
  "running":   false,
  "blackout":  false,
  "pattern":   "single",
  "bpm":       60,
  "step_size": 1,
  "fixtures":  8,
  "color":     [255, 140, 40, 0],
  "dimmer":    255,
  "step":      3,
  "seq_len":   8,
  "active":    [3]
}
```

`/api/set` accepts any combination of:
```json
{
  "bpm":       60,
  "step_size": 1,
  "fixtures":  8,
  "dimmer":    255,
  "pattern":   "single",
  "color":     [255, 140, 40, 0]
}
```

Validation ranges:
- `bpm`: 10–300
- `step_size`: 1–8
- `fixtures`: 1–MAX_FIXTURES
- `dimmer`: 0–255
- `color`: array of 4 ints, each 0–255

### Startup sequence

1. Load state from JSON (or defaults)
2. Build initial sequence from loaded pattern + fixtures
3. Start DMX daemon thread
4. Start Flask on `0.0.0.0:WEB_PORT`

---

## templates/index.html — detailed spec

Single-file, no external dependencies, no framework. Vanilla JS only.
Must work on a phone browser over local WiFi with no internet access
(so no CDN imports).

### Layout (top to bottom)

1. **Header bar** — title "TUNNEL DMX", running/stopped status dot + label
2. **PAR grid** — 16 circles in a row showing fixture states.
   Active = lit amber, inactive (beyond fixture count) = dimmed/greyed out,
   off = dark. Updates every 500ms via status poll.
3. **Pattern selector** — 8 buttons in a 4×2 grid. Selected pattern highlighted.
4. **Sliders** — BPM, Step size, Fixtures, Dimmer. Each shows current value.
   Debounced 150ms before sending to API to avoid flooding.
5. **Colour controls** — 4 sliders (R, G, B, W) with numeric readout each.
   Also debounced.
6. **Transport row** — Run (green accent), Step, Stop, Blackout (red when active)
7. **Step counter** — small text: "step 3 / 8"

### Behaviour

- Poll `/api/status` every 500ms
- On poll response, update all UI elements to reflect server state
- Do not update a slider that the user is currently dragging
  (check `document.activeElement`)
- All API calls are fire-and-forget (no await on UI interactions)
- No page reload ever needed
- Colour scheme: dark background (#0e0e0e), amber accents (#e8a020),
  monospace font, compact layout optimised for ~375px wide phone screen

---

## tunnel-dmx.service

```ini
[Unit]
Description=Tunnel DMX Chase Controller
After=network.target

[Service]
ExecStart=/usr/local/bin/uv run --no-sync python chase.py
WorkingDirectory=/home/pi/runawaytrain
Restart=always
RestartSec=5
User=root
Environment=UV_PROJECT_ENVIRONMENT=/home/pi/runawaytrain/.venv
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Python is managed by `uv` rather than system pip. The systemd unit invokes
`uv run --no-sync` so it does not re-resolve dependencies on every restart;
`UV_PROJECT_ENVIRONMENT` pins the venv path so it works under `User=root`.

---

## install.sh

One-shot script, run once as root on a fresh Raspberry Pi OS Lite install.

Steps it must perform:
1. `apt-get install` — `hostapd dnsmasq avahi-daemon curl ca-certificates`
2. Install `uv` to `/usr/local/bin` (via the official installer script) if
   not already present.
3. Run `uv sync` as the `pi` user inside the project directory to provision
   `.venv` from `pyproject.toml`.
4. Configure `/etc/hostapd/hostapd.conf`:
   - SSID: `TunnelDMX`
   - WPA2 password: defined as variable at top of script (`HOTSPOT_PASS`)
   - Channel 6, 2.4GHz
5. Configure `/etc/dnsmasq.conf`:
   - DHCP range: `192.168.50.10` to `192.168.50.50`
   - DNS alias: `dmx.local` -> `192.168.50.1`
6. Configure static IP `192.168.50.1/24` on `wlan0` via `/etc/dhcpcd.conf`
7. Copy `tunnel-dmx.service` to `/etc/systemd/system/`
8. `systemctl enable` for `hostapd`, `dnsmasq`, `tunnel-dmx`
9. Print summary: WiFi name, password, URL to connect to

The password variable is clearly marked at the top of the script. Operator
must check (and change if needed) before running.

---

## pyproject.toml

```toml
[project]
name = "tunnel-dmx"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "flask>=2.0",
    "pyserial>=3.5",
]
```

A `requirements.txt` mirroring these deps is kept alongside for reference,
but uv is the source of truth for environment provisioning.

---

## README.md and PI_SETUP.md

`README.md` is the project overview and covers:

- Hardware wiring diagram (ASCII)
- DMX channel map for RGBW fixtures
- How to connect (WiFi name, URL)
- How to check logs / restart the service
- How to change default settings (config block in chase.py)
- Pointer to `PI_SETUP.md` for setup details
- Note on the 120m cable run: keep DMX data cable physically separated
  from mains by at least 50mm, use 120Ω terminator on last fixture

`PI_SETUP.md` is the operator-facing setup and deployment guide and covers:

- Flashing Raspberry Pi OS Lite via Raspberry Pi Imager
- First boot, SSH, system update
- First-time deploy via `./sync.sh --no-restart`
- Editing `HOTSPOT_PASS` and running `install.sh`
- Verification, post-deployment SSH, code updates via `./sync.sh`
- Troubleshooting and pre-venue checklist

---

## Key constraints / things not to get wrong

- `running` must default to `False` after reboot — do not auto-start the chase
- Flask must use `use_reloader=False` to avoid spawning a second DMX thread
- The DMX thread must keep sending frames even when stopped (blank frames),
  otherwise some fixtures will show a "no signal" error state
- `build_sequence()` must be called whenever `pattern` or `fixtures` changes
- All state mutations must happen inside `threading.Lock()`
- The web UI must work with no internet (no CDN, no Google Fonts, no external JS)
- Port 80 requires `User=root` in the systemd service, which is acceptable
  for a closed tunnel install