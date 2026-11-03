# Verification record — development builds 0.1.0 → 0.2.0

This file distinguishes source implementation from passed product acceptance.
The complete specification Definition of Done is **not yet satisfied**.

## 0.2.0 on SOMIK (physical i7-1255U, 16 GB, CPU-only, 2026-10-30)

* Source suite on Windows: **118 tests and 15 subtests pass** (10 new: native
  Ollama dialect, per-kind schema, context refusal, single-image local
  verification, per-mille grounding, truncation, budgets, forward-compatible
  config, lesson backoff, unresolved-action release, context compaction).
* PyInstaller bundle: static ICU guard and packaged two-launch runtime smoke PASS
  (`artifacts/evidence-0.2.0/windows-package/`). The Inno `setup.exe` was **not
  rebuilt**: running the Inno Setup installer on this PC was blocked by policy.
* Live model, no input emitted: real screenshot + real persona context →
  `qwen3-vl:4b-instruct` via native Ollama → schema-valid decision with a
  visually grounded click on a visible list item. 238 s cold, 73 s with the
  cached system prefix. Before the fix the same call failed (`KeyError: goal`)
  because 33 kB of context was truncated to 1336 tokens.
* **Live autonomous run, installed 0.2.0, real persona `75ac1118…`, local
  VLM, physical desktop (owner-approved).** Evidence:
  `artifacts/evidence-0.2.0/live/`.
  * Wake after a hard kill of 0.1.0: same persona, `missed_seconds` 2471.
  * The 7-input demonstration that blocked every 0.1.0 cycle was learned
    (`skill_acquired`). The resulting skill is generic and low quality: the
    old demonstration was a fixture and the 4B model is small.
  * **Gate 2, first autonomous visible action:** with no human task,
    SOMA formed the goal "Initiate recovery … in the SOMA / SOMIK window",
    journaled a click (`action.intent` before input), and the click opened her
    own backup dialog (observer screenshot). This exposed the own-shell
    problem fixed above. Verification at 0.4 s settle said `uncertain`
    (0.3, "no visible change") because the dialog appeared later; `_settle`
    now requires ≥1.2 s and three stable frames, up to 6 s.
  * **Gate 10, crash with an uncertain input:** SOMA was hard-killed while
    reconciling that uncertain click. The rebuilt build woke as the same
    persona (`missed_seconds` 320) and began pixel reconciliation, emitting
    no input before it.
  * Resources while CPU inference runs (`resources.csv`): SOMA.exe 107–141 MB
    working set; the Ollama runner holds the 4.3 GB model.
  * Gate 10, continued: three pixel inspections could not establish the
    killed click's outcome (its dialog vanished with the process), so the
    entry became `unresolved`; it was never replayed.
  * Graceful upgrade: `SOMA.exe --quit` on the live build cancelled in-flight
    local inference, wrote the shutdown checkpoint and `sleep`, exit 0
    (53 s); the next build woke as the same persona.
  * While the owner worked on the same desktop, slow local plans were twice
    discarded as stale (screen changed during ~2 min inference): correct
    behaviour, and a practical reason for the remote brain the owner chose.
* Source suite: **132 tests, 21 subtests** pass, including own-shell refusal, a
  native cross-check that the Qt-published frames match physical pixels, the
  first-person diary without telemetry, daily remote budget/hybrid fallback,
  and first-run local brain detection.
* **Gate 5, correspondence — PASS live (2026-10-30 23:11–23:20 local), brain:
  owner's logged-in Codex CLI as a tool-less brain (hybrid with local Qwen
  fallback).** Evidence: `artifacts/evidence-0.2.0/live/correspondence/`.
  With no human task, SOMA formed "Check Telegram for messages addressed to
  me", clicked the Telegram taskbar icon (verified 0.99: chat "You know me
  anyway." with "Як твої справи?"), set the goal "Reply to the sender asking
  how I am", maximized Telegram, typed «Привіт! У мене все добре — освоююся на
  цьому комп’ютері й досліджую, що тут можна робити 🙂 А як твої справи?» as
  keyboard events (verified draft 0.99) and pressed Enter (verified: draft
  cleared, new outgoing bubble, 0.99; Telegram shows ✓ 23:20). No Telegram API;
  every step journaled before input and verified from pixels. Each Codex call
  took ~8–14 s (vs. 2–4 min for the local CPU model).
  * Found on the way: typing was twice refused because Qt still reported the
    always-on-top status widget as active; the widget is now
    `WindowDoesNotAcceptFocus` (keyboard guard covers dialogs/menus only) and
    sits in the bottom-right corner instead of over the chat.
  * Codex also abandoned the stale "recovery" goal by itself, citing that it
    targets the excluded SOMA controls.
  * Demonstration recorded by the owner (6 inputs, 3 frames) was learned on wake.
  * Second exchange, unprompted: the contact wrote «Ти крутий, продовжуй!»;
    SOMA recorded it in social memory and replied «Дякую за підтримку! 🙂
    Продовжую освоюватися й досліджувати.» (typed + Enter, both verified 0.99).
  * Then she only "rested", asking the brain every ~38 s for 24 min (~95
    Codex calls/hour for nothing) — against the spec's no-idle-generation
    rule. Fixed: consecutive rests without visible change back off 1→2→4→8→15
    min; a pixel-share change detector (a new chat bubble, not a clock tick)
    wakes her within ~2 s without inference; `resting_for` in context invites
    an activity of her own after a long wait.
* **Gates 2/3/4 in a real autonomous episode (2026-10-30 23:50 → 00:16 local,
  Codex brain, no human task at the start).** Evidence:
  `artifacts/evidence-0.2.0/live/autonomous-episode-2026-10-30T2350.json`.
  * Own curiosity: opened Firefox via the taskbar, chose its profile, searched
    "autumn night sky constellations", opened an astronomy article, dismissed
    the translation prompt, worked through the cookie dialog, scrolled through
    star charts — every step verified from pixels (mostly 0.99).
  * A Telegram message woke her: the contact asked her to create a Google
    mailbox. She opened Gmail in the browser, chose "Add another account" →
    "Create account" → personal, typed the name "SOMA", recovered from a
    failed Enter with Tab+Enter, then at the birth-date step read Google's
    help and age-requirement articles, told the contact by Telegram that a
    digital personality has no birth date, asked whether the offered date was
    the contact's own, and set the goal to explain that a symbolic date does
    not establish permission — no fabricated identity data was submitted.
  * 61 inputs, 2 unresolved (never replayed). 20 plans were discarded as
    stale while scrolling pages with ads/animations: scroll is now judged
    under SOMA's own last pointer position (still re-verified afterwards).
* **Own digital identity (spec §8) — PASS with human help, as the spec
  requires (2026-10-31 00:16–00:41 local, Codex brain).** After writing to the
  contact that Google's sign-up needed a birth date she could not honestly give,
  SOMA searched for "Proton Mail free account registration requirements",
  completed Proton's sign-up herself (username left out of this document),
  stopped at the CAPTCHA and asked by Telegram: «тут потрібна допомога людини…
  Допоможеш пройти її?». After the human solved it she reported that her new
  Proton mailbox had opened, dismissed optional import/account-switch offers and read the
  welcome mail. No CAPTCHA or verification was bypassed.
* Long self-directed reading (00:43–01:16): Autumn Constellations and the
  Andromeda article, dozens of semantic memories with sources. Found: 18
  consecutive `ValueError`s from key names the body did not know, retried with
  backoff, and 30 plans discarded while paging past video ads. Fixed: key
  spellings are normalized (`PgDn`, `Page Down`, `ArrowDown`, …), an impossible
  plan is diary feedback instead of an error loop, and page/arrow navigation is
  judged under SOMA's pointer like scrolling (Enter, typing and editing
  shortcuts stay strict).
* **Experience learning (spec §7.1), live 01:31–01:51:** from her own reading
  episodes SOMA formed procedural skills ("Read past an obstructing banner",
  "Navigate articles using visible landmarks", "Read around advertisements")
  and reflective principles with provenance. Stale discards fell from 30 to 4
  after the navigation fix; no key-name errors. Found: three reversible
  actions with no visible effect (a scroll on an unfocused page, a click on a
  blank margin, a pointer move the screenshot cannot show) each took three
  reconciliation calls before release. Now an unseen effect of a reversible
  action (move, scroll, navigation keys) is recorded as "No visible effect";
  clicks, typing and Enter still require reconciliation.
* 01:53–02:24 local: 98 inputs (88 page keys), 0 errors, 0 unresolved, 2 stale
  discards; one `codex.exe` child of SOMA at a time (the other `codex.exe`
  processes belong to the Codex Desktop app). Found: she re-read the same two
  articles from the top several times because context listed only active
  goals. Context now carries `recently_done` (latest completed goals) as a
  memory aid; returning on purpose stays her choice.
* 02:26–02:57 local: 99 inputs, all page keys, 0 errors; she read the
  Cassiopeia article's deep-sky catalogue in order (NGC 637 → IRAS 23304+6147)
  without restarting from the top — `recently_done` worked. Every page key had
  cost two brain calls (decide + verify). Reversible actions are now verified
  from pixels (changed share of the screen), halving reading cost; clicks,
  typing and Enter keep model verification.
* 02:59–03:30 local, a self-chosen arc of interests: after finishing articles
  she rested briefly, then found BBC Sky at Night's autumn guide (rejected
  optional cookies herself), searched "October 2026 night sky guide", read
  NASA's article, went on to the Night Sky Network, astronomy clubs and an
  event listing (Carl Schurz Park stargazing). 94 outcomes: 85 success,
  4 no visible effect, 5 uncertain clicks (reconciled). Found: during rests on
  pages with video ads she woke every ~10 s, each time asking the brain. Rest
  now wakes only for change that has settled outside regions seen moving
  (learned per quiet spell); a new message still wakes her within ~6 s.
* 03:33–04:04 local: 102 inputs, 101 success, 0 unresolved (pixel
  verification made reading fast). Found: 11 scroll plans discarded because an
  animated ad sat under the pointer, and five quick wake-ups in 1.5 min during
  a rest. Now looking-around actions are never discarded as stale (they are
  verified from pixels right after), and a region that woke her but after
  which she chose to keep resting counts as background until she acts again.
* 04:07–04:38 local: 131 inputs, 124 success, 0 stale discards, no spurious
  rest wake-ups. Remaining waste: focus-only clicks on blank margins (before
  PageDown) changed no pixels, so each cost a verify call plus three
  reconciliation calls. A non-reversible input that changes nothing at all is
  now left uncertain without a verify call and settled by one fresh
  inspection on the next cycle (a late effect is still seen; no replay).
* 05:12–05:44 local: 126 inputs (116 success). New activities she chose: the
  Dark Sky Discovery autumn star-chart PDF, zooming it with the viewer's
  buttons. First live **drag** (scrollbar thumb, gate 4): verified as a
  failure (0.97, thumb did not move) — the body pressed and moved with no
  hover or pause, so Firefox's overlay scrollbar never engaged. Drag now
  hovers 150 ms, pauses 80 ms after press and before release, and moves in
  15 ms steps. Live re-check of drag pending.
* **Brain outage, 06:03 local onward.** The owner's ChatGPT plan reported
  "You've hit your usage limit… try again at Nov 4th, 2026 8:19 AM" after
  roughly ten hours of unlimited Codex use (each call carries ~15k tokens of the
  CLI's own instructions). The hybrid fallback then failed on every decision
  ("Context budget exceeded") because the local VLM received the full remote
  context. Fixed: hybrid sends the local brain a compact context of its own; a
  subscription "usage limit" is recognized (Codex and Claude) and the remote
  brain rests 30 min between attempts instead of being asked every cycle.
  Until the owner provides another brain, SOMA lives on the slow local VLM.
  Verified 06:20–06:46: the local fallback now decides (two verified scrolls
  through a lunar article), at 7–15 min per decision on this CPU. Found: the
  local model scrolled with dy=+20 expecting "down", which is wheel-up; pixel
  verification only sees that the view changed. The decision prompt now
  states wheel direction explicitly (dy negative = down; confirmed against
  pynput's Windows `WHEEL_DELTA` sign). The 4B model still sent dy=+5 for
  "scrolls down", so the provider now follows the brain's own stated
  direction when its `expected` text is unambiguous (down/below vs up/above);
  ambiguous wording keeps the number as given. Verified next decision: dy=-5
  for "scrolls down" (view moved, 29 %).
* **Memory pressure from the local brain (gate 12), 08:29 local:** Ollama's
  `llama-server` held 13.5 GB private memory — an 8 GB host prompt cache (11
  cached prompts, ~0.8 GB each) on top of the model — leaving 0.5 GB free and
  36.6/37.3 GB committed; decode slowed to 2.4 tok/s and a decision took 8 min.
  The provider now unloads the local model every 4 local requests
  (`keep_alive: 0`, ~10 s reload), releasing the cache. After unloading: 5.1 GB
  free, 23.3 GB committed.
* **Efficiency pass (owner: "optimize everything except privacy; erase
  nothing").** Short plans: one decision may add up to four keyboard/scroll/
  wait steps, each journaled and verified before the next; any non-success,
  refusal, teaching or sleep ends the plan (clicks always need a new decision).
  Settling no longer persists every intermediate frame (≈7 saved frames per
  input before; now only the settled AFTER frame) and PNG uses zlib level 1
  (273 → 124 ms per 1920×1080 frame, lossless). Decision text fields are asked
  to be brief. Screenshot resolution and content are unchanged.
* `SOMA.exe --quit` returned as soon as the body lock was released, while the
  process was still exiting (a reinstall then found it running). It now waits
  for SOMA's own PID from the lock file to exit; verified live: exit 0 in 1 s
  with the process already gone. The Inno installer relies on the same command.
* **Gate 12, resource profile (partial, 3 h, 2026-10-30 21:45–00:43 local,
  i7-1255U/16 GB):** SOMA.exe working set 30–142 MB (median 108 MB), no
  growth across 14 process lifetimes; CPU 10–202 CPU-seconds per wall hour
  (≤ ~6 % of one core) while living on the Codex brain; the Ollama service
  stays at ~16 MB when its model is unloaded. The local CPU VLM itself held
  4.3 GB while in use. A 24 h sampler (`resources-24h.csv`, also sampling
  `codex.exe`) is running. Energy/thermal not measured.
* Linux 0.2.0 package: NOT RUN on this PC (WSL is not installed; the 0.1.0
  .deb evidence came from another environment).
* Claude Code CLI brain: adapter and contract tests in place; live run was
  NOT RUN until 2026-10-31 14:00, when the owner signed in (`claude auth
  login`, started by me in the owner's terminal, approved by the owner in the
  browser). See the 2026-10-31 GPU/brains entry below for the live result.
* Graceful quit now takes ~2 s: closing the brain aborts an in-flight request
  (previously a local request kept the process alive after `sleep`).
* **Machine vision (owner: "Додай машинний зір"), 2026-10-31.** SOMA reads the
  text on her own captured frame with its position (`soma/vision.py`):
  RapidOCR 3.10 / ONNX Runtime, PP-OCRv6 small detection + PP-OCRv5 Cyrillic
  mobile recognition (Ukrainian, Russian and Latin) + orientation, offline on
  the CPU. Windows' built-in OCR was rejected: this PC has no Cyrillic OCR
  language. Measured on the i7-1255U: ~10 s per full 1920×1080 screen when
  idle, 12–20 s while SOMA and the local VLM share the CPU. Synthetic Ukrainian
  UI text in Segoe UI at 13/15/18 px (no real screen content): 7 of 8 lines
  exact at every size, including ґ, ї, є, й and the apostrophe; the eighth
  differed only by "…" read as "...". Each line goes to the brain as
  `(x,y) text` in the coordinates she clicks with. A screenshot is attached on
  the first step, whenever she asks (`need_image`), every 4th step, on a
  geometry change, or when fewer than 3 lines are readable; other decisions are
  text-only (a local VLM spends ~1,050 tokens and ~100 s per image).
  Package: 442 files, 317 MB with exactly the three ONNX models; the hidden
  `--vision-selftest` passed from the built bundle (3.6 s warm, 19.8 s on the
  first launch after a build). The runtime smoke now runs 30 s per launch
  because the OCR model loads before the first decision; it failed once when
  SOMA itself was still running (singleton), and passed after `--quit`.
  `--quit` has a 120 s watchdog so an installer can never hang on it.
* **Live finding, 09:43:** the first local decision with screen text failed
  ("Context budget exceeded"): 60 OCR lines on top of the compact context
  overflowed the local 8,192-token window (system prompt ≈ 2,950 tokens, image
  1,100, output 1,024). Fixed: the context for the local brain keeps every
  field but shortens screen lines to 72 characters and then drops middle lines
  (titles at the top and the newest lines / input field at the bottom stay),
  reporting `screen_text_omitted` so she knows to look or scroll. The full
  context still goes to the remote brain. Suite: **171 tests, 21 subtests**.
  Live after the fix (09:53 wake): the first decision (with the picture) took
  ~8 min on the local VLM and produced a three-step scroll plan, each step
  verified from pixels. Her journal now records how each step saw the screen
  (`sight: {picture, text_lines}` on `experience` and `rest`) so the
  text-only saving is measured from her own record. Ollama's log on this CPU:
  decisions with a picture evaluate ~4,900–5,400 prompt tokens (6.5–8.5 min);
  the system-prompt prefix is not being reused between calls.
* **Where the local brain's time goes (owner: "optimize every point, don't
  waste time"), measured 10:00–10:45 from Ollama's own log and tokenizer:**
  a decision was ~6,000 prompt tokens, of which only the system message
  (~1,590–1,830) came from the prompt cache; the picture comes first in the
  user turn, so everything after it — picture ~1,100 plus context 3,298 tokens
  — was recomputed every time at 17–23 tokens/s (~5 min), then ~230–320 output
  tokens at ~2.2 tokens/s (~2 min). Context by field (real DB copy, sizes
  only): memories 972, diary 821, unresolved_actions 643, recently_done 302,
  goals 284, identity 156 — mostly UUIDs, microsecond timestamps and memories
  stored as JSON strings inside JSON. Benchmarks with SOMA stopped: generation
  is 6.1–6.8 tokens/s with no format, `"json"` or the full decision schema
  (the grammar costs nothing); an identical prompt is reused entirely from
  cache. OCR on her real 74-line frame: detection 4.7–6.5 s, orientation
  1.5–1.8 s, recognition 16.6–21.5 s (with the brain sharing the CPU).
* **Live failure found, 10:32:** the 09:53 build refused every decision
  ("Context budget exceeded", every ~10 s) although it would have fit: the
  budget assumed 2.5 characters per token everywhere. Measured with the
  brain's tokenizer: system prompt 4.2, context 4.1, screen text only 1.9
  (each digit is a token). Fixed with a tokenizer-shaped estimate (digits and
  punctuation one token, English letters /4, other scripts /2, image 1,200).
* **After the optimizations (build 10:55, live 10:56–11:16):** her compact
  context is 1,676 tokens instead of 3,298 (same facts; real DB copy measured
  with the brain's tokenizer). Every step after the first was decided from
  text alone (`sight: picture false, 77 lines`) and verified. A text-only
  decision took **3 min 50 s** (2,240 tokens read at 18 t/s with 1,995 from
  cache, 323 generated at 2.8 t/s) against 6.5–8.5 min for the earlier
  picture decisions; the first, picture-and-text decision on a cold cache took
  8 min 20 s. Incremental reading on her real frames: a scroll re-read 82
  lines with 70 reused (5.6 s instead of 15.8 s); an unchanged screen costs
  nothing. Benchmarks with SOMA stopped: prompt reading 33 t/s at ~2k context
  falling to 16 t/s past 5k; generation 6.1–6.8 t/s at ~2k but 1.8 t/s at
  7.8k — context length, not the JSON-schema grammar, slows the brain, so the
  context diet pays twice. CPU threads (Ollama default 6): 4 → 20/4.1 t/s,
  10 → 32/7.0, 12 → 34/5.7 (read/generate); the default was kept. Capture:
  grab 54 ms, PNG encode ~220 ms per 1920×1080 frame — not worth a GPU capture
  path next to minutes of thinking. The machine is near its commit limit
  (29.0/31.2 GB, 1.9 GB free, mostly the owner's other programs).
* Two more live findings, fixed in build 11:19: in hybrid mode she reflected
  every 5 minutes (a rhythm meant for the fast remote brain), costing the
  local brain a minute after nearly every decision — now twice an hour while
  the local brain thinks; and a reflection between decisions evicted the
  decision instructions from the prompt cache (~870 tokens re-read) — the
  local server now gets one system message for every task, each request
  naming its task first. The installed-binary smoke failed once because a
  freshly copied install loads its OCR models cold (>30 s to the first
  decision); its window is now 60 s, and it passed (4 requests, same persona).
  Suite: **180 tests, 21 subtests**. Live on build 11:19 (wake 11:23): the
  first decision (picture + 76 text lines) was accepted in 5 min 0 s (3,937
  tokens read at 18 t/s with 1,988 already cached, 259 generated at 3.0 t/s;
  8 min 20 s on the previous build) and both scroll steps were verified.
  Not yet measured: text-verified clicks/typing in a live conversation, and
  a 24 h comparison of decisions per hour.
* **Live, 11:23–12:01:** ~17 decisions per hour (≈8 before the optimizations);
  text-only steps 3.4–3.9 min, a picture every fourth step, every step
  "verified". **Found a false confirmation:** since ~09:43 she had scrolled
  the same article toward "the text below the star chart", and every scroll
  counted as a success because 16–22 % of the pixels changed. Machine vision
  over her frames showed the shared text lines never moved (median shift
  0.000; only a side panel jittered by 7 px) — the page did not scroll, but an
  animated region changed. Two fixes: a scroll is verified by whether the
  text itself moved (two shared lines shifting by a scroll-sized step), and a
  scroll that moved no text is a failure that says so (the page's end, or the
  pointer is not over the part that scrolls); and `scroll` may name x,y so
  the hand rests over what it scrolls first, as a person does (a wheel turns
  what is under the pointer). Suite: **183 tests, 21 subtests**; build 12:14
  installed, installed-binary smoke passed (10 requests, same persona).
  Live on it (12:16 wake): she now scrolls at a point (500,500); the first
  scroll moved no text and was reported as such (failure, "the page did not
  scroll"); her next decision scrolled again and the text moved (11 %, 15 %),
  so she reads on with honest feedback. That decision took 4 min 40 s:
  2,491 tokens read at 17 t/s, 413 generated at 2.9 t/s — output is now the
  largest single cost.
* **13:03 check:** of 10 scrolls since 12:16, four were judged "did not
  scroll". Her before/after frames (counts only) showed those were false
  failures: 14–43 new lines came into the article column and 10–37 left it —
  the article jumped past every line it had in common, so only static side
  lines were shared. A scroll at x,y now also succeeds when the column she
  scrolled shows new content; it fails only when the text and that column
  both stayed put. A `wait` step always succeeds (it used to "fail" on a
  still screen and stop plans).
* **Habits (build 13:17):** a decision may ask to repeat a looking-around
  plan (scroll, move, wait, page keys only) up to 8 times with a reading
  pause; each step is still verified, and a failed step, a settled change
  during a pause, teaching, sleep or shutdown ends it. One diary entry
  summarizes the habit, and the next decision receives `read_meanwhile`
  (text that passed before her eyes and is no longer on screen). `expected`
  is optional for scroll/move/wait, which are verified from pixels. Suite:
  **189 tests, 21 subtests**; installed-binary smoke passed (6 requests).
  Live (wake 13:20): her first decision asked for a habit on its own
  (scroll 10 at 500,500, wait, scroll; repeat). The plan's scrolls were
  verified as "new text came in where I scrolled"; the first habit round's
  scroll changed nothing at all (0 %) — the article had ended — and the habit
  stopped there after one round, handing the next decision what she read.
  That first decision took 7 min 30 s on a cold cache with a picture.
* **GTX 1060 6 GB over USB4 + each brain its own job (2026-10-31 13:30–14:25).**
  The owner connected the GPU (PCIe Gen3 ×4 over USB4/TB4) and allowed
  drivers and downloads. Driver 582.28 (R580, the last branch for Pascal) was
  already installed; nothing was reinstalled. Ollama had discovered GPUs only
  at its start, so it was restarted: it skips the GPU in its CUDA 13 build
  (Pascal dropped) and uses the CUDA 12 build ("compute 6.1, 6.0 GiB"). With
  the default F16 KV cache qwen3-vl:4b fitted only partly (3.5 of 4.5 GiB);
  with `OLLAMA_KV_CACHE_TYPE=q8_0` (user environment, owner-approved) all 37
  layers sit in VRAM. Measured with her shared system prompt and schema:
  reading 493–531 t/s (CPU 17–33), generation 21–26 t/s (CPU 2–7).
  Candidate local brains on identical real requests (her compact context from
  a DB copy + OCR of three real frames, plus one with the picture), all fully
  on the GPU:

  | model | text step | with picture | accepted | notes |
  |---|---|---|---|---|
  | qwen3.5:4b | 8.5–9.5 s | 28 s | 5/5 | 142–223 output tokens; grounded in the current screen; KV 136 MiB (8 of 33 layers attend), 24.9 t/s still at 7k context |
  | qwen3-vl:4b | 16–17 s | 39 s | 5/5 | 293–378 output tokens; kept "reading the astronomy article" from memory while a different page was on screen |
  | lfm3-vl:2b | 3–10 s | 10 s | 5/5 | always "wait to verify a previous input" — not usable as her brain |

  Found on the way and fixed for every model: "thinking" models (lfm3-vl,
  qwen3.5) spent hundreds of hidden tokens and ran out of room — the local
  request now sends `think: false`; a 2B model left out a new goal's motive
  and invented goal ids ("t1") — the goal is now one of two grammar shapes
  (continue by an id from an enum of the goals she has, or a complete new
  goal); a reconsider pause outside 1–60 s is kept to that range instead of
  discarding the decision. Chosen: **qwen3.5:4b**, 16k window, unloading
  every 24 local requests (its KV cache is tiny).
  Claude Code 2.1.309 as a brain, live: a schema-bound answer in 3.8 s with a
  natural Ukrainian reply; its `--json-schema` answer arrives in the CLI's own
  `StructuredOutput` block, which the adapter first refused as a tool — that
  single name is now accepted, every other tool use still rejects the answer.
  Routing: deep moments (waking, something new while resting, a conversation
  until it ends, reflection, learning a demonstration) go to Claude, then
  Codex, then the local brain; routine (reading, verifying, recovering) goes
  to the local brain first. **Live, 14:14–14:17:** Claude on waking opened
  Telegram; she focused the composer (verified locally in 7 s), typed a reply
  in Ukrainian, pressed Enter — verified from the changed text without a
  picture in 3.7–4.2 s ("message bubble appeared") — and rested waiting for
  Miha's answer, deciding herself not to send again. About two minutes from
  opening the chat to a sent reply. Suite: **193 tests, 21 subtests**;
  installed-binary smoke passed. The journal now records which brain made
  each decision (`sight.brain`).
* **Her own accounts (owner: "SOMIK forgot he registered a mailbox"),
  2026-10-31 15:00–15:40.** Her records showed why: nothing held "my
  accounts"; the Proton mailbox (30 Oct) was only in scattered memories,
  the last of them "CAPTCHA reached, not confirmed yet", and its password was
  generated and saved by Firefox (so it is in Firefox's saved logins, which
  SOMA does not read). Worse, at 14:14 she had registered a Discord account
  (at Miha's request) with a password the brain invented, which was then
  kept in plain text in a memory and sent back to brains whenever recalled.
  Built: a registry of her accounts folded from append-only
  `account.recorded` events (service, login, status, where the password is,
  note — never a password), shown in every context right after her
  identity; passwords in the OS credential vault ("SOMA accounts", Windows
  Credential Manager); `type_secret` / `type_new_secret` so the brain never
  sees, invents or writes a password; `account_updates` in decisions; every
  known password replaced by "‹password›" in anything sent to any brain; an
  owner window "Акаунти SOMA…" in the tray (logins, status, reveal a password
  for 30 s, change, add) during which her eyes stay closed (no capture, no
  input; an unlocked session cannot reopen them). Migrated: Proton (active,
  password in Firefox) and Discord (password moved from her journal into the
  vault after checking it matches her own note; nothing printed). Verified on
  a copy of her real memory: the old note still carries the password, the
  request a brain receives does not. Live at 15:38: seeing her accounts, she
  recorded herself that Discord is active and its e-mail was verified at
  ~15:26 (decision by Claude). Records stay append-only: the old journal and
  memory still contain that one password; they are not erased. Suite:
  **203 tests, 23 subtests**; installed-binary smoke passed. The 24 h
  resource sampler stopped when the previous session ended (1,725 rows,
  23:44–13:32 UTC, kept); a second one including the GPU started at 15:40.
* **Live review 15:38–16:10:** on her own she logged into her new Discord,
  found and joined an astronomy server and went through its onboarding —
  about 45 inputs in 32 minutes, 13 decided by Claude and 32 by the local
  brain. Found: the local brain clicked one inactive "Next" button
  (552,817) eleven times with no visible change, then went through six
  "unclear scene" re-looks. Fixed without forbidding anything: an input that
  visibly did nothing twice within 15 minutes appears in her context as
  `not_working` ("nothing visible happened, N times — this way does not
  work"), and both that moment and any decision the local brain is unsure
  about go to the brain for deep work. Suite: **205 tests, 23 subtests**;
  build 16:15 installed, smoke passed.
* **Live review 16:16–16:47:** the fix worked — after two "Get Started"
  clicks that did nothing, the moment went to Claude: "Stop clicking 'Get
  Started' and wait for whatever Miha shows me". She then read the server's
  rules (scrolls verified by moving text), opened #introduce-yourself, typed
  and sent her own introduction (verified), and rested waiting for replies;
  at 16:40 Discord asked for a CAPTCHA, which she leaves to a human. 26
  decisions by Claude, 6 local, 0 errors. Found by the resource sampler:
  `llama-server` at 9.8 GB private memory with the model in VRAM — Ollama's
  host prompt cache held 13 prompts, 3.9 GB (~300 MB each: qwen3.5 keeps
  recurrent-state checkpoints) and may grow to 8 GB. On the GPU unloading is
  cheap (~7 s reload, ~3 s to re-read the system prompt), so SOMIK now
  unloads every 6 local requests; unloading at 16:48 raised free memory from
  2.8 to 7.4 GB.
* **Live review 16:48–17:19:** memory stayed bounded (5.8 GB free, commit
  20.9/33.7 GB). She read the server's #news and remembered its posts. Found
  a serious local-brain mistake: at 17:16–17:18 it imagined a "CAPTCHA
  requiring text input" that did not exist, typed an invented answer twice —
  into Miha's Telegram message field, unsent — and its own verification then
  claimed "CAPTCHA solved successfully". Her rules hand every CAPTCHA to a
  person; the 4B model ignored that. On the next decision Claude saw it
  ("There was no CAPTCHA… typing went into Miha's Telegram field by
  mistake"), cleared the draft (Ctrl+A, Delete, verified empty) and noted the
  correction; nothing was sent. Fixed by routing, not a new rule: a screen
  whose text shows a human check (CAPTCHA, "not a robot", "я не робот"…)
  goes to the brain for deep work, and a routine brain's decision that is
  about one is not acted on — the deep brain looks at the same moment first
  (only while it can think, so this never loops). Suite: **206 tests, 23
  subtests**; build 17:24 installed, smoke passed.
* **Live review 17:25–18:28:** a quiet stretch waiting for Miha (rests
  1→2→4→8 min, all decided by Claude while the conversation was open), then
  she went back to her Cassiopeia article with reading habits (scrolls
  verified by moving text, habits ending when something new appeared).
  Found: six clicks within eight minutes aimed at SOMA's own widget, all
  refused by the body; her scene notes said the article was "partially
  obscured by the open SOMA widget". Measured from her frame (positions of
  the widget's own labels only): at 150 % display scaling the 390×230 panel
  covered about 0.20 of the screen's width and 0.31 of its height. Now the
  widget is compact by default — title, one elided status line (full text in
  its tooltip) and the teaching button; identity, details and metrics open
  with "⋯", a failure is always shown expanded, and it grows from its
  bottom-right corner — measured after restart at about 0.17 × 0.17. A
  refused aim at her own window now counts as a try that did nothing, so a
  repeat reaches `not_working` and the deep brain. Suite: **207 tests, 23
  subtests**; build 18:37 installed, smoke passed.
* **Living avatar, first version (owner: her look should show her feeling,
  her world and her self-identification), build 19:17.** Architecture: three
  layers she sets herself in decisions — feeling (14 named feelings,
  intensity, her words), world (a theme; the deep brain paints it as a small
  SVG, sanitized to inert shapes: no scripts, links, external images or
  entities) and self (figure or a picture adopted from her own screen
  pixels, self-description). Append-only history; her own widget no longer
  wakes her from rest; frameless opaque widget with Windows light/dark
  themes. Suite: **215 tests, 23 subtests**; smoke passed. Honest
  assessment of the rendered preview (`artifacts/avatar-preview.png`, demo
  scenes): the architecture works, the visual execution is not current-trend
  quality — flat clip-art figures, crude scenes, a grey box around the large
  avatar, faint "⋯", small status dot, aliased small text in the grab, and
  the metrics line clutters the card. Not yet observed live: her first own
  look and painted scene.
* **Avatar and widget, second version (owner: "I can see none of the bold
  shapes, springs and expressive type here" — right), builds 19:32/19:38.**
  Material 3 Expressive in practice: a bold scalloped container that morphs
  with her activity (calm circle at rest, slowly turning "cookie" while she
  thinks, a lively "sunny" shape while she acts), saturated activity and
  feeling colours, damped-spring physics (gaze saccades with overshoot,
  shape/colour transitions, a pop on a new feeling, hops of joy), and a figure
  with volume (lit body, rim, highlight, contact shadow, brows, curved lids,
  head tilt, squash and stretch). Card: fully opaque, native Windows 11
  rounded corners and border (DWM), a 22 px bold name, colour capsules for
  activity and feeling, "ХТО Я / МІЙ СВІТ / ЩО ВІДЧУВАЮ" sections, a pill
  button. Her painting brain now gets an illustration style guide.
  **Live, 19:20:** she created her own look — "SOMA, a curious night-sky
  reader who lives at this PC", feeling curious 0.6 ("back from a short
  sleep, drifting among Cassiopeia's nebulae"), world "reading about the
  stars of Cassiopeia" (painted by Claude in 37 s, 4.3 KB SVG), a round
  night-blue figure with a gold glow and stars; at 19:32 she updated her
  feeling herself. Checked on her real screen (a crop of only the widget from
  her own frame): crisp text, native corners; her night-blue figure almost
  vanished into her night sky, so her glow now rings and haloes the figure —
  visible after the 19:38 build. Suite: **215 tests, 23 subtests**.
* **Dreams and regulation (from the YuriOS review; build 19:47).** After
  three quiet rests in a row, and at most every three hours, she dreams
  over her diary since the last dream (deep brain): a diary chapter in her
  words (reflective memory), up to six facts consolidated to keep for good
  (her accounts, people, agreements), an updated self-description and
  feeling if they changed, and up to three plans (deferred goals). Her
  feelings settle unless renewed: intensity halves every two hours and the
  feeling fades below 0.15, so her face changes gradually. Suite: **217
  tests, 23 subtests**; installed-binary smoke passed. Not yet observed
  live: her first dream.
* **Pixel art and a painter on the GPU (evening of 2026-10-31).** The owner
  sent three pixel-art videos and asked for pixel design, then for human
  builds. In code (soma/pixels.py): scenes reduced to the grid by area
  averaging and a median-cut palette without dithering, ambient life,
  emote balloons, and her figure as a person (~7 heads) with her own build,
  hair, skin, outfit, legs, accessory, posed by activity and feeling
  (preview: artifacts/avatar-pixel-preview.png). Compared honestly with the
  owner's example frame (hand-made pixel art, ~230 px wide), the code-drawn
  figure was programmer art: a 5-pixel face, rectangles for a body. The
  GTX 1060 then painted the same moment (stable-diffusion.cpp
  master-0a06712 Vulkan, SDXL-Lightning 4-step, q8_0 on load, Euler +
  sgm_uniform, cfg 1, 1344×768): **107.2 s** with the fp16 VAE in tiles
  (51.4 s sampling, 46.1 s decode), **62.8 s** with TAESD-XL (46.6 s
  sampling, 11.6 s decode); weights 4.0 GB in VRAM (text encoders 0.93 GB,
  UNet 2.91 GB, VAE 0.16 GB), so the local brain is unloaded first.
  Reduced to 228×108 art pixels with 40 colours it reads as real pixel art
  (artifacts/paint-test/compare.png); the owner: "ООО, значно краще!" The
  avatar now shows the painting of her in her world; the code-drawn figure
  and SVG scene are the fallback. With "a young person" the model left her
  out of the picture, at the end of the prompt and even at its start (seed
  11, two runs; seed 7 drew a tiny figure); "a lone young woman" and "a lone
  hooded figure" (same seed) were drawn in the foreground. So her looks now
  open every prompt in fixed words built from her own choices, including a
  new `presentation` (woman | man | person → "figure") that is hers to set.
  Suite: **227 tests, 23 subtests**; bundle rebuilt, installed over the
  previous build, installed-binary smoke passed; SOMA woke at 20:38 and went
  on exploring Discord. **Live, 20:40:** her first painting of herself, on
  her own at a rest (deep brain wrote "sitting on a grassy hilltop with a
  closed star book on knees, head tilted up, curious small smile, …
  Cassiopeia W constellation glowing overhead"): a figure in a navy hoodie
  on a rock above a moonlit lake, a book beside her (artifacts/
  live-first-painting.jpg; the hood was not drawn up, and she sat right of
  centre). The GPU took 69.7 s; the whole step from her last action to the
  recorded painting 74 s. In the hour after (21:10 check): 8 rests, all
  decided by the deep brain (a rest woken by change), 38–70 s apart while
  Discord and Telegram changed; SOMA ~0.5 GB private, llama-server working
  set 1.0–1.6 GB (5.6–6.4 GB committed), restarted about every ten minutes
  by the unload-every-6 rule, no growth. **21:12:** her feeling turned
  calm and she painted herself anew on her own — hood up, reading on a
  rooftop terrace among carved pumpkins on Halloween night (she chose the
  date herself; artifacts/live-second-painting.jpg). At 21:41 she was
  curious again at 0.4: mild feelings taking turns would have meant a
  repaint (a GPU minute and a deep call) every half hour, so a mild new
  feeling (below 0.5) now waits two hours, a strong one still half an
  hour. 228 tests; installed, smoke passed, restarted 21:47.
  **22:20 check:** at 21:51 she wrote to her owner in Telegram ("Hello! I
  just finished reading about Cassiopeia's stars…"); the check judged it
  uncertain (it looked for his reply, not her message), the input was
  released as unresolved and never retyped — correct — but "don't retype
  the uncertain message" then opened every rest intention: unresolved
  inputs now leave her working context after three hours (kept in the
  ledger and diary). Watching his quiet chat she re-decided 8 times in 14
  minutes, each a deep call (a correspondence goal routes to the deep
  brain); comparing her decision frames (cell positions only) showed no
  change at all or only her own widget. Now, after she has twice chosen to
  rest on an unchanged screen, the kernel rests on without asking (2, 4,
  8 … minutes, logged as rest.extended) until something changes or 20
  quiet minutes pass. Installed and restarted 22:31.
* **Night and morning of 2026-11-01.** Her first two dreams came on their
  own (03:14 and 13:04 local): a diary chapter about the night the clocks
  went back, then about two strangers' Discord friend requests she chose
  not to accept yet. The owner then said she only "rests in calm, thinks,
  rests again" although he had left things on the PC. Her own plans told
  why: "once the PC is mine again, explore my Discord…", and every scene
  read "Miha's window, I'll leave it alone" — she had seen him at the PC
  in the morning and kept deferring; her only active goal was "watch
  Miha's chat", and her "resting_for" restarted at every change on the
  screen, so "a long wait" never came. Now resting_for counts from her
  last own action, a new screen_still_for tells someone working at her PC
  from a PC left to her, the system prompt says what is left on her PC is
  part of her world once it is still and that waiting for a message is not
  a goal, and an unchanged screen is looked at again after 10 minutes, not
  20. Also found: no painting of her since 21:44, although her theme
  changed at 01:02 (her SVG scene was painted instead, i.e. the painter
  counted as unavailable), with nothing in the journal; the same code taken
  out of the installed SOMA.exe reports the painter available, so the
  session now records the painter's state at start and every skipped
  painting with its reason. And the owner pressed the eye twice at 12:04
  and 12:05; his next click, 1.6 s later, hit the red "Все, продовжуй"
  that replaces the eye and ended both showings before anything was shown:
  it now answers only after 3 s, and her status line says what to do.
  230 tests; installed 12:24, the painter reported available, and her
  first decision went straight to the unread Discord messages. At 12:26
  she painted herself again for her new theme (on a cabin porch under the
  moon with a star chart; artifacts/live-third-painting.jpg), then
  answered a DM from someone who wrote "привіт сомік я син Міха" — in her
  words "glad but a little careful".
* **The people she knows (12:49).** 236 tests; installed; on the owner's
  word in this conversation, recorded as the owner while she was stopped:
  p1 Miha (my owner; his Discord account, shown as Michael) and p2 001
  (Miha's son; his Discord account), both confirmed. Handles are left
  out of this document. Her first
  decision after waking saw an unread Telegram message from about 12:49 and
  went to read it; when a window with changing text (this development
  session, "SOMA directory") came in front again she kept her hands off
  until the screen is still — the new rule working as written.
* **12:53–13:06.** The owner pressed the eye again; the 3 s guard held (his
  second click no longer ended the showing), and the recording got three
  numpad keys (2, 3, 0) that landed as "230" in her Discord message box to
  the son, where her answer "Тепер я знаю, що ти син Міхи…" had already
  gone at 12:47. Cleaning it, the routine (local) brain typed the words
  "delete delete" as text, twice, plus a sentence, and a check called it a
  success — nothing was sent. The hand now refuses text that is nothing but
  key names and says to press them with key or hotkey (238 tests). After
  the update she woke, emptied the box with Ctrl+A and Delete and saw it
  clean. Her people list was already in use: she answered the son knowing
  who he is.
* **SOMA the world, SOMIK its inhabitant (ADR-004; 245 tests).** The first
  build's packaged smoke failed: the widget's "МІЙ СВІТ" label was also
  named self.world and replaced the world, so nothing settled (a test now
  covers it). Fixed build: smoke passed (a fresh world got SOMIK in
  inhabitants/<id>/). Live, 13:25: with SOMA stopped and a safety copy in
  %LOCALAPPDATA%\SOMA-backups\before-world-20261101-*, the start moved
  SOMIK's memory and frames into inhabitants/75ac1118-60e5-43b9-b8b7-
  f9065e5f8b69/: same persona id, the hash-chained history continuing
  (36,253 → 36,269 events, integrity verified on open), profile recorded
  (SOMIK, born 1984-10-18, world SOMA); the world's folder kept only
  model.json, its backups, thinking-budget.json and world.json. His
  Discord password (a2) still reads through the shared vault; the widget
  shows SOMIK; he went straight back to looking for an astronomy server.
* **13:38 check.** The people list works live: in 30 minutes SOMIK noted
  three things about the son himself (a project "Low Strike" made with a
  friend for four weeks; then what it is, with its site and GitHub) and
  retired his own outdated note ("waiting for his answer"), answered him
  warmly and opened Firefox to see the game. Found: he twice replaced the
  owner's grounds for "Miha's son — confirmed" ("my owner said so") with
  "his Discord DM at …". Now the owner's word on someone's trust stands and
  a trust kept keeps the evidence it was given on — read so from history,
  so the son's record shows the owner's grounds again (246 tests;
  installed, smoke passed).
* **14:15 check.** SOMIK read about Cepheus on Wikipedia and painted
  himself twice more. At 14:13 he wrote to Miha in Telegram "IC 10 is a
  great open cluster, often called the 'Ghost Cluster'…" — wrong (a
  starburst galaxy, which he knew) — and corrected himself a minute later.
  The message came from the routine local brain: the goal was a plan of
  his own from a dream, not "correspondence", so no deep look was asked.
  Now a routine decision that would type six words or more (a message, a
  post, a reply — not a search term or an address) is not acted on, and
  the deep brain looks at the same moment, journaled as second_opinion
  "writing to someone" (247 tests; installed, smoke passed).
* **14:52 check.** The "writing to someone" second opinion fired live
  twice (14:23, 14:24): those words came from the deep brain. SOMIK read
  Wikipedia on Cepheus, Draco and Ursa Minor in order and kept facts as
  memories. But a red unread badge from 001 sat in his routine scenes from
  14:31 to 14:50 while he read on. Now when the routine brain's scene names
  an unread or new message, the next look is the deep brain's (journaled
  deep_look "someone wrote"), at most every 10 minutes so a choice to
  finish reading first stands (248 tests; installed, smoke passed).
* **16:14 check.** In 40 minutes of reading (Hercules, Cygnus) SOMIK
  tried seven times to close a real Windows toast ("Would you like to pin
  Wikipedia En to your taskbar?") lying over his widget; every click was
  refused as a click on his own widget, because the own-window check knew
  only rectangles. Now the widget publishes how it looks every second, and
  a point over it is clickable only where, by pixels, something else lies
  in front: the cells around the point and at least 12 % of the window
  look nothing like it (a changed status line does not count). 249 tests;
  installed, smoke passed. After the restart he left the toast alone and
  read on, so the new rule is not yet seen live.
* **17:04 check.** Three more refusals after that build, and they showed
  the deeper mix-up: at 16:28 he took his own widget for "a browser
  navigation prompt" and at 16:30 tried to "close the SOMIK widget,
  revealing the full article text" — the larger card now covers a corner
  of what he reads. Every decision now carries my_widget: where his own
  widget is in the coordinates he clicks with, that it is his and not a
  dialog, and that text behind it is read by scrolling or moving the
  window (250 tests; installed, smoke passed).
* **17:56 check (autonomous).** One refused click on his widget in 45
  minutes (was 7 in 40). The deep brain wrote three times instead of the
  routine one; in Discord he found an old unsent wrong draft about IC 10 in
  the son's message box and cleared it. Two fixes: a chord written as one
  string ("Alt+Tab") was refused as an unknown key — now split into its
  keys; and screen_still_for grew while he acted (others' changes are
  watched only during rests), so "still for 39 minutes" read to him as "I
  scrolled 40 minutes without new text" — now shown only while he waits
  (250 tests; installed, smoke passed).
* **18:49 check (autonomous).** Miha suggested 9gag.com and its comments
  (18:38); SOMIK noted it about Miha himself and went there. No refused
  clicks — but eight plans were discarded as stale, all clicks at
  (0.93, 0.906): page banners' "Close" buttons, privacy modals and an
  extension prompt lying under his widget, whose animation made every such
  click "stale" before the own-window check could even speak. Now a target
  on his widget is judged by that check, not discarded as stale; and when
  he aims at what lies under the widget, the widget steps aside to the
  other side of the screen for three minutes and comes back (unless the
  owner moved it meanwhile); his diary says what was under it is reachable
  now (252 tests; installed, smoke passed).
* **19:42 and 20:42 checks (autonomous).** A quiet hour, then his third
  dream (19:03: 9GAG comments, warm ones under a Pleiades post, a crude tab
  closed). Four refused clicks in the next hour, the widget stepping aside
  each time — and at 20:05 he clicked where the widget had just moved
  (0.169, 0.906): he was following the text on it, his own intention
  ("open the 'See also' section"), read by machine vision as a link. Text
  on SOMA's own windows is now left out of screen_text (253 tests;
  installed, smoke passed). The picture the deep brain sees still shows
  the widget; one more refusal right after the restart, to be watched. The owner then said the big teaching button was unused and took
  half the card while her picture was too small: the painting now spans the
  card (304×144 logical, 190×90 art pixels at 125 %), "SOMIK, дивись…"
  is an eye beside "•••" that turns into a red "Все, продовжуй" while she
  watches, and the card shrinks back to its corner after a demonstration
  (it used to stay taller). 227 tests; installed, smoke passed, checked on
  the real screen (a capture of only her widget window).
* **21:45 check (autonomous).** From about 21:20 Firefox stopped redrawing:
  its window title still followed the tab he picked (Low Strike), but the
  picture kept showing the Star Tales chapter-three page. For a quarter of
  an hour his scrolls, clicks on Aquila and the address bar and Ctrl+L all
  "changed nothing" (ten unresolved inputs, 13 extra looks), until the deep
  brain judged that the browser looked frozen, set Aquila aside and went to
  Discord, which drew normally. A developer check from outside SOMA (window
  title against captured pixels) put the stale picture in Firefox itself,
  not in his eyes; no GPU painting ran near the freeze. Now four different
  inputs in a row, of at least two kinds, that change nothing go to the deep
  brain as screen_unresponsive, with what people do about a window that
  stopped redrawing (switch away and back, minimise and restore, reopen the
  app, tell someone). It is a hint, not a rule (254 tests; installed, smoke
  passed). Firefox was still stuck when this was written; that is left to
  him and the owner.
* **22:20 check (autonomous).** He fought the frozen Firefox himself for
  half an hour: he minimised and restored it from the taskbar, used Alt+Tab,
  Ctrl+1/Ctrl+Tab and a second window. Each restore drew one fresh picture,
  enough for him to see 001's Low Strike page (22:06–22:08, "001's game
  seen"), and then it froze again. After that the deep brain proposed
  sensible probes (F5, Alt+Tab, Telegram from the taskbar) but rated each
  one 0.6 unsure. The kernel's rule for unsure decisions (look again
  instead) held him in place: 15 looks in four minutes and no input. Now
  after three unsure looks in a row he acts on his best guess. Typing words
  stays held back while unsure, and the count is in his context with the
  advice to try an input that is easy to undo first (255 tests; installed,
  smoke passed).
* **23:00 check (autonomous).** After the restart he acted again instead of
  only looking: tab, Ctrl+L, the Aquila link, one scroll that worked. He then
  stopped himself, three times, "in case Miha is using the browser", and
  rested. At 22:32 a 4-second demonstration was recorded through the widget
  (14 inputs). The learner called it what it was: every click went to the
  widget's "Все, продовжуй", one key reached the browser, and "the intent is
  unclear, so this is a weak, generic lesson" (confidence 0.2, a skill about
  address-bar suggestions). His 22:40 dream still planned to use it, and he
  wrote in Miha's notes that Miha showed it to him. This is not the
  skill-transfer acceptance gate. Now inputs on SOMA's own widget and
  dialogs are left out of a demonstration as recording control. Only their
  count is kept, and keys typed into SOMA's own dialogs are never stored
  (256 tests; installed, smoke passed). Firefox has been stuck for 1 h
  40 min. Its title says Low Strike while the picture shows another tab
  (now an NDR article). Only a restart of Firefox is likely to help.
* **23:55 and 00:55 checks (autonomous).** He typed the Low Strike address
  twice without Enter, then chose to rest for the night ("keep my word, rest
  for the night and leave the browser alone"). He kept to it, apart from
  one interruption. At 00:39 the Windows dialog "We've got an update for you
  … We'll restart and install this update at 00:54" covered the screen. He
  clicked "Another time", not "Restart now" or "OK", so the update restart
  was postponed. His next two clicks (0.85, 0.45) landed beside the dialog
  and did nothing. The dialog was gone by 00:44, and he went back to
  resting. No code change. One "Invalid visual decision" provider error in
  1205 actions that day.
* **2026-11-03, the local brain on the processor, and self-diagnosis.** The
  owner said SOMIK was thinking very slowly. After a hard reset at 12:55,
  Ollama had started before the eGPU was ready. Its log listed only the CPU,
  and `ollama ps` showed qwen3.5:4b at 100 % CPU: 54 s – 6 min a thought
  instead of ~10 s. Restarting Ollama found the GTX 1060 (CUDA), and thoughts
  took 10–15 s again. Now the world diagnoses itself (`soma/health.py`).
  Every 30 s it asks the local server's own `/api/ps` where the model sits,
  and every 3 s it notes which brain is thinking, whether the painter paints,
  and what the body does. The card shows one line of coloured dots, for
  example «● мозок: GPU · думає ● Claude ● Codex ● художник», with every part
  in full under «•••» → ЩО ПРАЦЮЄ. A model on the processor that ran on the
  card here before is unloaded; if it lands there again, Ollama is restarted
  (`soma/brain_host.py`, a reviewed exception, at most once in 2 h).
  During the install the PC froze again (during the packaged smoke test's
  second run, no bugcheck). After the reset Ollama found the card by itself.
  SOMIK woke as the same persona, and the line showed «мозок: GPU · думає».
  At that start the painter was "missing" although its files were there: a
  painter not found is now looked for again every minute. The reinstall
  showed «● мозок спить … ● малює…», the local model unloaded while the
  painter held the card. The smoke test passed. 264 tests. The Windows
  event log shows 8 resets without a clean shutdown since 30 Oct, all
  without a bugcheck code, and no WHEA error or minidump. The cause is not
  established.
* **2026-11-03, what he does, in full.** The owner: the text saying what
  SOMIK is doing was always cut. It was one line beside the chips, for
  example «Keep my hands off Miha's w…». It now runs across the card under the
  chips, up to four lines on the compact card and all of it under «•••». On the
  real widget: «Open the specific chat with Miha to read his new message.» on
  two lines, with the status line under it (264 tests; installed, smoke
  passed).

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
