# Lights: physical setup and web UI mapping

Specific to the **Equinox MaxiPar Quad** (RGBW 4-in-1 LED PAR can).
How to address each fixture, daisy-chain the run, and verify the install
from the phone UI.

---

## 1. Fixture mode (set on every MaxiPar Quad)

The MaxiPar Quad has a 4-button menu on the rear (`MODE`, `UP`, `DOWN`,
`ENTER`) and a 4-digit display. It supports several DMX channel layouts;
this controller requires the **4-channel mode** (`d004` / `CH04` on the
display).

To set 4-channel mode:

1. Press `MODE` until the display shows the channel-mode parameter
   (typically prefixed `CH` or `d`).
2. Use `UP` / `DOWN` to select `CH04` (or `d004`).
3. Press `ENTER` to confirm. The display should stop flashing.
4. Repeat on every fixture.

In 4-channel mode the slot order is **R, G, B, W**, which is what
the controller assumes:

| Offset | Channel |
|--------|---------|
| +0     | Red     |
| +1     | Green   |
| +2     | Blue    |
| +3     | White   |

**Do not use the 5/7/8-channel modes.** They prepend a master dimmer
and append strobe/macro channels, so the colour sliders in the UI will
appear to do nothing (the master dimmer slot will be 0 and the lamp
will stay dark). If you must run a different mode, the slot mapping in
`_frame_for()` in `controller.py` needs to be updated to match.

---

## 2. DMX addressing

On the MaxiPar Quad, the start channel is the parameter shown as `A001`
(default). Press `MODE` until the display shows `AXXX`, use `UP` / `DOWN`
to set the value from the table below, then press `ENTER` to confirm.

| Fixture # | Start ch | Channels |
|-----------|----------|----------|
| 1         | 1        | 1–4      |
| 2         | 5        | 5–8      |
| 3         | 9        | 9–12     |
| 4         | 13       | 13–16    |
| 5         | 17       | 17–20    |
| 6         | 21       | 21–24    |
| 7         | 25       | 25–28    |
| 8         | 29       | 29–32    |
| 9         | 33       | 33–36    |
| 10        | 37       | 37–40    |
| 11        | 41       | 41–44    |
| 12        | 45       | 45–48    |
| 13        | 49       | 49–52    |
| 14        | 53       | 53–56    |
| 15        | 57       | 57–60    |
| 16        | 61       | 61–64    |

**Formula:** `start = (fixture_number - 1) * 4 + 1`.

Label each fixture's case with its number and start channel before installing
in the tunnel. You will not want to re-address a fixture once it is hung.

---

## 3. Daisy chain

The MaxiPar Quad has **3-pin XLR DMX IN and OUT** sockets on the rear
(plus IEC mains in/out for power-linking, but treat that as a separate
chain — see warning below).

```
  Pi 4B ──USB──▶ Enttec Open DMX
                       │ 3-pin XLR
                       ▼
                ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
                │ MaxiPar #1   │──▶ │ MaxiPar #2   │──▶ │ MaxiPar #N   │──▶ [120Ω term]
                │ A001 (1-4)   │    │ A005 (5-8)   │    │              │
                └──────────────┘    └──────────────┘    └──────────────┘
```

Rules:

- Use **DMX cable** (110Ω, twisted pair). Mic cable will work for short runs
  but is not spec; for a 120m run, use proper DMX cable.
- DMX **OUT** of the Enttec into DMX **IN** of fixture 1, OUT of 1 into IN
  of 2, and so on. Do not split.
- Fit a **120Ω terminator** (3-pin male XLR) in the DMX OUT of the last
  fixture. Without it, reflections will cause flicker, especially over 120m.
- Keep DMX physically separated from mains by at least **50mm** along the run.
  Cross at 90° if you must cross.
- The MaxiPar's IEC power-link can chain mains to the next fixture, but
  total current draw is limited (check the rear-panel rating on your unit,
  typically 5–8 fixtures per chain). For a 16-fixture install on a single
  generator feed, split the mains into multiple shorter chains rather than
  one long daisy.

---

## 4. First-power checklist

1. Power the generator and let it stabilise.
2. Power the Pi.
3. Watch each MaxiPar Quad as it boots:
   - The display flashes briefly, then settles on its address (e.g. `A001`).
   - It should not flicker or show `--` / blank. If it does, the DMX thread
     is not running or the cable run is broken: check
     `sudo journalctl -u tunnel-dmx -f`.
   - On power-up the lamp itself stays dark until DMX values arrive: this
     is normal.
4. Join the `TunnelDMX` WiFi from your phone and open `http://dmx.local`
   (or `http://192.168.50.1`).

---

## 5. Verifying each fixture from the UI

Use this procedure to confirm every fixture is addressed correctly without
having to walk the full 120m more than once.

1. **Set fixture count** to your real count (e.g. `8`) using the Fixtures
   slider.
2. **Pattern: `single`**. The chase will light one fixture at a time.
3. **BPM: 30**. Slow enough to walk between fixtures.
4. **Dimmer: 255**, colour: bright (e.g. R=255, G=255, B=255, W=255).
5. Press **Run**.
6. Walk the tunnel. Fixture 1 should light first, then 2, then 3...
   - If a fixture is **skipped**, its address is wrong (check the menu).
   - If **two light at once**, two fixtures share an address.
   - If a fixture lights but **wrong colour channel**, it is in the wrong
     mode (probably 8-channel) or has a non-RGBW slot order.
7. Press **Stop** when done.

Alternative: stop the chase and use the **Step** button to advance one
fixture at a time, so you can pause on any fixture for inspection.

---

## 6. Web UI — what each control does

| Control          | Effect |
|------------------|--------|
| **PAR grid**     | Live indicator: amber = currently active, dim = configured but off, dark = beyond the configured fixture count. Updates every 500ms. |
| **Pattern**      | Selects the chase shape. Changing this rebuilds the sequence and resets to step 0. |
| **BPM**          | Step rate. 60 BPM = one step per second. Range 10–400. |
| **Fixtures**     | Number of fixtures in the chase. Sequences are built against this count, so set it to match the physical install. Range 1–16. |
| **Dimmer**       | Master intensity scale applied to all channels (0–255). |
| **Cycle**        | Hue cycle speed (0–60). 0 disables the cycle and uses the fixed R/G/B values. Above 0, the colour sweeps through the hue band defined by Hue Start / Hue Width. |
| **Hue Start**    | Starting hue of the cycle band, 0–100 (as a fraction of the colour wheel). |
| **Hue Width**    | Width of the hue band the cycle sweeps over, 0–100. |
| **R / G / B / W**| Per-channel colour values (0–255 each). Editing R, G, or B disables the cycle (sets Cycle back to 0). W is always added on top of the cycle output. |
| **Run**          | Starts the chase. |
| **Step**         | Advances one position manually. Only takes effect while stopped. |
| **Stop**         | Stops the chase and blanks the active fixtures. DMX frames continue (so fixtures don't show "no signal"). |
| **Black**        | Toggles blackout. Sends all-zero frames regardless of run state. Tap again to restore. |
| **step N / M**   | Footer counter: current step index / total steps in the sequence. |

### Patterns

| Pattern   | Behaviour |
|-----------|-----------|
| single    | One fixture on at a time, advances forward. |
| double    | Two adjacent fixtures, wraps. |
| triple    | Three adjacent fixtures, wraps. |
| bounce    | One fixture travelling forward then back (ping-pong). |
| odd_even  | All odd fixtures, then all even. |
| build     | Accumulates fixtures one by one, then strips back down. |
| random    | Random single fixture each step (sequence regenerates when selected). |
| all       | All fixtures on, single step. Useful as a static lighting state. |

### Persistence

Most settings (pattern, BPM, fixtures, dimmer, colour, cycle speed, hue
start, hue width) persist across reboots in `state.json`. `running` and
`blackout` are **not** persisted: on startup the controller comes up
running (so the tunnel resumes lighting after a generator power-cycle
without operator intervention) and not blacked out.

---

## 7. Troubleshooting MaxiPar Quads

- **Fixture ignores DMX completely (sound-reactive or auto-cycling)** — it
  is in a standalone mode. Press `MODE` and look for `SOUN` (sound active),
  `AUTO` / `Auto`, or `SLAV` (slave). Cycle back to the address parameter
  (`AXXX`) and ensure the channel mode is `CH04`. The presence of a flashing
  address display means it is in DMX mode and waiting for data.
- **Fixture lights up but the colour sliders do nothing** — almost always
  the channel mode is set to `CH05` / `CH07` / `CH08`, where slot 1 is a
  master dimmer that this controller leaves at 0. Set the fixture to
  `CH04`.
- **Fixture flickers, especially at the end of the chain** — missing or
  faulty 120Ω terminator on the last fixture. Replace it.
- **Fixture lights but is dim** — confirm the dimmer slider in the UI is
  255. The MaxiPar Quad has no separate onboard dimmer in `CH04` mode, so
  brightness is purely a function of the colour values × the controller's
  master dimmer.
- **Display blank or fixture unresponsive** — no DMX frames arriving. Check
  the XLR cable (swap ends to rule out a bad lead), check
  `sudo journalctl -u tunnel-dmx -f` for serial errors. If the Pi log shows
  "demo mode", the Enttec adapter is not detected — replug it.
- **Display shows address but lamp stays off** — DMX is connected but the
  controller is sending zeros. Check the UI: blackout off, dimmer up,
  colour values non-zero, fixture index within the configured fixture
  count. Use **Step** with pattern `single` to confirm.
- **Some fixtures stop responding mid-run** — over a 120m run this is
  usually cable: a marginal connector, or DMX laid alongside mains. Reseat
  every XLR connection at the affected fixture and the one before it; if
  it persists, swap that section of cable.
