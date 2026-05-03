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
├── src/tunnel_dmx/
│   ├── __init__.py
│   ├── __main__.py           # `python -m tunnel_dmx` entry point
│   ├── chase.py              # Flask app, routes, waitress entry (main())
│   ├── controller.py         # State, sequencing, persistence, DMX frame loop
│   ├── config.py             # Constants and DEFAULT_STATE
│   ├── dmx.py                # OLA HTTP client
│   ├── patterns.py           # build_sequence, hsv_to_rgb
│   ├── templates/
│   │   ├── index.html        # Phone UI
│   │   └── help.html         # Renders help/LIGHTS.md as HTML
│   ├── static/               # CSS + JS for the UI
│   └── help/
│       └── LIGHTS.md         # Operator-facing fixture/UI guide
├── scripts/
│   ├── install.sh            # One-shot Pi setup script
│   ├── sync.sh               # Laptop -> Pi rsync helper
│   ├── apsetup.sh            # Hotspot reconfiguration helper
│   └── ci.sh                 # Local sanity checks
├── docs/
│   ├── PI_SETUP.md           # Pi setup and deployment guide
│   ├── LOGS.md               # Logging / debugging cheatsheet
│   └── spec.md               # This file
├── tunnel-dmx.service        # systemd unit file
├── pyproject.toml            # uv project definition + dependencies
├── state.json                # Auto-created at runtime, do not commit
└── README.md                 # Setup and usage documentation
```

Deployed location on the Pi: `/home/pi/runawaytrain/`. The package is
installed editable into the project's `.venv` by `uv sync` and exposed as
the `tunnel-dmx` console script (see `[project.scripts]` in
`pyproject.toml`).

---

## Application — detailed spec

The Python source lives under `src/tunnel_dmx/`. The Flask routes and the
waitress server are in `chase.py`; show state and the DMX frame loop are
in `controller.py`; constants live in `config.py`.

### Configuration block (`config.py`, easy to edit)

```python
OLA_URL      = "http://127.0.0.1:9090/set_dmx"
OLA_UNIVERSE = 0
MAX_FIXTURES = 16
CHANNELS_PER = 4
STATE_FILE   = "state.json"
WEB_PORT     = 80
```

### Default state

```python
DEFAULT_STATE = {
    "running":     True,
    "blackout":    False,
    "pattern":     "single",
    "bpm":         60,
    "fixtures":    8,
    "color":       [255, 140, 40, 0],   # R, G, B, W — warm white
    "dimmer":      255,
    "cycle_speed": 0,
    "hue_start":   0,
    "hue_width":   100,
}
```

### State persistence

- On startup: read `state.json` if it exists, merge into DEFAULT_STATE
  (so new keys added in future versions fall back to defaults gracefully)
- On any change via API: a debounced background thread writes the keys
  listed in `PERSISTED_KEYS` to `state.json` (at most once per ~1.5s)
- `PERSISTED_KEYS` excludes `running` and `blackout`: on startup the
  controller always comes up `running=True`, `blackout=False`. The tunnel
  resumes lighting on its own after a generator power-cycle.
- Runtime-only fields (`step`, `active`, `sequence`) are never persisted
- If `state.json` is missing or corrupt: log a warning, continue with defaults
- An `atexit` flush forces a synchronous final write on clean shutdown

### DMX layer (OLA)

The app no longer talks to the Enttec adapter directly. It POSTs frames
to a local OLA daemon (`olad`) over its HTTP API at `OLA_URL`, and OLA
owns the USB device, BREAK timing, and DMX framing. The systemd unit
declares `Wants=olad.service` so OLA is always up first.

The DMX status string surfaced in `/api/status` (`dmx`) is one of
`ok`, `demo` (no successful POST since startup), `error` (recent POST
failed), or `unpatched` (olad is up but no port is patched to the
universe).

### DMX thread

- `controller.dmx_loop` runs as a daemon thread alongside the web server
- Protected shared state via `threading.Lock()`
- Steps the chase based on BPM; sends a frame every ~33ms while running
  (smooth colour cycling) and every 50ms while stopped (blank frames keep
  fixtures from showing "no signal")
- On `pattern == "random"`, the sequence is reshuffled every time the
  step counter wraps so the random walk keeps moving
- If OLA is unreachable: log and continue in demo mode (no output)
- Do not crash if a POST fails mid-run — log and continue

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

### HTTP API

All endpoints return JSON. POST endpoints use `request.get_json(force=True)`.

| Method | Endpoint      | Body (JSON)                         | Effect |
|--------|---------------|-------------------------------------|--------|
| GET    | /             | —                                   | Serve index.html (phone UI) |
| GET    | /help         | —                                   | Render `help/LIGHTS.md` as HTML |
| GET    | /api/status   | —                                   | Return full state snapshot |
| GET    | /api/stream   | —                                   | Server-Sent Events stream of state changes (heartbeat every 2s) |
| POST   | /api/run      | —                                   | Start chase, rebuild sequence, reset step to 0 |
| POST   | /api/stop     | —                                   | Stop chase, blank active fixtures |
| POST   | /api/step     | —                                   | Advance one step manually (only when stopped) |
| POST   | /api/blackout | —                                   | Toggle blackout on/off |
| POST   | /api/set      | Any subset of configurable fields   | Update one or more settings, rebuild sequence if pattern/fixtures changed |

`/api/status` response shape:
```json
{
  "running":     true,
  "blackout":    false,
  "pattern":     "single",
  "bpm":         60,
  "fixtures":    8,
  "color":       [255, 140, 40, 0],
  "dimmer":      255,
  "cycle_speed": 0,
  "hue_start":   0,
  "hue_width":   100,
  "step":        3,
  "seq_len":     8,
  "active":      [3],
  "dmx":         "ok",
  "dmx_target":  "http://127.0.0.1:9090/set_dmx u=0",
  "effective_color": [255, 140, 40, 0]
}
```

`effective_color` is the RGBW the controller would emit right now: equal
to `color` when `cycle_speed == 0`, otherwise the cycle's current sample
from the hue band (with W passed through unchanged).

`/api/set` accepts any combination of:
```json
{
  "bpm":         60,
  "fixtures":    8,
  "dimmer":      255,
  "cycle_speed": 0,
  "hue_start":   0,
  "hue_width":   100,
  "pattern":     "single",
  "color":       [255, 140, 40, 0]
}
```

Validation ranges:
- `bpm`: 10–400
- `fixtures`: 1–MAX_FIXTURES
- `dimmer`: 0–255
- `cycle_speed`: 0–60 (0 disables the hue cycle)
- `hue_start`: 0–100
- `hue_width`: 0–100
- `color`: array of 4 ints, each 0–255. Editing R/G/B forces
  `cycle_speed` back to 0 (manual colour overrides the cycle)

### Startup sequence

1. Construct `Controller`: load state from JSON (or defaults), force
   `running=True` and `blackout=False`, build initial sequence
2. Probe olad (`DMXOutput.check_patched()`)
3. Start the DMX daemon thread and the persistence daemon thread
4. Register `atexit` flush
5. Start waitress on `0.0.0.0:WEB_PORT` (8 threads, generous channel
   timeout to keep SSE clients alive)

---

## templates/index.html — detailed spec

(Lives at `src/tunnel_dmx/templates/index.html`.)

Single-file, no external dependencies, no framework. Vanilla JS only.
Must work on a phone browser over local WiFi with no internet access
(so no CDN imports).

### Layout (top to bottom)

1. **Header bar** — title "TUNNEL DMX", running/stopped status dot + label
2. **PAR grid** — 16 circles in a row showing fixture states.
   Active = lit amber, inactive (beyond fixture count) = dimmed/greyed out,
   off = dark. Updates every 500ms via status poll.
3. **Pattern selector** — 8 buttons in a 4×2 grid. Selected pattern highlighted.
4. **Sliders** — BPM, Fixtures, Dimmer. Each shows current value.
   Debounced before sending to API to avoid flooding.
5. **Colour controls** — Cycle (hue cycle speed), Hue Start, Hue Width,
   plus R, G, B, W sliders with numeric readout each. Editing R/G/B
   sends `cycle_speed=0` so the manual colour wins. Also debounced.
6. **Transport row** — Run (green accent), Step, Stop, Blackout (red when active)
7. **Step counter** — small text: "step 3 / 8"
8. **Help link** — `?` icon in the header opens `/help`.

### Behaviour

- Subscribe to `/api/stream` (SSE) for state updates; fall back to a
  status poll if the stream is unavailable
- On every event, update all UI elements to reflect server state
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
After=network.target olad.service
Wants=olad.service

[Service]
ExecStart=/usr/local/bin/uv run --no-sync tunnel-dmx
WorkingDirectory=/home/pi/runawaytrain
Restart=always
RestartSec=5
User=pi
Group=pi
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes
Environment=UV_PROJECT_ENVIRONMENT=/home/pi/runawaytrain/.venv
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Python is managed by `uv` rather than system pip. The systemd unit invokes
`uv run --no-sync tunnel-dmx` (the console script declared in
`pyproject.toml`) so it does not re-resolve dependencies on every restart;
`UV_PROJECT_ENVIRONMENT` pins the venv path. The service runs as the
unprivileged `pi` user and gets `CAP_NET_BIND_SERVICE` so it can bind to
port 80 without being root.

---

## scripts/install.sh

One-shot script, run once as root on a fresh Raspberry Pi OS Lite (Trixie)
install.

Steps it performs:
1. `apt-get install` — `network-manager dnsmasq avahi-daemon ola curl ca-certificates`
2. Blacklist the kernel `ftdi_sio` driver and unload it now, so OLA's
   FTDI USB DMX plugin (libftdi) can claim the Enttec adapter.
3. Enable `olad`, disable competing OLA USB plugins (Serial USB, Enttec
   Open DMX, StageProfi), enable plugin 13 (FTDI USB DMX), and patch the
   FTDI device's output port to universe 0 if the adapter is plugged in.
4. Install `uv` to `/usr/local/bin` (via the official installer) if not
   already present.
5. Run `uv sync` as the `pi` user inside the project directory to
   provision `.venv` from `pyproject.toml`.
6. Configure NetworkManager to bring `wlan0` up as an AP:
   - SSID: `TunnelDMX`
   - WPA2 password: defined as variable at top of script (`HOTSPOT_PASS`)
   - Channel 6, 2.4GHz, static IP `192.168.50.1/24`
7. Disable autoconnect on any other wifi profile bound to `wlan0` so the
   AP profile owns the radio.
8. Configure `/etc/dnsmasq.conf`:
   - DHCP range: `192.168.50.10` to `192.168.50.50`
   - DNS alias: `dmx.local` -> `192.168.50.1`
9. Add a systemd drop-in so dnsmasq waits for NetworkManager to bring
   the static IP up before binding.
10. Copy `tunnel-dmx.service` to `/etc/systemd/system/` and
    `systemctl enable` for `NetworkManager`, `dnsmasq`, `tunnel-dmx`.
11. Print summary: WiFi name, password, URL to connect to.

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
    "markdown>=3.5",
    "waitress>=3.0",
]

[project.scripts]
tunnel-dmx = "tunnel_dmx.chase:main"

[build-system]
requires = ["uv_build>=0.5,<0.9"]
build-backend = "uv_build"
```

uv is the single source of truth for environment provisioning. The
`tunnel-dmx` console script is what the systemd unit invokes; flask is
fronted by waitress (production WSGI server) rather than Flask's dev
server. There is no longer a direct `pyserial` dependency: DMX output
goes via the system `olad` daemon over HTTP.

---

## README.md and PI_SETUP.md

`README.md` is the project overview and covers:

- Hardware wiring diagram (ASCII)
- DMX channel map for RGBW fixtures
- How to connect (WiFi name, URL)
- How to check logs / restart the service
- How to change default settings (constants in `src/tunnel_dmx/config.py`)
- Pointer to `docs/PI_SETUP.md` for setup details
- Note on the 120m cable run: keep DMX data cable physically separated
  from mains by at least 50mm, use 120Ω terminator on last fixture

`docs/PI_SETUP.md` is the operator-facing setup and deployment guide and covers:

- Flashing Raspberry Pi OS Lite via Raspberry Pi Imager
- First boot, SSH, system update
- First-time deploy via `./scripts/sync.sh --no-restart`
- Editing `HOTSPOT_PASS` and running `scripts/install.sh`
- Verification, post-deployment SSH, code updates via `./scripts/sync.sh`
- Troubleshooting and pre-venue checklist

---

## Key constraints / things not to get wrong

- `running` defaults to `True` on boot so the tunnel auto-resumes after a
  generator power-cycle. `running` and `blackout` are deliberately not
  in `PERSISTED_KEYS`: the operator's last on/off choice is not what we
  want to remember across power loss.
- Only one DMX thread may ever be running. Production uses waitress (no
  reloader); avoid Flask's dev server with the auto-reloader, which would
  spawn a second worker process and a second DMX loop.
- The DMX thread must keep sending frames even when stopped (blank frames),
  otherwise some fixtures will show a "no signal" error state
- `build_sequence()` must be called whenever `pattern` or `fixtures` changes
- All state mutations must happen inside `threading.Lock()`
- The web UI must work with no internet (no CDN, no Google Fonts, no external JS)
- Port 80 is granted to the non-root `pi` user via
  `AmbientCapabilities=CAP_NET_BIND_SERVICE` in the systemd unit — the
  service does not run as root.

---

## Future expansion

### DMX transport

The app currently sends frames to OLA via its HTTP REST API on
`localhost:9090`. OLA also exposes the same data over other transports;
none are required for the current chase rate (1–5 frames/sec) but each
opens specific capabilities:

- **Native RPC (protobuf over TCP, port 9010).** Persistent connection,
  no per-request overhead. Required if the app ever wants to push
  smooth fades at 30+ FPS. Python access via the `python3-ola` Debian
  package (sits outside the uv venv, so would need `--system-site-packages`
  or vendoring).
- **sACN (E1.31) input on UDP/5568.** Lets an external lighting console
  drive the same universe over WiFi as a backup or override. Patch the
  sACN input to universe 0 alongside the chase app and OLA HTQ-merges
  the streams.
- **Art-Net input on UDP/6454.** Same idea, older protocol. Useful if
  the available console only speaks Art-Net.
- **OSC input.** Lets a phone running TouchOSC (or similar) drive
  individual channels for live tweaking.

### Other

- **RDM-capable adapter.** Replace the Enttec Open DMX USB with an
  Enttec DMX USB Pro (or similar) to gain RDM, which would let the app
  query fixture state and addresses over the same XLR cable. Requires
  RDM-capable fixtures; the Equinox MaxiPar Quad is not.
- **Audio reactivity.** Pipe a USB microphone's audio level into a new
  `pattern: audio` mode that scales dimmer or step rate to amplitude.
- **Schedules.** Persist a list of "at HH:MM, switch to pattern X"
  rules, served from the same Flask app. Useful for unattended runs.