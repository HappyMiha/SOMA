# ADR 003: A living brain on SOMIK — subscription CLIs, pixel-paced life

Accepted 2026-10-31, from the 0.2.0 live runs on the owner's i7-1255U laptop.

**Brains.** The installed local VLM (`qwen3-vl:4b-instruct`, CPU only) needs
2–4 minutes per decision; on a desktop people also use, its plans were mostly
stale by the time they were ready. The owner chose a remote brain using their
existing subscriptions. `soma/cli_brains.py` runs the Codex CLI (ChatGPT login)
or the Claude Code CLI (Claude login) as an inference engine only: every tool is
disabled, it runs in an empty temporary directory without user config, rules,
MCP servers or saved sessions, and any tool event rejects the answer. It is the
single production module allowed to start a process (`test_contract`). Live mode
is hybrid: Codex first, the local VLM when Codex is unavailable. Native Ollama
uses `/api/chat` with an explicit context size and JSON-schema decoding; requests
that would not fit are refused, never silently truncated. The OpenAI-compatible
HTTP route remains for keyed providers. The owner removed the daily request cap.

**Perception and pacing.** SOMA perceives a first-person diary, not telemetry.
Pointer plans are invalidated only by change near their target, keyboard plans by
any change, and looking around (move, scroll, page/arrow keys) is never discarded
and is verified from pixels instead of a second inference. An input that changes
no pixels skips model verification and is settled by one later inspection. Rest
backs off 1→2→4→8→15 min and wakes, without inference, for a change that has
settled outside regions seen moving; a region she looked at and chose to ignore
is background until she acts. Unknown key spellings are normalized; an impossible
plan is diary feedback, not an error loop. `recently_done` keeps finished goals in
view.

**Shell and self.** Her own widget, tray menu and dialogs are refused targets
(Qt-published geometry, no OS window enumeration). The widget is status plus the
teaching button and never takes keyboard focus. Her self-image and the owner's
decisions about it are recorded in PERSONALITY_AND_LIFE.md.

Consequences: decisions take 8–14 s, reading costs one inference per page, idle
time costs none. Remote brains see screenshots of the owner's desktop; that is the
owner's choice of provider. Upgrades use `SOMA.exe --quit`, which aborts in-flight
inference and checkpoints within seconds.
