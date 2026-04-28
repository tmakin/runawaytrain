#!/usr/bin/env bash
# Local sanity checks. Run before ./sync.sh.
#
# Usage: ./ci.sh

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

run() {
    echo
    echo "==> $*"
    "$@"
}

# 1. Resolve / install deps from pyproject.toml.
run uv sync

# 2. Type check (Astral's ty, run via uvx so no dev-dep needed).
run uvx ty check chase.py

# 3. Lint (ruff via uvx).
run uvx ruff check chase.py

# 4. Byte-compile templates: render index.html with dummy context to catch
#    Jinja2 syntax errors without booting Flask.
run uv run python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('templates'))
env.get_template('index.html').render(max_fixtures=16, patterns=('single','all'))
print('templates/index.html: ok')
"

# 5. Smoke test: import chase, exercise build_sequence, hit a few endpoints
#    via Flask's test client. No serial port, no real DMX writes.
run uv run python -c "
import chase
from chase import build_sequence, PATTERNS, MAX_FIXTURES

# Every pattern must produce a non-empty sequence for any fixture count 1..MAX.
for p in PATTERNS:
    for n in (1, 2, 8, MAX_FIXTURES):
        seq = build_sequence(p, n)
        assert seq, f'empty sequence for {p}/{n}'
        for step in seq:
            assert all(0 <= i < n for i in step), f'out-of-range index in {p}/{n}: {step}'
print('build_sequence: ok')

# Hit the API surface.
client = chase.app.test_client()
r = client.get('/api/status'); assert r.status_code == 200, r.status_code
r = client.post('/api/set', json={'bpm': 120, 'pattern': 'bounce', 'fixtures': 4})
assert r.status_code == 200, (r.status_code, r.data)
r = client.post('/api/set', json={'bpm': 9999})
assert r.status_code == 400, 'validation should reject out-of-range bpm'
r = client.post('/api/run');  assert r.status_code == 200
r = client.post('/api/stop'); assert r.status_code == 200
print('flask api smoke: ok')
"

echo
echo "==> All checks passed."
