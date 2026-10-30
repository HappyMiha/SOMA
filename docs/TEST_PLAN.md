# Test plan and release gates

Run headless regression tests on both OSes, then device tests on isolated native
fixtures. Mock providers validate contracts and lifecycle; they do not establish
model intelligence, task success, learning transfer or correspondence.

1. Contracts: fixed frame fields, finite normalized coordinates, closed action
   alphabet, rejected tools/imports; manual source review of own storage/inference
   and every allowed native API.
2. Body: owned-window click/double/drag/wheel, Ukrainian/emoji, hotkeys, release,
   actual screenshots, DPI and monitor gap transformations; test secure sessions
   only on a test machine, never bypass lock/UAC.
3. Durability: terminate a subprocess with os._exit after durable action intent,
   recover the same persona; inconclusive evidence stays pending; corrupt hashes,
   missing identity, disk/write failure and invalid restore must preserve history.
4. Teaching: synchronous motor inhibition during slow inference, real hooks only
   in visible recording, privacy gaps omit both images and keys, timestamp pairing,
   crash recovery, semantic strategy storage and fresh visual grounding.
5. Model endpoints: real configured remote and local VLM; autonomous browser
   exploration, own-goal completion, subsequent recall, social GUI correspondence
   in a test account, transfer to changed UI. Record screenshots/ledger. Never
   substitute deterministic provider stubs for these acceptance tests.
6. Product: build Windows installer and Linux .deb, isolated install/start,
   first-run setup, provider change without identity change, backup/restore,
   upgrade, uninstall preserves app-data, autostart, two physical reboots.
7. Hardware: actual Windows and physical Linux/X11 sessions, multiple displays,
   secure-session sleep/resume, defined Wayland portal matrix (currently open).
8. Endurance: 24–72 h in a dedicated test session with actual VLM, periodic own
   process CPU/RAM/latency/token/cost metrics, bounded screenshots, no hidden
   cloud scheduler. OSWorld release-matched subset, with pinned assets and model.

Record PASS / FAIL / NOT RUN and exact environment for each gate. A virtual X11
server establishes X11 integration only, not physical Linux sleep/GPU behavior.
