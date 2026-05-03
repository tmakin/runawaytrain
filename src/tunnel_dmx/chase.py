"""Tunnel DMX Chase Controller.

Headless DMX chase controller for a 120m railway tunnel installation.
Serves a phone-optimised web UI and drives an Enttec Open DMX USB adapter
via a local OLA daemon.
"""

from __future__ import annotations

import atexit
import json
import logging
import threading
from importlib.resources import files
from typing import Any

import markdown
import waitress
from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from .config import MAX_FIXTURES, PATTERNS, WEB_PORT
from .controller import Controller


__all__ = ["app", "controller"]


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("tunnel-dmx")


controller = Controller()
app = Flask(__name__)


def _render_help() -> str:
    try:
        text = (files(f"{__package__}.help") / "LIGHTS.md").read_text(encoding="utf-8")
    except (OSError, FileNotFoundError) as exc:
        log.warning("could not read LIGHTS.md: %s", exc)
        return "<p>Help document not available.</p>"
    return markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "toc"],
        output_format="html",
    )


HELP_HTML = _render_help()


@app.route("/")
def index() -> Any:
    return render_template("index.html", max_fixtures=MAX_FIXTURES, patterns=PATTERNS)


@app.route("/help")
def help_page() -> Any:
    return render_template("help.html", body=HELP_HTML)


@app.route("/api/status")
def api_status() -> Any:
    return jsonify(controller.status())


@app.route("/api/stream")
def api_stream() -> Any:
    HEARTBEAT_SEC = 2.0
    def gen():
        yield f"data: {json.dumps(controller.status())}\n\n"
        last = controller.version
        while True:
            new_version = controller.wait_for_change(last, timeout=HEARTBEAT_SEC)
            if new_version == last:
                yield "event: hb\ndata: \n\n"
            else:
                last = new_version
                yield f"data: {json.dumps(controller.status())}\n\n"
    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return Response(stream_with_context(gen()), headers=headers)


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
    # Probe olad now (deferred from import time so tests/imports don't block
    # on the network and so olad has a chance to come up before we check).
    controller.dmx.check_patched()
    threading.Thread(target=controller.dmx_loop, daemon=True).start()
    threading.Thread(target=controller.persistence_loop, daemon=True).start()
    atexit.register(controller.flush_state)
    log.info("starting waitress on 0.0.0.0:%d", WEB_PORT)
    # threads=8 leaves room for several concurrent SSE clients (each holds a
    # thread for the lifetime of the connection) plus regular API requests.
    # channel_timeout is set generously so SSE heartbeats keep connections
    # alive without being closed as idle.
    waitress.serve(
        app,
        host="0.0.0.0",
        port=WEB_PORT,
        threads=8,
        channel_timeout=600,
        ident="tunnel-dmx",
    )


if __name__ == "__main__":
    main()
