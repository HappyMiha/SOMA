# Iterative implementation record — 2026-10-30

1. **Audit before implementation.** Cloned twelve candidates, read pinned licenses
   and current modules, ran isolated PoCs. Rejected whole agent runtimes that
   expose eval/exec, clipboard, DOM/UIA, window metadata, shell or application
   APIs. Selected native Qt + a closed body port and own durable cognition.
2. **Body and memory.** Built actual Windows/X11 capture/input, action validation,
   stable identity, six memory kinds, hash-linked event history, transactional
   action journal, checkpoints and portable backups/restore. Crash subprocess,
   corruption, atomicity and uncertainty tests drove corrections.
3. **Life and teaching.** Added autonomous planning, goal revision, semantic/social
   provenance, reflection/experience skills, pixel feedback and adaptive rest.
   Teaching immediately inhibits input, invalidates old inference and records
   only visible-mode pixels/events. Private gaps omit both. Incremental journal
   recovery preserves partial observations without replaying them.
4. **Live device loop.** Windows owned fixture passed real input/capture at actual
   200% DPI. Unicode ordering required per-character pacing. Isolated Linux/X11
   fixture passed; its first actual RECORD listener shutdown failure required a
   separate control connection+flush. Mocks were never counted as physical GUI
   success or model skill transfer.
5. **Lifecycle regressions.** Tests caught rapid suspend/resume input inhibition,
   shutdown busy-spin, lock/sleep reason conflation, stale lesson requeue,
   privacy-timestamp races, swallowed hook errors, portable frame-path mismatch
   and reconstruction memory growth. Corrections have regression coverage.
6. **Packages.** Built Windows Inno installer and Linux .deb with a bundled runtime,
   licenses/SBOM/checksums. Native packaged smoke exposed a Windows Poppler ICU
   collision absent in source execution; excluded that DLL and added a PE guard.
   Linux packaging uses native temporary staging, correct ownership/modes and
   explicit glibc/XCB dependencies. Platform reports record final scopes/hashes.

7. **0.2.0 — first real local brain (2026-10-30, SOMIK i7-1255U, CPU-only
   Ollama 0.40.13, `qwen3-vl:4b-instruct`).** The installed 0.1.0 logged a
   `ProviderError` every minute and completed 0 cycles. Measured causes:
   * Ollama's OpenAI-compatible route ran with a 4096-token window and silently
     truncated a 33 kB context (1336 prompt tokens accepted), so the reply lacked
     the schema fields;
   * a pending 11-input demonstration was relearned before every cycle with 8
     screenshots (~1050 tokens each), which can never fit;
   * one screenshot costs ~100 s of CPU prefill, text ~21 tok/s, generation
     ~8 tok/s, while the config capped inference at 120 s.

   Corrections: native Ollama dialect (auto-probed `/api/version`) with explicit
   `num_ctx`, per-kind JSON-schema constrained decoding, `keep_alive`, static
   instructions moved into the cacheable system prefix (repeat call 240 s → 73 s);
   refusal instead of silent truncation; compact cognitive context (1 kB instead
   of 33 kB); per-mille grounding for Qwen/UI-TARS; single AFTER image plus the
   model's own BEFORE scene for local verification; local timeouts up to 900 s;
   undigestible lessons back off instead of blocking life; inputs whose outcome
   three inspections cannot establish become `unresolved` rather than an
   infinite quarantine. A live dry decision (no input) produced a valid,
   visually grounded plan. 118 tests pass.

8. **0.2.0 live autonomy (owner-approved, same day).** Installed over 0.1.0 with
   app+persona backups in `%LOCALAPPDATA%\SOMA-backups\`. Live findings drove
   three fixes: the own-shell exclusion (her first autonomous click opened her
   own backup dialog), an adaptive settle window (a late dialog was judged
   "no change"), and `SOMA.exe --quit` for upgrades that checkpoint instead of
   being killed (installer `PrepareToInstall` and uninstaller call it). Recall
   gained a derived character-trigram vector index, rebuilt for older memories.

9. **Semantic review against the owner's original intent** (the ChatGPT
   conversation that produced the spec). Letter matched, meaning did not: SOMA
   was perceiving her own implementation (errors, recovery) and formed goals
   about it; nothing drew her to correspondence, her own identity or people's
   tasks; the widget had become a control panel; first run required a wizard.
   Corrections: cognition receives a first-person diary of lived events
   (telemetry such as provider errors, discarded plans, checkpoints and frame
   captures is excluded) and a first-person system prompt describing her life
   (messages first, reply in the same program, tasks done at her PC, own
   openly digital identity via GUI sign-ups, curiosity, rest); failures no
   longer overwrite her intention; the widget is status + "SOMIK, дивись"
   with housekeeping in the tray; first run adopts a pulled local vision model;
   remote OpenAI-compatible brains get a persisted daily request budget
   (hybrid falls back to local) and `max_completion_tokens` for api.openai.com.
   `SOMA.exe --quit` verified live: checkpoint + `sleep`, exit 0.

10. **Subscription brains and the first real conversation.** The owner asked to
    use existing Claude/Codex logins. Both CLIs are agents, so they run as
    tool-less brains (contract-tested exception module `cli_brains.py`). Codex
    (logged in) produced 8–14 s decisions; with it SOMA read a Telegram message
    and replied by keyboard, verified from pixels. Live fixes on the way:
    pointer plans are now invalidated only by change near their target
    (keyboard plans still by any change); the status widget never takes the
    keyboard and sits in a corner; closing the brain aborts in-flight requests
    so `--quit` takes ~2 s.

11. **Machine vision.** The owner asked for machine vision instead of sending
    every screenshot. SOMA now reads her own frame's text with positions
    (offline PP-OCRv5 Cyrillic via RapidOCR/ONNX, ~10 s per full screen on this
    CPU) and decides from that text on routine steps; the picture still goes on
    the first step, on request, every 4th step, on geometry change or when
    little text is readable. This is computation over SOMA's own pixels only —
    no application text, UI tree or API. The first live decision overflowed the
    local 8k window; screen text for the local brain is now fitted (long lines
    shortened, middle lines dropped, the omission stated in the context).

12. **Not wasting the slow brain's time.** Measured first (Ollama's log and
    tokenizer, OCR stage timings), then changed what the numbers showed:
    the context is written for thinking rather than storage (relative times,
    local clock, no internal ids, memories in plain words, inputs in her own
    clicking coordinates, least-changing parts first so the prompt cache
    reuses them) — 3,298 → 1,676 tokens with every fact kept; goals are g1,
    g2… to the brain and a continued goal needs only its id; the token budget
    follows the tokenizer's real shape (the old flat ratio refused every
    decision live); machine vision re-detects only changed regions, never
    re-recognizes a line it already read (also after scrolling) and skips the
    orientation pass; an input that changed readable text is verified from
    that text without a picture.

13. **Honest eyes and habits.** Live, every scroll had counted as a success
    because some pixels changed, and she scrolled one finished page for two
    hours. Scrolls are now verified by whether the text moved (or, after a
    long jump, whether the column she scrolled shows new content), and the
    hand can scroll at a point, as a person rests the mouse over what they
    read. A decision may turn a looking-around plan into a habit that repeats
    without new thought until a step fails or something new appears; the next
    thought is told what she read meanwhile. Nothing that acts on the world
    ever repeats.

14. **A GPU and each brain its own job.** The owner connected a GTX 1060
    over USB4 and signed Claude Code in. Ollama was restarted to find the GPU
    (CUDA 12 build; CUDA 13 dropped Pascal) and its KV cache set to q8_0 so
    the whole model fits in VRAM. Three local brains were compared on her own
    real requests; qwen3.5:4b won (twice as fast as qwen3-vl:4b, all answers
    valid, grounded in the current screen). Claude takes the moments that
    need judgment — waking, something new, conversations, reflection,
    learning — and the local GPU brain the routine, with Codex as stand-in.
    The schema now lets a small model continue only goals that exist and
    never forget a new goal's motive.

15. **Her accounts are part of who she is.** She had forgotten her own
    mailbox and kept an invented password in plain memory. She now always
    sees her accounts (never their passwords), her hand types passwords
    from the OS vault by naming the account, new passwords are made strong
    and kept before they are typed, no brain ever receives a known
    password, and her owner has a window to see, fix and add accounts while
    she keeps her eyes closed.

16. **A living avatar of her own.** Her look shows her inner life in three
    layers she sets herself — feeling, the world she lives in (a scene her
    deep brain paints as inert SVG) and who she is — with every look kept.
    The first visual version was honestly clip-art; the second follows
    Material 3 Expressive (morphing shapes, bold colour, spring physics,
    expressive type) on an opaque Windows 11 card. On her own she became "a
    curious night-sky reader" under Cassiopeia's stars.
17. **Pixel art, a person, and a painter on the GPU (2026-10-31).** The owner
    asked for pixel-art avatar and scenes (three example videos: moody
    pixel scenes with people in them, small living details), then for human
    builds. First, all in code (soma/pixels.py): every world reduced to a
    pixel grid and a small palette without dithering (skies fall into
    bands), ambient life (stars, snow, rain, fireflies, petals, dust,
    birds), emote balloons, and her figure as a person of about seven heads
    with her own build, hair, skin, clothes and accessory, posed by what she
    does and feels (from behind looking up when dreamy, a hand to her chin
    while thinking, a book while learning, arms up in a hop of joy). Asked
    to compare honestly with the owner's example, the drawn-in-code figures
    were programmer art next to hand-made pixel art. So the avatar's main
    look became a painting of her in her world by SDXL-Lightning on the
    GTX 1060 (stable-diffusion.cpp Vulkan, ~4 GB VRAM, 1344×768 in 63 s with
    the tiny SDXL autoencoder instead of 107 s with the tiled VAE), shown at
    228×108 art pixels with 40 colours. The owner: "ООО, значно краще!" The
    image model kept leaving her out when she was described as "a person",
    even first in the prompt; see TEST_RESULTS.md. The code-drawn figure and
    SVG scene remain the fallback while she is painted or without a GPU.
18. **The people she knows (2026-11-01).** Her owner wrote to her in Discord
    from two accounts, his own and his son's, and asked whether she would
    remember who is who. Her social memories held the facts, but a memory
    came to mind only when her intention happened to name the person. Now a
    registry like her accounts (soma/people.py, events person.recorded /
    person.noted / person.note_retired): everyone she knows (p1 …), who they
    are to her, their accounts by service and handle, confirmed (on evidence
    from a channel she already trusts) or only claimed, and her own notes
    about each one (n1 …), shown in every decision, the latest news first.
    She keeps it with people_updates in decisions and dreams; a note no
    longer true leaves her context, never her history. Her owner reads and
    corrects it in the tray window "Люди SOMA…"; what the owner says there
    counts as confirmed.
19. **SOMA, the world, and SOMIK, its inhabitant (2026-11-01).** The owner
    closed an architectural gap: SOMA is the system, like a world; SOMIK is
    one personality living in it, and more will come. ADR-004: the world
    keeps the body, brains, painter, widget and world.json; each inhabitant
    has a home inhabitants/<persona id>/ with memory, frames, accounts
    (their own vault names), people and look; who they are is their
    identity as born plus identity.profile events. The live SOMIK moved in
    by journaled renames with id and history unchanged; the prompt now says
    "You are SOMIK … you live in SOMA, the world on this PC".

Final commands:

```powershell
.\.venv\Scripts\python -m pytest -q --basetemp=artifacts/test-tmp
.\.venv\Scripts\python packaging/build.py --iscc .tools/inno/ISCC.exe
.\.venv\Scripts\python packaging/check_windows_bundle.py dist/win32/SOMA
.\.venv\Scripts\python packaging/smoke_runtime.py --executable artifacts/win32/install-test/SOMA.exe --output docs/evidence/windows-package
```

Linux: `.venv-linux/bin/python -m pytest -q --basetemp=artifacts/linux/test-tmp`,
then `xvfb-run -a env -u WAYLAND_DISPLAY XDG_SESSION_TYPE=x11 .venv-linux/bin/python packaging/build.py`.
The normal build command on a real X11 session needs no Xvfb. End users install
the packages and use the native widget; they do not execute these commands.

The full specification DoD remains open until real model/service/hardware and
endurance acceptance gates pass. See IMPLEMENTATION_STATUS.md and TEST_PLAN.md.
