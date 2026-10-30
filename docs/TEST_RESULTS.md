# Verification record — development build 0.1.0

This file distinguishes source implementation from passed product acceptance.
The complete specification Definition of Done is **not yet satisfied**.

## Confirmed

* All 12 upstream repositories cloned and audited at pinned commits, with
  reproducible isolated PoCs. See UPSTREAM_EVALUATION.md and its evidence reports.
* Windows and Linux unit/regression suites pass: **108 tests and 15 subtests**.
  Commands and output are captured in the platform verification logs.
* Real Windows body + visible demonstration fixture passes. Native physical
  capture geometry 1080×2280, Qt logical 540×1140, actual DPR 2.0.
  Click, double click, drag, wheel, Ukrainian and emoji keyboard text, hotkey and
  key release verified in its own native window. Twelve injected demonstration
  key events paired with two real captured frames and persisted. See
  `evidence/windows-desktop/report.json` and PNGs. This is a device integration
  test, without VLM inference or external application task success.
* Native Windows source UI smoke (`python -m soma --smoke-seconds 3`) exits cleanly.
* Actual subprocess crash/WAL identity recovery, uncertainty quarantine, hash
  corruption refusal, backup/restore, privacy gaps and stale decision cancellation
  covered by automated tests.

## Package evidence

Windows installation and installed binary smoke are recorded in
`evidence/windows-package/`; Linux package metadata, extraction and native binary
smoke are in `evidence/linux-package/`. Both platforms exercise two sequential
native runtime launches against a deterministic localhost wait-only cognition
stub. The same persona, captured frames, durable wake/sleep/checkpoints and zero
input intents are checked. This is integration evidence, not VLM autonomy.

Linux native capture/input/demonstration probe passes eight checks on a dedicated
virtual Xvfb X11 server in WSL Ubuntu 24.04. Its report and screenshots are under
`evidence/linux-x11/`. The .deb declares its actual glibc >=2.38 requirement;
physical distro/compositor support is unclaimed. A source manifest hash check of
OSWorld is not an OSWorld task pass.

Windows packaging found and corrected an actual Qt/system-ICU collision caused
by a developer PATH dependency. A static PE guard and actual installed-binary
smoke cover the repair. Earlier failed attempts are retained as audit evidence.

## NOT RUN / open acceptance gates

Real configured VLM autonomy and browser exploration; real GUI mail/messenger
correspondence; model-based demonstration generalization and transfer; two
physical reboots; physical Linux/X11, multi-monitor hardware, UAC/lock/sleep
cycles; 24–72 h unattended endurance; i7/16 GB CPU/RAM/thermal/energy profiling;
OSWorld tasks with matched assets; provider dollar-cost calibration; signed public
release and installer upgrades on clean machines. Native Wayland is unavailable.

The user chose to configure local/remote endpoints in the widget. No credentials,
models or test accounts were supplied, so the implementation does not claim these
model/service-dependent gates passed. Linux virtual X11 evidence, when recorded,
must not be described as a physical Linux machine test.
