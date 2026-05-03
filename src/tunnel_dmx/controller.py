"""Show controller: state, sequencing, persistence, DMX frame loop."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from copy import deepcopy
from typing import Any

from .config import (
    BLANK_FRAME_INTERVAL,
    CHANNELS_PER,
    CYCLE_SPEED_MAX,
    DEFAULT_STATE,
    DMX_UNIVERSE_SIZE,
    FRAME_INTERVAL,
    MAX_FIXTURES,
    PATTERNS,
    PERSISTED_KEYS,
    STATE_FILE,
)
from .dmx import DMXOutput
from .patterns import build_sequence, hsv_to_rgb


log = logging.getLogger("tunnel-dmx")


# Coalesce state writes so slider drags don't hammer the SD card.
SAVE_DEBOUNCE_SEC = 1.5


# (key, lo, hi, rebuild_on_change). pattern + color are validated separately.
_INT_FIELDS: tuple[tuple[str, int, int, bool], ...] = (
    ("bpm",         10, 400,            False),
    ("fixtures",    1,  MAX_FIXTURES,   True),
    ("dimmer",      0,  255,            False),
    ("cycle_speed", 0,  CYCLE_SPEED_MAX, False),
    ("hue_start",   0,  100,            False),
    ("hue_width",   0,  100,            False),
)


class Controller:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.changed = threading.Condition()
        self.version = 0
        self.state: dict[str, Any] = deepcopy(DEFAULT_STATE)
        self.sequence: list[list[int]] = []
        self.step: int = 0
        self.active: list[int] = []
        self.dmx = DMXOutput()
        self._cycle_phase = 0.0
        self._cycle_t = time.monotonic()
        self._next_step_at = time.monotonic()
        self._save_cv = threading.Condition()
        self._dirty = False
        self._stopping = False
        self._load_state()
        self.state["running"] = True
        self.state["blackout"] = False
        self._rebuild_sequence()

    # --- hue / colour ---

    def _advance_hue(self) -> float:
        """Advance the cycle phase by elapsed time and return current hue.

        Mutates `_cycle_phase` and `_cycle_t`. Call once per frame from the
        DMX loop only. Read-only callers should use `_current_hue()`.
        """
        now = time.monotonic()
        dt = now - self._cycle_t
        self._cycle_t = now
        speed = self.state["cycle_speed"]
        if speed > 0:
            self._cycle_phase = (self._cycle_phase + dt * speed / 300.0) % 1.0
        return self._cycle_phase

    def _current_hue(self) -> float:
        return self._cycle_phase

    def _effective_rgb(self, phase: float) -> tuple[int, int, int]:
        start = self.state["hue_start"] / 100.0
        width = self.state["hue_width"] / 100.0
        tri = 1 - abs(2 * phase - 1)
        return hsv_to_rgb(start + tri * width)

    # --- change notification ---

    def _notify(self) -> None:
        with self.changed:
            self.version += 1
            self.changed.notify_all()

    def wait_for_change(self, last_version: int, timeout: float) -> int:
        with self.changed:
            if self.version == last_version:
                self.changed.wait(timeout=timeout)
            return self.version

    # --- persistence (debounced) ---

    def _load_state(self) -> None:
        if not os.path.exists(STATE_FILE):
            log.info("no state file, using defaults")
            return
        try:
            with open(STATE_FILE) as f:
                saved = json.load(f)
            for k in PERSISTED_KEYS:
                if k in saved:
                    self.state[k] = saved[k]
            log.info("loaded state from %s", STATE_FILE)
        except Exception as exc:
            log.warning("could not load %s: %s (using defaults)", STATE_FILE, exc)

    def _mark_dirty(self) -> None:
        with self._save_cv:
            self._dirty = True
            self._save_cv.notify()

    def _write_state_now(self) -> None:
        """Snapshot persisted keys under lock, then write to disk."""
        with self.lock:
            persisted = {k: self.state[k] for k in PERSISTED_KEYS}
        try:
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(persisted, f, indent=2)
            os.replace(tmp, STATE_FILE)
        except Exception as exc:
            log.error("could not save state: %s", exc)

    def persistence_loop(self) -> None:
        """Coalesce dirty marks: at most one disk write per SAVE_DEBOUNCE_SEC."""
        log.info("persistence thread started")
        while not self._stopping:
            with self._save_cv:
                while not self._dirty and not self._stopping:
                    self._save_cv.wait()
                if self._stopping:
                    break
                self._dirty = False
            # Sleep first so further changes within the window get coalesced
            # into the upcoming write.
            time.sleep(SAVE_DEBOUNCE_SEC)
            with self._save_cv:
                self._dirty = False
            self._write_state_now()

    def flush_state(self) -> None:
        """Force a synchronous write. For atexit/shutdown."""
        with self._save_cv:
            self._stopping = True
            had_pending = self._dirty
            self._dirty = False
            self._save_cv.notify_all()
        if had_pending:
            self._write_state_now()

    # --- sequencing ---

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
        dim = self.state["dimmer"] / 255.0
        w = self.state["color"][3]
        if self.state["cycle_speed"] > 0:
            r, g, b = self._effective_rgb(self._advance_hue())
        else:
            r, g, b = self.state["color"][:3]
        rr, gg, bb, ww = int(r * dim), int(g * dim), int(b * dim), int(w * dim)
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
        self._next_step_at = time.monotonic()
        while True:
            now = time.monotonic()
            stepped = False
            with self.lock:
                running = self.state["running"]
                bpm = self.state["bpm"]
                pattern = self.state["pattern"]
                if running and self.sequence and now > self._next_step_at:
                    self.step = (self.step + 1) % len(self.sequence)
                    self._next_step_at = now + max(0.01, 60.0 / max(1, bpm))
                    if pattern == "random" and self.step == 0:
                        # Reshuffle each loop so 'random' actually keeps randomising.
                        self.sequence = build_sequence("random", self.state["fixtures"])
                    stepped = True
                if running and self.sequence:
                    self.active = list(self.sequence[self.step % len(self.sequence)])
                    frame = self._frame_for(self.active)
                else:
                    frame = self._frame_for([])
                    self._next_step_at = now
            self.dmx.send(frame)
            if stepped:
                self._notify()
            time.sleep(FRAME_INTERVAL if running else BLANK_FRAME_INTERVAL)

    # --- public API ---

    def status(self) -> dict[str, Any]:
        with self.lock:
            s = {
                **{k: self.state[k] for k in DEFAULT_STATE},
                "step": self.step,
                "seq_len": len(self.sequence),
                "active": list(self.active),
                "dmx": self.dmx.status(),
                "dmx_target": self.dmx.target,
            }
            if self.state["cycle_speed"] > 0:
                r, g, b = self._effective_rgb(self._current_hue())
                s["effective_color"] = [r, g, b, self.state["color"][3]]
            else:
                s["effective_color"] = list(self.state["color"])
            return s

    def run(self) -> None:
        with self.lock:
            self.state["running"] = True
            self._rebuild_sequence()
            self._next_step_at = time.monotonic()
        self._mark_dirty()
        self._notify()

    def stop(self) -> None:
        with self.lock:
            self.state["running"] = False
            self.active = []
        self._mark_dirty()
        self._notify()

    def step_once(self) -> None:
        with self.lock:
            if self.state["running"] or not self.sequence:
                log.debug("step_once ignored (running=%s, seq_len=%d)",
                          self.state["running"], len(self.sequence))
                return
            self.step = (self.step + 1) % len(self.sequence)
            self.active = list(self.sequence[self.step])
        self._notify()

    def toggle_blackout(self) -> None:
        with self.lock:
            self.state["blackout"] = not self.state["blackout"]
        self._mark_dirty()
        self._notify()

    def update(self, patch: dict[str, Any]) -> tuple[bool, str]:
        with self.lock:
            rebuild = False
            bpm_changed = False
            cycle_was_off = self.state["cycle_speed"] == 0
            for key, lo, hi, rebuilds in _INT_FIELDS:
                if key not in patch:
                    continue
                try:
                    v = int(patch[key])
                except (TypeError, ValueError):
                    return False, f"{key} must be int"
                if not lo <= v <= hi:
                    return False, f"{key} out of range"
                if v != self.state[key]:
                    if key == "bpm":
                        bpm_changed = True
                    self.state[key] = v
                    if rebuilds:
                        rebuild = True
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
                rgb_changed = list(c[:3]) != list(self.state["color"][:3])
                self.state["color"] = list(c)
                if rgb_changed:
                    self.state["cycle_speed"] = 0
            if rebuild:
                self._rebuild_sequence()
            if bpm_changed:
                # Apply the new tempo immediately rather than waiting out the
                # previously-scheduled (potentially long) interval.
                interval = max(0.01, 60.0 / max(1, self.state["bpm"]))
                now = time.monotonic()
                self._next_step_at = min(self._next_step_at, now + interval)
            if cycle_was_off and self.state["cycle_speed"] > 0:
                # Reset the integration clock so the first frame after enabling
                # cycle doesn't apply a huge dt accumulated while speed was 0.
                self._cycle_t = time.monotonic()
        self._mark_dirty()
        self._notify()
        return True, "ok"
