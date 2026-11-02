# SOMA 0.2.0 — development build, first real life on SOMIK

Built and installed 2026-10-31 on the owner's Windows 11 laptop from the source in
`C:\SOMA` (no git on this PC; the GitHub repository HappyMiha/SOMA does not contain
these changes yet).

| Artifact | Size | SHA256 |
|---|---:|---|
| Windows x64 portable bundle (`artifacts/win32/SOMA-0.2.0-windows-x64-portable.zip`) | 52,492,375 bytes | `8758bf1cd6177670d3471cc65b96098807a4bd10ab3709a490db8c09edd311c0` |

Installed by copying the bundle to `%LOCALAPPDATA%\Programs\SOMA` over 0.1.0 (app
and persona backups in `%LOCALAPPDATA%\SOMA-backups\`), autostart via the user's
Startup folder. The Inno Setup `setup.exe` was not rebuilt because Inno Setup is
not installed on this PC; `packaging/windows/soma.iss` now calls `SOMA.exe --quit`
before upgrading and on uninstall. No Linux 0.2.0 package (no WSL here).

Source suite on Windows: **152 tests, 21 subtests pass**. Every installed build
passed the static ICU guard and the packaged two-launch runtime smoke.

What changed since 0.1.0: native Ollama with schema decoding and context checks;
Codex/Claude Code subscription CLIs as tool-less brains (hybrid with local
fallback); first-person diary context and life-oriented prompt; owner decisions on
her self-image (PERSONALITY_AND_LIFE.md); own-shell exclusion; minimal widget with
housekeeping in the tray; first-run local brain detection; trigram vector recall;
`--quit`; adaptive settle; pixel-paced rest and verification; key-name
normalization; `recently_done`. See ADR-003 and WORK_LOG.md.

Live results are in TEST_RESULTS.md and IMPLEMENTATION_STATUS.md: autonomous start,
browser exploration, Telegram correspondence, an own Proton mailbox (CAPTCHA by a
human), experience-derived skills, crash-safe continuity. Still open: skill
transfer from a demonstration, drag/multi-monitor, two physical reboots, 24–72 h
endurance, Inno installer and Linux package for 0.2.0, Claude CLI brain live run,
signing.
