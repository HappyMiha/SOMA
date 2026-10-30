# SOMA 0.1.0 — development package

Implementation source commit: `4b4d3357f6b8e883b27e138fa70cb1e44a5b14a9`.
Later evidence-only commits retain the same production source.

| Artifact | Size | SHA256 |
|---|---:|---|
| Windows x64 installer | 43,729,574 bytes | `9fe9fb062a36294ef77df820ba56c3a09d307e90547af8eed5aae0307d56ef32` |
| Linux amd64 .deb | 62,757,074 bytes | `6b3f4d9cf98eda90db42d3c35f2aa174cf106cb3e02800d66a659bbd02f7aaea` |

Local files: `artifacts/win32/SOMA-0.1.0-windows-x64-setup.exe` and
`artifacts/linux/SOMA-0.1.0-linux-amd64.deb`. Platform directories include SBOM,
dependency inventories, license texts and SHA256SUMS. The installers are unsigned.
Windows minimum is build 19041. The Linux build requires glibc >=2.38 and the
declared XCB/X11 libraries; Ubuntu 24.04 WSL/Xvfb is the actual test environment.

Windows and Linux source suites: **108 passed, 15 subtests passed**. Live owned
Windows GUI device evidence and isolated virtual X11 device evidence are in
`evidence/windows-desktop/` and `evidence/linux-x11/`. Both final packaged binaries
passed two sequential native life-loop smoke runs with a deterministic localhost
wait-only cognition stub, retaining one identity and durable checkpoints, without
input intents or demonstration hooks. Final installer/extraction/runtime reports:
`evidence/windows-package/verification.json` and
`evidence/linux-package/verification.json`.

This development package does not close the full specification DoD. Real VLM
autonomy/browser tasks, real correspondence, model-based skill transfer, physical
Linux/Wayland, two physical reboots, 24–72 h endurance, hardware resource/cost
baselines, clean-machine upgrades and public signing remain open. Configure a
local/remote multimodal endpoint in the native widget; no model weights or user
credentials are bundled. See IMPLEMENTATION_STATUS.md for the phase checklist.
