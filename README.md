# Tunnel DMX Chase Controller

Headless DMX chase controller for a 120m railway tunnel. Runs on a Raspberry
Pi 4B at boot, serves a phone-optimised web UI over a self-hosted WiFi
hotspot, and persists all settings across reboots.

## Hardware wiring

```
  Pi 4B                              PAR fixtures (RGBW, 4 ch each)
  +---------+      USB              +---------+   +---------+
  |         | <===> Enttec Open === | Fix 1   |==>| Fix 2   |==> ... ==> [120Ω term]
  | wlan0   |       DMX USB         | ch 1-4  |   | ch 5-8  |
  +---------+                       +---------+   +---------+
       |
       +-- self-hosted AP "TunnelDMX" -- phone connects here
```

Generator powers everything from one end. Keep DMX data cable physically
separated from mains by at least 50mm. 120Ω terminator on the last fixture.

## DMX channel map

| Fixture | R   | G   | B   | W   |
|---------|-----|-----|-----|-----|
| 1       | 1   | 2   | 3   | 4   |
| 2       | 5   | 6   | 7   | 8   |
| 3       | 9   | 10  | 11  | 12  |
| ...     | ... | ... | ... | ... |
| 16      | 61  | 62  | 63  | 64  |

## First-time setup

See [docs/PI_SETUP.md](docs/PI_SETUP.md). Summary:

1. Flash Raspberry Pi OS Lite, enable SSH, set hostname `tunneldmx`.
2. From your laptop: `PI_HOST=pi@tunneldmx.local ./scripts/sync.sh --no-restart`
3. SSH in, edit `HOTSPOT_PASS` in `scripts/install.sh`, run `sudo bash scripts/install.sh`.
4. Reboot. Join WiFi `TunnelDMX`, browse to `http://dmx.local`.

## How to connect

- WiFi SSID: `TunnelDMX`
- Password: set in `scripts/install.sh` (`HOTSPOT_PASS`)
- URL: `http://dmx.local` or `http://192.168.50.1`

## Operations

```sh
# Live logs
sudo journalctl -u tunnel-dmx -f

# Restart the service
sudo systemctl restart tunnel-dmx

# Stop / start
sudo systemctl stop tunnel-dmx
sudo systemctl start tunnel-dmx
```

## Changing defaults

Edit the constants at the top of [src/tunnel_dmx/config.py](src/tunnel_dmx/config.py):

```python
OLA_URL      = "http://127.0.0.1:9090/set_dmx"
OLA_UNIVERSE = 0
MAX_FIXTURES = 16
CHANNELS_PER = 4
STATE_FILE   = "state.json"
WEB_PORT     = 80
```

Default runtime state lives in `DEFAULT_STATE` in the same file. After a
reboot, the keys listed in `PERSISTED_KEYS` are restored from `state.json`
on top of those defaults. `running` and `blackout` are not persisted: on
startup the controller comes up `running=True` and `blackout=False`.

## Updating code on a deployed Pi

Join `TunnelDMX`, then from your laptop:

```sh
./scripts/sync.sh
```

This rsyncs the allowlisted files (see `INCLUDES` in [scripts/sync.sh](scripts/sync.sh))
and restarts the service.
