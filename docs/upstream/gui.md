# GUI upstream audit

Audited 2026-10-30 on Windows. All four first clone attempts succeeded with exit code 0 using `git clone --depth 1 --filter=blob:none`; clones live in `.upstream/gui-audit/`. Exact clone commands, license hashes, source line evidence and reproducible probe results are in [gui_audit_results.json](gui_audit_results.json). No upstream implementation code was copied into SOMA. README claims below are source claims, not platform certification.

Decision: use these repositories as references. Implement SOMA's fixed monitor/mouse/keyboard port independently. Importing any complete upstream runtime would add task-only orchestration, unsupported platform assumptions, or routes forbidden by the specification.

| Repository | Audited commit | Code license | Decision |
| --- | --- | --- | --- |
| OthersideAI/self-operating-computer | `eb8165a2efb1b34d66a28ecebf8ca97ae67cbb79` | MIT | Reference screenshot/action loop and normalized coordinates |
| simular-ai/Agent-S | `0fff0e634869dab72027435b4586e62300185d41` | Apache-2.0; bundled Prime runtime MIT | Reference visual planning/feedback only; reject S3/S4 execution runtime |
| bytedance/UI-TARS-desktop | `3ac2cb8d946d78d5ff92ad17b318eaafa18c178c` | Apache-2.0 | Reference screenshot grounding, scaling and native shell; reject existing Windows typing and tool integration |
| showlab/computer_use_ootb | `21b05ae06de89700b998dc85d8ef64454f0d0291` | Apache-2.0 | Reference planner/visual actor separation; reject tool-enabled runtime/dashboard |

## Self-Operating Computer

Read `README.md`, `LICENSE`, `operate/operate.py`, `operate/utils/operating_system.py`, `operate/utils/screenshot.py`, `operate/models/prompts.py` and screenshot/OCR call sites in `operate/models/apis.py` at the pin above. [Pinned source](https://github.com/OthersideAI/self-operating-computer/tree/eb8165a2efb1b34d66a28ecebf8ca97ae67cbb79).

- Windows: README advertises support; screenshot module calls `pyautogui.screenshot()` and motor module emits PyAutoGUI keyboard/mouse calls.
- Linux/X11: README explicitly requires an X server; screenshot branch queries Xlib screen dimensions then captures through Pillow. `Xlib` is imported unconditionally, so Windows import/package behavior needs repair and validation. No portal/libei/Wayland implementation was found in the audited modules.
- Boundary: screenshot/OCR over those pixels and explicit motor actions fit the intended perimeter. The macOS `screencapture` subprocess and CLI console clearing are internal fixed utilities, not evidence of a model shell tool. Do not carry those subprocesses into SOMA's runtime adapter.
- Adaptation: remove task CLI/ten-iteration limit, swallowed motor errors, cursor circling animation and fixed one-second delay; validate coordinates/keys; add negative monitor origins, DPI, Unicode keyboard events, drag/scroll and teaching inhibition. Current `pyautogui.size()` conversion is insufficient for SOMA's full multimonitor contract.
- Probe: isolated upstream `write` and `press` methods executed against a fake PyAutoGUI object. Confirmed character writes and paired key events. This verifies method translation, not real input or screenshot support. Dependencies/model inference/live desktop were not run.

## Agent S3 and S4

Read root `README.md`, root `LICENSE`, `agent_s4/README.md`, `gui_agents/s3/README.md`, `gui_agents/s3/cli_app.py`, `agents/grounding.py`, `utils/common_utils.py`, `utils/local_env.py` and inspected S4 harness/setup paths. [Pinned source](https://github.com/simular-ai/Agent-S/tree/0fff0e634869dab72027435b4586e62300185d41).

- Current README announces S4 on 2026-10-20. S4 is a separate package evolving Python "shadow interfaces" through a builder and benchmark tasks on AWS VMs. Its results and name do not imply a screen-only runtime.
- Windows/Linux: S3 README advertises Windows/macOS/Linux; CLI uses `pyautogui.screenshot()`. Linux app switching uses `wmctrl` to enumerate/activate windows. No Wayland ScreenCast/RemoteDesktop/libei path was established by this audit.
- Reject concrete forbidden routes: `cli_app.py` runs `exec(code[0])`; `common_utils.py` evaluates action expressions; `grounding.py` defines `SET_CELL_VALUES_CMD` using LibreOffice UNO socket access, `call_code_agent` with direct code execution, `wmctrl` window introspection, Unicode clipboard writes and automatic apt/pip subprocess installation. `local_env.py` executes bash/Python directly. These are execution architecture choices, not dependencies that can safely be disabled by prompt alone.
- Adaptation if any future code reuse: retain only pure visual planner/feedback components; replace all output with SOMA's closed JSON action schema; remove code agent, UNO, clipboard, window queries, shell and arbitrary evaluation. Audit transitive imports again after extraction. Current recommendation is conceptual reference only.
- Probe: isolated S3 `OSWorldACI.type` generated a Unicode action string containing clipboard and subprocess-install routes. The generated string was inspected and **never executed**. This is code-generation evidence only. No live model/desktop benchmark was run.

## UI-TARS Desktop

Read root `README.md`/`LICENSE`, `docs/quick-start.md`, `docs/sdk.md`, both `packages/ui-tars/operators/nut-js/src/index.ts` and `multimodal/gui-agent/operator-nutjs/src/NutJSOperator.ts`, Electron operator `apps/ui-tars/src/main/agent/operator.ts`, and `electron-builder.yml`. [Pinned source](https://github.com/bytedance/UI-TARS-desktop/tree/3ac2cb8d946d78d5ff92ad17b318eaafa18c178c).

- Windows: documented local desktop operator; NutJS screenshot capture and mouse/key actions exist. Electron captures screen sources (not window contents). Both desktop operators implement Windows text through clipboard read/write and Ctrl+V, which violates SOMA's explicit event-only typing requirement.
- Linux: builder config lists AppImage/snap/deb targets; README features list Windows/macOS/browser and the quick start documents Windows/macOS. Package targets alone do not establish Linux runtime support. No explicit X11/Wayland portal/libei implementation was established in these adapters. Linux remains unverified upstream.
- Reject: remote computer/browser operator and the Agent TARS DOM/hybrid browser, MCP and shell tool stacks. Their presence in the monorepo means the whole package is not a compliant SOMA body.
- Adaptation: own capture/input adapter; replace clipboard with keyboard synthesis, preserve whitespace instead of `.trim()`, validate zero/edge coordinates (legacy drag guard uses truthiness), correct monitor/DPI mapping, replace fixed sleeps with visual feedback. Broad Electron/MCP stack is unnecessary for a minimal SOMA widget.
- Probe: static TypeScript structural check located the action manifest, screenshot call and Windows clipboard route. No JS dependencies installed and no TypeScript/GUI runtime exercised. This is explicitly a static PoC, leaving native integration PoC outstanding.

## Computer Use OOTB

Read root `README.md`/`LICENSE`, `computer_use_demo/loop.py`, `tools/computer.py`, `tools/screen_capture.py`, both executor modules, and shell/edit tool registration and implementations. [Pinned source](https://github.com/showlab/computer_use_ootb/tree/21b05ae06de89700b998dc85d8ef64454f0d0291).

- Windows: README support and screenshot code using `screeninfo` monitor geometry plus Pillow capture; keyboard/mouse via PyAutoGUI.
- Linux/X11: code contains a fallback using an `xrandr` shell pipeline and Pillow; README only claims Windows/macOS. This is an unverified fallback, not established Linux support. No Wayland support established. Querying monitor geometry is within SOMA's permitted technical geometry; expose no arbitrary shell route when replacing this helper.
- Reject: Anthropic actor/executor registers `BashTool` and `EditTool` by default; `ComputerTool` itself contains an async `shell` method. ShowUI executor registers only `ComputerTool`, but importing the broad tool module retains unacceptable capability surface. Do not inherit Gradio public sharing/dashboard.
- Adaptation: fixed typed action port; remove all shell/edit tools, temporary screenshot-file assumptions and platform-specific shell pipelines; handle negative monitor origins and screen offsets explicitly.
- Probe: isolated upstream `scale_coordinates` maps model midpoint `(683,384)` to `(960,540)` on a 1920×1080 screen. Input `(1500,300)` is accepted despite exceeding the 1366 model width and maps beyond physical width. SOMA must validate coordinates in the correct coordinate space. No live screenshot, input or model run was attempted.

## Licenses and delivery obligations

The checked-in `LICENSE` files, not inferred README badges, determine these code license findings. Preserve the MIT copyright/permission notice for copied or substantial portions of Self-Operating Computer (and the bundled Prime runtime if reused). For any Apache-2.0 code reuse, distribute the license, retain relevant copyright/patent/trademark/attribution notices, mark changed files, and carry relevant NOTICE attribution when supplied. No tracked `NOTICE*` files were found in these four pins. Apache-2.0 includes patent terms and does not grant trademark rights. These are source license observations, not a complete dependency/legal clearance.

No model weights were downloaded or licensed by this audit. Code licenses do not establish weight rights. Dependencies were not installed; their resolved transitive licenses/SBOM must be checked for the actual release environment. Merely reading or referencing these repositories does not make them bundled runtime dependencies.

## Reproduction and verification limits

Run `python docs/upstream/gui_audit.py` from the repository root after creating the clones with the commands in the JSON evidence. The script refuses changed commit pins, hashes tracked licenses, parses selected Python source, records source line markers, and runs three isolated Python probes plus one static TypeScript probe. It does not import upstream packages or execute generated motor scripts. A passing run proves those limited checks only.

Live Windows/X11/Wayland integration, multi-monitor/DPI/layout behavior, model inference quality, task success and installer delivery are **not** verified by this audit. In particular, there is no credible upstream basis here for claiming universal Wayland input injection. Initial SOMA implementation should explicitly support Windows/X11 adapters and report unavailable Wayland support until tested portal-based adapters exist.
