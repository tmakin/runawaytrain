#!/usr/bin/env bash
# Local sanity checks. Run before ./sync.sh.
#
# Usage: scripts/ci.sh

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

run() {
    echo
    echo "==> $*"
    "$@"
}

# 1. Resolve / install deps + this package (editable).
run uv sync

# 2. Type check (Astral's ty, run via uvx so no dev-dep needed).
run uvx ty check src/tunnel_dmx

# 3. Lint (ruff via uvx).
run uvx ruff check src/tunnel_dmx

# 4. Render templates through Flask's test client to catch Jinja2 syntax
#    errors and missing url_for targets. Booting Flask is fine here.
run uv run python -c "
from tunnel_dmx import chase
client = chase.app.test_client()
r = client.get('/');     assert r.status_code == 200, r.status_code
r = client.get('/help'); assert r.status_code == 200, r.status_code
print('templates: ok')
"

# 5. Smoke test: exercise build_sequence and the API surface via the Flask
#    test client. No serial port, no real DMX writes.
run uv run python -c "
from tunnel_dmx import chase
from tunnel_dmx.patterns import build_sequence
from tunnel_dmx.config import PATTERNS, MAX_FIXTURES

# Every pattern must produce a non-empty sequence for any fixture count 1..MAX.
for p in PATTERNS:
    for n in (1, 2, 8, MAX_FIXTURES):
        seq = build_sequence(p, n)
        assert seq, f'empty sequence for {p}/{n}'
        for step in seq:
            assert all(0 <= i < n for i in step), f'out-of-range index in {p}/{n}: {step}'
print('build_sequence: ok')

client = chase.app.test_client()
r = client.get('/api/status'); assert r.status_code == 200, r.status_code
body = r.get_json()
assert 'dmx' in body and body['dmx'] in ('ok','demo','error','unpatched'), body
assert 'dmx_target' in body, body
r = client.post('/api/set', json={'bpm': 120, 'pattern': 'bounce', 'fixtures': 4})
assert r.status_code == 200, (r.status_code, r.data)
r = client.post('/api/set', json={'bpm': 9999})
assert r.status_code == 400, 'validation should reject out-of-range bpm'
r = client.post('/api/run');  assert r.status_code == 200
r = client.post('/api/stop'); assert r.status_code == 200
r = client.get('/help'); assert r.status_code == 200, r.status_code
assert b'<table' in r.data, '/help should render markdown tables'
print('flask api smoke: ok')
"

echo
echo "==> All checks passed."
