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

Known implementation limits: no native Wayland portal/PipeWire adapter; lexical
memory retrieval rather than embeddings; uncertain outcomes conservatively block
new input until visual reconciliation; restore interruption markers require
recovery rather than silent rebirth; append-only autobiography requires lifetime
storage planning. Local model weights and remote credentials are supplied by the
user through the widget. There is no cloud life loop.

Use TEST_PLAN.md and TEST_RESULTS.md as the acceptance checklist. A passed device
fixture or deterministic inference stub does not close the intelligence gates.
