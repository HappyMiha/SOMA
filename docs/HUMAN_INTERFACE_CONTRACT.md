# HumanInterfacePort contract

Production application observation is `ScreenFrame`: PNG pixels, virtual desktop
size/origin, physical monitor rectangles, frame ID and wall/monotonic capture
times. There are no window titles, process IDs, OCR fields, DOM or accessibility
objects. Vision may infer semantics only from these pixels. SOMA's own machine
vision (`soma/vision.py`) is such an inference: it reads text and positions from
the captured frame's pixels inside SOMA, re-reading only regions whose pixels
changed; the port still supplies nothing but pixels.

Input primitives are mouse move/button/scroll and keyboard press/release. Closed
composites: click, double_click, drag, move, scroll, key, hotkey, type_text and
wait. A scroll may name x,y: the pointer moves there first and then the wheel
turns, as a hand rests over what it scrolls (a wheel turns what is under the
pointer); without x,y it turns where the pointer already is.
`type_secret` (account) and `type_new_secret` (service, login) are keyboard
events too: the kernel takes the password from SOMA's OS credential vault (or
makes a strong new one and keeps it there first) and the hand types it as
`type_text`. The brain names only the account; the journal, ledger,
verification and every prompt carry the account name, never the password,
and every known password is replaced by a placeholder in anything sent to a
brain. The hand refuses these two kinds if they ever reach it unresolved. Normalized coordinates reference the entire composite screenshot, including
negative desktop origins. Monitor gaps are rejected. Text is emitted as keyboard
events, never clipboard or direct field assignment. Held input is released on
exceptions, teaching, suspension and shutdown.

**Own-shell exclusion (0.2.0).** SOMA's widget, tray menu and dialogs (model
settings, backup, restore) are the product shell, not her environment. On the
first live run a small local VLM clicked her own "Резервна копія" button while
pursuing a self-made "recovery" goal; the same path could restore another
persona, stop her own life via "Модель" or toggle teaching. The GUI thread
therefore publishes the physical-pixel frames of SOMA's *own* visible Qt windows
and whether one is active (`OwnInterface`). `validate_action` refuses pointer
actions inside them (including every drag sample and a scroll at SOMA's last own
pointer position) and keyboard actions while one is active, before journaling or
emitting anything. File dialogs are Qt dialogs (`DontUseNativeDialog`) so the
whole shell is known to Qt; no OS window enumeration or foreground-window query
is used, and nothing about other applications is read. The kernel journals the
refusal as `own_interface_refused`, which cognition sees as a recent event.

Windows uses MSS screen pixels and pynput SendInput. Native desktop availability
is checked before capture and input; secure/locked desktops are not bypassed.
Linux/X11 uses MSS and explicit xorg input. Wayland is rejected before XWayland
could create a misleading partial implementation. A future portal adapter must
preserve this same port.

**Subscription CLI brains.** `soma/cli_brains.py` is one of the three reviewed
production modules allowed to start a process, and it starts only the Codex CLI or the Claude Code CLI
as an inference engine using the owner's own login (SOMA never reads their
credentials). Both are agents, so every tool is disabled (Codex: all tool
features off, read-only sandbox, empty working directory, no user config/rules,
ephemeral; Claude Code: `--tools ""`, `--strict-mcp-config`, project-only
settings in an empty directory, no session persistence, slash commands off).
Any tool activity in their event streams rejects the answer. `test_contract`
enforces the module exception and the flags. The other two: `soma/imaging.py`
starts only the painter's own engine with the prompt as one argument, and
`soma/brain_host.py` (2026-11-03) restarts only the world's local brain server —
`taskkill /F /T /IM "ollama app.exe" /IM ollama.exe`, then Ollama's tray app —
when `soma/health.py` finds the local model on the processor although it ran on
the graphics card here before (unloading it first; never while the painter holds
the card or while Ollama keeps models that are not SOMA's; at most once in two
hours). The self-diagnosis reads only SOMA's own state and the local server's own
HTTP API (`/api/ps`), no process list.

Inference HTTP is only cognition. SQLite, backups, configuration, tray singleton,
credential vault and power/session APIs operate on SOMA's own implementation.
None supplies application content. The source-level contract test blocks common
bypass imports/calls; this is a regression guard, not a security sandbox or an
exhaustive proof of transitive dependency behavior.
