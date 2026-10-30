# Demonstration-learning upstream audit

Audit date: 2026-10-30. Local clones use `git clone --depth 1 --filter=blob:none` under `.upstream/`. No upstream source has been copied into SOMA production code. Decisions below concern these exact commits, not future releases.

| Repository | Commit | Code license | Decision |
| --- | --- | --- | --- |
| showlab/ShowUI-Aloha | `f998a8b1f132f9b1cd37b86dc20b124be37343a2` | Apache-2.0 | Reference semantic demonstration pipeline; replace recorder/motor adapters |
| OpenAdaptAI/OpenAdapt | `ffd9b6d1ad0870cf8e094de07302a5e9e35b5ddc` | MIT at root and capture package | Reference recording integrity/verification concepts; reject full workflow runtime |
| OpenAdaptAI/openadapt-capture | `6e2e1ad6e882a99b6e6e742a85cb812aee82c59f` | MIT | Reference frame/input synchronization, geometry, and explicit recording lifecycle |
| showlab/ShowUI | `21ed7cb24be0cc877bb8352ee34d58a9aea2c876` | Apache-2.0 | Optional model-provider candidate; no bundled weights or model runtime |

## License evidence

Aloha's actual [LICENSE at the audited commit](https://github.com/showlab/ShowUI-Aloha/blob/f998a8b1f132f9b1cd37b86dc20b124be37343a2/LICENSE) is Apache-2.0, and its README agrees. The implementation specification's external MIT label does not override that file. If code is incorporated later, retain the license, attribution, any applicable NOTICE, and notices identifying modifications. Aloha's cloud model providers have separate terms; the code license does not license their models.

[OpenAdapt root LICENSE](https://github.com/OpenAdaptAI/OpenAdapt/blob/ffd9b6d1ad0870cf8e094de07302a5e9e35b5ddc/LICENSE), [monorepo capture LICENSE](https://github.com/OpenAdaptAI/OpenAdapt/blob/ffd9b6d1ad0870cf8e094de07302a5e9e35b5ddc/packages/capture/LICENSE), and [standalone capture LICENSE](https://github.com/OpenAdaptAI/openadapt-capture/blob/6e2e1ad6e882a99b6e6e742a85cb812aee82c59f/LICENSE) are MIT: copyright and license text must accompany copies/substantial portions. The standalone README states capture has moved into the monorepo; the two snapshots must not be assumed identical. Optional FFmpeg and transcription dependencies require separate distribution review. Capture's `docs/COMPLIANCE.md` explicitly treats those boundaries separately.

[ShowUI code LICENSE](https://github.com/showlab/ShowUI/blob/21ed7cb24be0cc877bb8352ee34d58a9aea2c876/LICENSE) is Apache-2.0. Separately, the [ShowUI-2B model card at revision cabec4fcc48d15ffd3efe0b33ea9bc7d41509d60](https://huggingface.co/showlab/ShowUI-2B/blob/cabec4fcc48d15ffd3efe0b33ea9bc7d41509d60/README.md) declares MIT and names Qwen/Qwen2-VL-2B-Instruct as the base model. The file listing contains a roughly 4.42 GB PyTorch checkpoint and no standalone LICENSE file. This is model-card licensing evidence, not proof that every dependency/base-model condition has been resolved. Before distributing weights, pin the checkpoint digest, preserve the declared MIT notice, review the base model and tokenizer dependencies, and add them to SBOM/notices. No weights were downloaded, distributed, or executed in this audit.

Exact SHA-256 hashes of local LICENSE files are preserved in [learning-evidence.json](learning-evidence.json). Licensing conclusions are repository-file observations, not a complete legal review of the dependency graph.

## ShowUI-Aloha: actual module boundaries

`Aloha_Learn/log_processor.py` parses input logs; `screenshot_processor.py` binds video frames/crops to actions; `trace_generator.py` asks a VLM for observation, intended action, and expected result. `default_prompt.json` asks for semantic descriptions without coordinates. `Aloha_Act/ui_aloha/act/gui_agent/planner/trajectory_manager.py` supplies learned action descriptions as context for a new task. This is the useful transfer pattern: retain a semantic workflow and re-ground it against each new screen.

The recorder is supplied as release binaries in the README; its source is not present in this checkout. We cannot certify the recorder's capture routes from these Python files. Public example logs contain executable/window titles; `log_processor.py:55,109` retains them as `current_software`, and `trace_generator.py:129,143` sends that field into the model prompt. SOMA must omit this nonpixel metadata and derive software context only from screenshots.

Execution uses `ui_aloha/execute/executor/aloha_executor.py` and `tools/computer.py`: explicit click, move, drag, scroll, key, and type operations through PyAutoGUI, screenshots via ImageGrab, and physical-monitor geometry. A generic shell helper also exists in `tools/run.py`; it must not become a SOMA action. The Linux branch uses `xrandr` shell pipelines for monitor geometry, and `ComputerTool.__init__` later references `screen` assigned only in the Windows/macOS branches. README lists Windows/macOS and Linux adaptation as future work. Consequently Linux/Wayland support is not established by the presence of an `else` branch.

Offline PoC: the real included public air-ticket log parses into 98 raw events and 17 processed items. A synthetic left-monitor click at `(-100,50)` loses its coordinates because the parser regex accepts only unsigned values. This is a concrete reason to retain signed desktop coordinates and explicit monitor origins in SOMA rather than transplanting the parser.

## OpenAdapt and capture: forbidden routes are not hypothetical

The current [OpenAdapt README](https://github.com/OpenAdaptAI/OpenAdapt/blob/ffd9b6d1ad0870cf8e094de07302a5e9e35b5ddc/README.md) describes a compiler/execution system that deliberately uses DOM, native accessibility, direct API steps, and system-of-record read-back. `packages/flow/openadapt_flow/adapters/desktop_recorder.py` arms native click targets with UIA/AT-SPI structural locators. `backends/windows_backend.py` uses an HTTP execute channel, UIA identity extraction, and clipboard/PowerShell for non-ASCII input. `backends/linux_backend.py` uses AT-SPI native actions. `runtime/effects/rest.py` and `db_snapshot.py` read application APIs/databases. These are incompatible with SOMA's application perimeter, including for verification. Do not import the flow runtime, backends, compiler-generated programs, browser recorder, or system-of-record verifiers.

The smaller `openadapt-capture` package contains native low-level input hooks and screenshot capture, but defaults to structural observations. In `openadapt_capture/config.py`:

- `RECORD_STRUCTURAL_OBSERVATIONS=True` must be explicitly set false.
- `RECORD_WINDOW_DATA=False` gates `read_window_events`; keep false.
- `RECORD_READ_ACTIVE_ELEMENT_STATE=False` gates element lookup; keep false.
- Browser events and audio default false; keep false.
- Do not use a window owner/title selector: window-scoped capture resolves window IDs and can capture backing-window pixels independently of physical visibility.

`recorder.py:3067` confirms active-window polling is conditional on `RECORD_WINDOW_DATA`, while `1692` gates active-element state and `2955` constructs the structural observer. Disabling only structure is insufficient as a general guarantee because other settings/environment overrides remain independent. A hypothetical adapted recorder must enforce these values, validate every serialized field, forbid injected structural observers, and keep `send_profile=False`. SOMA uses a small native recording adapter instead of importing this broad package.

Windows `input_observer/windows.py` uses WH_KEYBOARD_LL and WH_MOUSE_LL and discards OS-injected input. It reads the foreground input thread's keyboard layout to translate native key events, not application text/title/control state. If adapted, keep that use narrowly within event decoding and never export window/process identity. Linux `input_observer/linux.py:440` explicitly rejects native Wayland to avoid missing events from native Wayland applications through XWayland. Desktop display geometry itself is allowed monitor information; application window metadata is not.

Useful concepts: one shared recording clock; monotonic source ordering; before/input/after frame binding; negative-origin monitor translation; bounded queues; terminal-frame/drain integrity; explicit protected gaps that omit both keys and pixels. No covert or always-running human-input recorder is appropriate: hooks exist only during a visible agreed demonstration, with motor output inhibited.

## ShowUI: model boundary

`QUICK_START.md` takes a screenshot and target description, returning normalized coordinates; inference is separate from OS execution. `api.py` offers a Gradio inference client, which is an internal model endpoint rather than an application API. SOMA must supply already-captured image bytes and receive a validated motor proposal; it must not let an image path open arbitrary application files. The default web action vocabulary includes `COPY`, which must never grant clipboard read/write access.

The isolated `extract_norm_point` PoC maps `[0.5,0.25]` on a 1920x1080 test image to `(960,270)`. It also accepts `[1.5,-0.25]` and returns `(2880,-270)` without bounds validation. Production must reject nonfinite, out-of-range coordinates and points in monitor gaps before input. `api.py`'s non-string image branch references `np` without importing it; the tested string-image branch works. Neither result establishes model accuracy or local hardware performance.

## Platform assessment

| Candidate | Windows | Linux X11 | Wayland |
| --- | --- | --- | --- |
| Aloha | README and motor code support Windows; live end-to-end NOT RUN | README roadmap only; broken constructor path observed | No evidence of complete portal/input support |
| OpenAdapt flow | Supports structural/UIA path, incompatible with perimeter | Supports AT-SPI path, incompatible with perimeter | No acceptable pixels/input-only evidence |
| Capture | Native low-level hook and MSS code present; live recording NOT RUN | Explicit X RECORD/MSS implementation; live X11 NOT RUN | Input observer explicitly refuses native Wayland |
| ShowUI model | Inference library, no native body included | Inference library, no native body included | Model itself is display-server independent; provides no Wayland body |

Wayland needs an explicit compositor/portal capability plan for both pixels and input plus a demonstration-input observation mechanism. XWayland-only observations are incomplete and cannot qualify as support. This Windows host audit cannot pass an X11 or Wayland acceptance gate.

## Reproducible PoCs and limits

Run `python research/upstream-pocs/audit_learning.py` from the SOMA root after cloning these repositories. Requires Python 3.11 and Pillow only. The script runs upstream log processing, both snapshots' pure desktop-geometry code, OpenAdapt's structural-coverage detector on an offline fixture, and ShowUI's isolated output postprocessor. It generates [learning-evidence.json](learning-evidence.json) with exact versions, license hashes, and assertions. These are offline component probes, not live capture/learning/inference tests. They expose unsupported routes and boundary issues before integration.

Live human demonstration capture, real model generalization, Windows GUI replay, X11 GUI replay, Wayland sessions, and native installers: **NOT RUN by this audit**. No live user input was recorded, no GUI action was emitted, no API key was read, and no model endpoint was called. Firecrawl was unavailable for new work because its recorded credit balance was negative; official model-card evidence was checked with the web tool instead.
