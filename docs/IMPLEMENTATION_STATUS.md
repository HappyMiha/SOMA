# Implementation status

The project was implemented through audit → implementation → test → correction
cycles. Hardware/model-dependent acceptance gates remain open and are not counted
as completed by the presence of source code.

| Phase | Implemented | Evidence / remaining gate |
|---|---|---|
| 0 — upstream | All 12 candidates cloned, SHA/license/module audits, isolated candidate probes, ADRs | Reports and reproducible scripts under docs/upstream and research/upstream-pocs. OSWorld source probes only. |
| 1 — native body | Qt widget/tray, setup, fixed action parser, Windows/X11 pixels and keyboard/mouse, pre-dispatch validation, normalized geometry/DPI, installer build scripts | Real Windows owned fixture and virtual X11 native fixture PASS. Browser exploration with real VLM and physical multimonitor NOT RUN. |
| 2 — cognition | One persisted identity, autonomous goal planning, goal revisions, six memory kinds, structured reflection/experience skills, visual feedback, request budgets, recovery quarantine, power/session lifecycle | Unit/crash tests and synthetic wait-only native runtime smoke. Real VLM own-goal completion and physical reboot gates NOT RUN. |
| 3 — teaching | Visible hooks, immediate input inhibition, privacy, timestamp triples, bounded incremental durable journal, crash reconstruction, semantic strategy acquisition | Real Windows/X11 device traces and deterministic semantic-inference tests PASS. Model-based transfer to another UI NOT RUN. |
| 4 — everyday activity | General visual planner can express browser/editor/mail/messenger interaction through the same port; semantic/social facts retain frame provenance | Real service accounts, correspondence and the research→document→reply workflow NOT RUN. No application integrations or site macros were added. |
| 5 — packaging/durability | Windows installer and Linux .deb pipelines, bundled runtime, app-data preservation, credential vault, backups/restore, SBOM/licenses/checksums, platform CI | Platform package build and smoke reports accompany artifacts. Public signing, clean-machine upgrades, physical sleep/reboots, endurance and resource baselines remain open. |

0.2.0 (2026-10-30/31), live on the physical SOMIK laptop (Windows 11, i7-1255U,
16 GB). Brains (ADR-003, "each brain its own job"): until 31 Oct 14:14 the owner's
Codex login as a tool-less CLI brain with a CPU VLM fallback; since then the
owner's Claude Code login for deep work (waking, conversations, something new,
being stuck or unsure, human checks, reflection, learning), local qwen3.5:4b on a
GTX 1060 6 GB eGPU (USB4) for routine work, Codex as stand-in (its quota is
exhausted until 4 Nov). Machine vision (offline Cyrillic OCR) reads her own
frames. Gates passed live, with evidence in TEST_RESULTS.md:

| Gate | Status |
|---|---|
| 1 three interfaces | Contract tests; one reviewed process exception for the brain CLIs; passwords typed from the vault as keyboard events |
| 2 autonomous start | PASS — own goals and visible GUI actions with no task |
| 3 browser exploration | PASS — Firefox search, articles, cookie dialogs, tabs, navigation; reading habits with scroll verified by moving text |
| 4 general GUI control | Clicks, double click, scroll (at a point), keys, hotkeys, typing, dialogs in live sessions; drag and multi-monitor not exercised live |
| 5 correspondence | PASS — Telegram messages read and answered by keyboard, verified from pixels/changed text (≈2 min from opening the chat to a sent reply on the GPU/Claude brains); own introduction posted on a Discord server |
| 6 human demonstration | Owner's demonstration recorded and learned on wake; transfer gate 7 NOT RUN |
| 8 continuity | One persona `75ac1118…` across 50 wakes (restarts, reinstalls, hard kills, three brain changes); 1,404 journaled inputs, 2,396 memories, 75 procedural skills |
| 9 sleep / 10 crash safety | Graceful quit + wake; uncertain inputs reconciled, never replayed (also live after reinstalls interrupted an input) |
| 11 packaging | PyInstaller bundle + installed-binary smoke on every build; Inno installer not rebuilt (Inno Setup not installed); Linux 0.2.0 NOT RUN (no WSL) |
| 12 resources | CPU era: 30–142 MB, ≤ ~6 % of one core over 3 h. GPU era: model 3 GiB in VRAM; Ollama host prompt cache bounded by unloading every 6 local requests (it reached 3.9 GB at 24); 14 h of samples kept, a 24 h sampler with GPU running since 31 Oct 15:40 |
| 13 long run | Over a day of unattended life with interruptions for upgrades; an uninterrupted 24–72 h run NOT yet complete |
| §8 own identity | Proton mailbox and Discord account created by SOMA via GUI, CAPTCHAs by a human; account registry in her memory, passwords in the OS vault, owner window to see and fix them |
| §7.1 experience learning | Procedural skills and reflections formed from her own episodes |

Known implementation limits: no native Wayland portal/PipeWire adapter; recall is
lexical plus a character-trigram vector index, not neural embeddings; uncertain
non-reversible inputs are reconciled from pixels (at most three inspections, then
released as unresolved, never replayed); screenshots do not include the mouse
pointer; restore interruption markers require
recovery rather than silent rebirth; append-only autobiography requires lifetime
storage planning. Local model weights and remote credentials are supplied by the
user through the widget. There is no cloud life loop.

Use TEST_PLAN.md and TEST_RESULTS.md as the acceptance checklist. A passed device
fixture or deterministic inference stub does not close the intelligence gates.
