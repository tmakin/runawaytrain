"""Chase pattern generation and colour helpers."""

from __future__ import annotations

import logging
import random


log = logging.getLogger("tunnel-dmx")


def hsv_to_rgb(h: float) -> tuple[int, int, int]:
    """Hue in [0,1) at full saturation/value -> 8-bit RGB."""
    h = h % 1.0
    i = int(h * 6)
    f = h * 6 - i
    q = int(255 * (1 - f))
    t = int(255 * f)
    return [(255, t, 0), (q, 255, 0), (0, 255, t),
            (0, q, 255), (t, 0, 255), (255, 0, q)][i % 6]


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
