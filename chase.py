"""Tunnel DMX Chase Controller.

Headless DMX chase controller for a 120m railway tunnel installation.
Serves a phone-optimised web UI and drives an Enttec Open DMX USB adapter.
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from copy import deepcopy
from typing import Any

from flask import Flask, jsonify, render_template, request

try:
    import serial as _serial
    serial: Any = _serial
except ImportError:
    serial = None


DMX_PORT = "/dev/ttyUSB0"
MAX_FIXTURES = 16
CHANNELS_PER = 4
STATE_FILE = "state.json"
WEB_PORT = 80

DMX_UNIVERSE_SIZE = 512
BLANK_FRAME_INTERVAL = 0.05

DEFAULT_STATE: dict[str, Any] = {
    "running": False,
    "blackout": False,
    "pattern": "single",
    "bpm": 60,
    "step_size": 1,
    "fixtures": 8,
    "color": [255, 140, 40, 0],
    "dimmer": 255,
}

PATTERNS = (
    "single", "double", "triple", "bounce",
    "odd_even", "build", "random", "all",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("tunnel-dmx")


def build_sequence(pattern: str, n: int) -> list[list[int]]:
    """Return a list of steps; each step is a list of zero-indexed active fixtures."""
    n = max(1, int(n))
    if pattern == "single":
        return [[i] for i in range(n)]
    if pattern == "double":
        return [[i % n, (i + 1) % n] for i in range(n)]
    if pattern == "triple":
        return [[i % n, (i + 1) % n, (i + 2) % n] for i in range(n)]
    if pattern == "bounce":
        if n == 1:
            return [[0]]
        forward = [[i] for i in range(n)]
        back = [[i] for i in range(n - 2, 0, -1)]
        return forward + back
    if pattern == "odd_even":
        odds = [i for i in range(n) if i % 2 == 0]
        evens = [i for i in range(n) if i % 2 == 1]
        return [odds, evens]
    if pattern == "build":
        up = [list(range(i + 1)) for i in range(n)]
        down = [list(range(i)) for i in range(n - 1, 0, -1)]
        return up + down
    if pattern == "random":
        return [[random.randrange(n)] for _ in range(max(8, n * 2))]
    if pattern == "all":
        return [list(range(n))]
    log.warning("unknown pattern %r, falling back to 'single'", pattern)
    return [[i] for i in range(n)]


class DMXOutput:
    """Wraps the serial port and DMX framing. Demo mode if no port available."""

    def __init__(self, port: str) -> None:
        self.port = port
        self.ser: Any = None
        self._open()

    def _open(self) -> None:
        if serial is None:
            log.warning("pyserial not installed; running in demo mode")
            return
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=250000,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_TWO,
                timeout=1,
            )
            log.info("opened DMX port %s", self.port)
        except Exception as exc:
            log.error("could not open DMX port %s: %s (demo mode)", self.port, exc)
            self.ser = None

    def send(self, channels: list[int]) -> None:
        if self.ser is None:
            return
        frame = bytes([0x00]) + bytes(channels[:DMX_UNIVERSE_SIZE])
        if len(frame) < DMX_UNIVERSE_SIZE + 1:
            frame += bytes(DMX_UNIVERSE_SIZE + 1 - len(frame))
        try:
            self.ser.break_condition = True
            time.sleep(0.0001)
            self.ser.break_condition = False
            time.sleep(0.000012)
            self.ser.write(frame)
            self.ser.flush()
        except Exception as exc:
            log.error("DMX write failed: %s", exc)


class Controller:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state: dict[str, Any] = deepcopy(DEFAULT_STATE)
        self.sequence: list[list[int]] = []
        self.step: int = 0
        self.active: list[int] = []
        self.dmx = DMXOutput(DMX_PORT)
        self._load_state()
        self.state["running"] = False
        self._rebuild_sequence()

    def _load_state(self) -> None:
        if not os.path.exists(STATE_FILE):
            log.info("no state file, using defaults")
            return
        try:
            with open(STATE_FILE) as f:
                saved = json.load(f)
            for k in DEFAULT_STATE:
                if k in saved:
                    self.state[k] = saved[k]
            log.info("loaded state from %s", STATE_FILE)
        except Exception as exc:
            log.warning("could not load %s: %s (using defaults)", STATE_FILE, exc)

    def _save_state(self) -> None:
        try:
            persisted = {k: self.state[k] for k in DEFAULT_STATE}
            persisted["running"] = False
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(persisted, f, indent=2)
            os.replace(tmp, STATE_FILE)
        except Exception as exc:
            log.error("could not save state: %s", exc)

    def _rebuild_sequence(self) -> None:
        self.sequence = build_sequence(self.state["pattern"], self.state["fixtures"])
        if not self.sequence:
            self.sequence = [[]]
        self.step = 0
        self.active = list(self.sequence[0]) if self.sequence else []

    def _frame_for(self, active: list[int]) -> list[int]:
        channels = [0] * DMX_UNIVERSE_SIZE
        if self.state["blackout"]:
            return channels
        r, g, b, w = self.state["color"]
        dim = self.state["dimmer"] / 255.0
        rr = int(r * dim)
        gg = int(g * dim)
        bb = int(b * dim)
        ww = int(w * dim)
        for idx in active:
            base = idx * CHANNELS_PER
            if base + CHANNELS_PER > DMX_UNIVERSE_SIZE:
                continue
            channels[base + 0] = rr
            channels[base + 1] = gg
            channels[base + 2] = bb
            channels[base + 3] = ww
        return channels

    def dmx_loop(self) -> None:
        log.info("DMX thread started")
        while True:
            with self.lock:
                running = self.state["running"]
                bpm = self.state["bpm"]
                step_size = self.state["step_size"]
                if running and self.sequence:
                    self.active = list(self.sequence[self.step % len(self.sequence)])
                    frame = self._frame_for(self.active)
                else:
                    frame = self._frame_for([])
            self.dmx.send(frame)
            if running:
                interval = max(0.01, 60.0 / max(1, bpm))
                time.sleep(interval)
                with self.lock:
                    if self.sequence:
                        self.step = (self.step + step_size) % len(self.sequence)
            else:
                time.sleep(BLANK_FRAME_INTERVAL)

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                **{k: self.state[k] for k in DEFAULT_STATE},
                "step": self.step,
                "seq_len": len(self.sequence),
                "active": list(self.active),
            }

    def run(self) -> None:
        with self.lock:
            self.state["running"] = True
            self._rebuild_sequence()
            self._save_state()

    def stop(self) -> None:
        with self.lock:
            self.state["running"] = False
            self.active = []
            self._save_state()

    def step_once(self) -> None:
        with self.lock:
            if self.state["running"] or not self.sequence:
                return
            self.step = (self.step + self.state["step_size"]) % len(self.sequence)
            self.active = list(self.sequence[self.step])

    def toggle_blackout(self) -> None:
        with self.lock:
            self.state["blackout"] = not self.state["blackout"]
            self._save_state()

    def update(self, patch: dict[str, Any]) -> tuple[bool, str]:
        with self.lock:
            rebuild = False
            if "bpm" in patch:
                v = int(patch["bpm"])
                if not 10 <= v <= 300:
                    return False, "bpm out of range"
                self.state["bpm"] = v
            if "step_size" in patch:
                v = int(patch["step_size"])
                if not 1 <= v <= 8:
                    return False, "step_size out of range"
                self.state["step_size"] = v
            if "fixtures" in patch:
                v = int(patch["fixtures"])
                if not 1 <= v <= MAX_FIXTURES:
                    return False, "fixtures out of range"
                if v != self.state["fixtures"]:
                    self.state["fixtures"] = v
                    rebuild = True
            if "dimmer" in patch:
                v = int(patch["dimmer"])
                if not 0 <= v <= 255:
                    return False, "dimmer out of range"
                self.state["dimmer"] = v
            if "pattern" in patch:
                v = str(patch["pattern"])
                if v not in PATTERNS:
                    return False, "unknown pattern"
                if v != self.state["pattern"]:
                    self.state["pattern"] = v
                    rebuild = True
            if "color" in patch:
                c = patch["color"]
                if (not isinstance(c, list) or len(c) != 4
                        or not all(isinstance(x, int) and 0 <= x <= 255 for x in c)):
                    return False, "color must be 4 ints 0-255"
                self.state["color"] = list(c)
            if rebuild:
                self._rebuild_sequence()
            self._save_state()
        return True, "ok"


controller = Controller()
app = Flask(__name__)


@app.route("/")
def index() -> Any:
    return render_template("index.html", max_fixtures=MAX_FIXTURES, patterns=PATTERNS)


@app.route("/api/status")
def api_status() -> Any:
    return jsonify(controller.status())


@app.route("/api/run", methods=["POST"])
def api_run() -> Any:
    controller.run()
    return jsonify(controller.status())


@app.route("/api/stop", methods=["POST"])
def api_stop() -> Any:
    controller.stop()
    return jsonify(controller.status())


@app.route("/api/step", methods=["POST"])
def api_step() -> Any:
    controller.step_once()
    return jsonify(controller.status())


@app.route("/api/blackout", methods=["POST"])
def api_blackout() -> Any:
    controller.toggle_blackout()
    return jsonify(controller.status())


@app.route("/api/set", methods=["POST"])
def api_set() -> Any:
    payload = request.get_json(force=True, silent=True) or {}
    ok, msg = controller.update(payload)
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify(controller.status())


def main() -> None:
    t = threading.Thread(target=controller.dmx_loop, daemon=True)
    t.start()
    log.info("starting Flask on 0.0.0.0:%d", WEB_PORT)
    app.run(host="0.0.0.0", port=WEB_PORT, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
