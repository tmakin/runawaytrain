"""DMX output via local OLA daemon (olad) HTTP API."""

from __future__ import annotations

import http.client
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlsplit

from .config import DMX_UNIVERSE_SIZE, OLA_UNIVERSE, OLA_URL


log = logging.getLogger("tunnel-dmx")


class DMXOutput:
    """Send DMX frames via a local OLA daemon (olad) HTTP API.

    OLA owns the FTDI / Enttec Open DMX adapter and handles BREAK timing
    correctly via libftdi, which pyserial cannot do reliably on Linux.

    Uses one persistent HTTPConnection: at 30fps that saves ~30 socket
    setups/teardowns per second to loopback. The connection is recycled
    on any error.
    """

    ERROR_WINDOW_SEC = 2.0
    OK_WINDOW_SEC = 4.0  # if no successful send in this window, drop "ok"
    HTTP_TIMEOUT = 0.5

    def __init__(self, universe: int = OLA_UNIVERSE, url: str = OLA_URL) -> None:
        self.universe = universe
        self.url = url
        parts = urlsplit(url)
        self._host = parts.hostname or "127.0.0.1"
        self._port = parts.port or 9090
        self._path = parts.path or "/set_dmx"
        self.last_error_at: float = 0.0
        self.last_ok_at: float = 0.0
        self.patched: bool | None = None  # None = unknown; True/False after check
        self._conn: http.client.HTTPConnection | None = None

    @property
    def target(self) -> str:
        return f"OLA universe {self.universe}"

    def check_patched(self) -> None:
        """Confirm our universe has an output port patched at olad.

        OLA accepts /set_dmx for any universe id whether or not anything
        is patched downstream, so a 200 response does NOT prove DMX
        actually reaches the wire. This check queries olad's universe_info
        endpoint and warns loudly if there's no output port. Call from
        main() after olad is known to be up; safe to call again later
        if you want to re-probe.
        """
        info_url = self.url.rsplit("/", 1)[0] + f"/json/universe_info?id={self.universe}"
        try:
            with urllib.request.urlopen(info_url, timeout=1.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log.warning("could not query olad universe state: %s", exc)
            self.patched = None
            return
        outputs = data.get("output_ports") or []
        if outputs:
            self.patched = True
            log.info("olad universe %d patched (%d output port(s): %s)",
                     self.universe, len(outputs),
                     ", ".join(p.get("description", "?") for p in outputs))
            return
        self.patched = False
        log.error(
            "olad universe %d has NO output port patched -- DMX will not reach fixtures",
            self.universe,
        )
        log.error("fix: ola_dev_info ; ola_patch -d <DEV> -p <PORT> -u %d",
                  self.universe)

    def status(self) -> str:
        now = time.monotonic()
        if self.patched is False:
            return "unpatched"
        if self.last_error_at and (now - self.last_error_at) < self.ERROR_WINDOW_SEC:
            return "error"
        if self.last_ok_at and (now - self.last_ok_at) < self.OK_WINDOW_SEC:
            return "ok"
        return "demo"

    def _drop_conn(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def send(self, channels: list[int]) -> None:
        slots = channels[:DMX_UNIVERSE_SIZE]
        body = urllib.parse.urlencode({
            "u": self.universe,
            "d": ",".join(str(c) for c in slots),
        })
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        try:
            if self._conn is None:
                self._conn = http.client.HTTPConnection(
                    self._host, self._port, timeout=self.HTTP_TIMEOUT,
                )
            self._conn.request("POST", self._path, body, headers)
            resp = self._conn.getresponse()
            resp.read()  # drain so the connection stays usable
            if resp.status == 200:
                self.last_ok_at = time.monotonic()
            else:
                log.error("OLA returned status %d", resp.status)
                self.last_error_at = time.monotonic()
                self._drop_conn()
        except (http.client.HTTPException, OSError) as exc:
            log.debug("OLA send failed: %s", exc)
            self.last_error_at = time.monotonic()
            self._drop_conn()
