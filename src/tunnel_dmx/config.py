"""Constants for the tunnel DMX controller."""

from __future__ import annotations

from typing import Any


OLA_URL = "http://127.0.0.1:9090/set_dmx"
OLA_UNIVERSE = 0
MAX_FIXTURES = 16
CHANNELS_PER = 4
STATE_FILE = "state.json"
WEB_PORT = 80

DMX_UNIVERSE_SIZE = 512
BLANK_FRAME_INTERVAL = 0.05
FRAME_INTERVAL = 1.0 / 30.0  # 30 fps frame pump for smooth colour cycling

CYCLE_SPEED_MAX = 60  # rotations per minute at max

PATTERNS = (
    "single", "double", "triple", "bounce",
    "odd_even", "build", "random", "all",
)

DEFAULT_STATE: dict[str, Any] = {
    "running": True,
    "blackout": False,
    "pattern": "single",
    "bpm": 60,
    "fixtures": 8,
    "color": [255, 140, 40, 0],
    "dimmer": 255,
    "cycle_speed": 0,
    "hue_start": 0,
    "hue_width": 100,
}

PERSISTED_KEYS = ("pattern", "bpm", "fixtures", "color", "dimmer",
                  "cycle_speed", "hue_start", "hue_width")
