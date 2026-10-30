# Native Windows desktop evidence

`report.json` records a passing real run on 2026-10-30, lasting 4.546 seconds. Input targeted only the owned, visible fullscreen Qt fixture in `tests/desktop_e2e.py`; the fixture confirmed its own focus before input, closed afterwards and released held keys/buttons. No external application, model or browser was used.

Reproduce explicitly from the project root:

```powershell
.venv/Scripts/python tests/desktop_e2e.py --run-desktop
```

Without `--run-desktop`, the script skips. The run requires an unlocked Windows interactive desktop and refuses ambiguous primary-display mapping. It temporarily raises its owned fixture and emits synthetic input for a few seconds; do not run other GUI tests concurrently.

Verified through native Qt input events and actual HumanInterfacePort/MSS monitor captures:

- Mouse click, double click, drag and wheel.
- Ukrainian plus non-BMP emoji keyboard input; Ctrl+A selection and replacement.
- Paired key release events and no retained body key/button state.
- Teaching inhibits SOMA's input immediately.
- Actual native injected-only keyboard hooks record a synthetic teacher's ` Показ`; DemonstrationRecorder stores 12 inputs linked to two screenshots in the actual MemoryStore SQLite database.
- Current display mapping: 1080×2280 physical pixels, 540×1140 Qt logical coordinates, DPR 2. This is evidence for this one 200% scaling configuration. The additional geometry unit test is simulated and does not establish multi-DPI behavior.

`before.png`, `after-input.png` and `after-teaching.png` are crops of real monitor captures restricted to the owned fixture. No other monitor pixels are saved. `demonstration.json` and `teaching-memory/` contain only synthetic fixture data. Test hooks discard physical user input; they use a test-specific native hook factory and do not claim to exercise the production hook factory's complete behavior.

The first two attempt reports are retained as evidence of the iteration. Attempt 1 blocked its own Qt event loop while injecting and exposed a Unicode ordering problem. The fixture now uses a worker to match production. Attempt 2 still exposed zero-delay Unicode packet ordering. Adding 10 ms cancellable inter-character pacing to the native body resolved the observed issue; the third run passed all checks. This does not establish universal input reliability across applications or IMEs.

Not tested here: real model planning, external-application workflow success, UAC/secure desktop transitions, lock/unlock, multiple monitors with mixed DPI, Linux X11/Wayland, or installation on a separate clean PC.
