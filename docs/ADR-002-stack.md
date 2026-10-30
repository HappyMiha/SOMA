# ADR 002: Bundled Python with native Qt

Accepted 2026-10-30. Use PySide6 native desktop widgets, SQLite WAL, MSS pixels,
pynput device input, HTTPX inference, and PyInstaller bundles. This is the
specification's permitted Python implementation, packaged with its interpreter;
end users do not install Python, pip or Docker. Rust is not required to preserve
the interface boundary. No upstream agent runtime is included.

Windows 10 version 2004 (build 19041) or newer, and Linux/X11, are initial targets.
The Windows bundle uses the operating system's unversioned ICU API required by
Qt. Packaging excludes unrelated `icuuc.dll` and `icudt78.dll` discovered on PATH;
the Poppler ICU 78 build exports incompatible versioned symbols. Run
`python packaging/check_windows_bundle.py <bundle-directory>` and the native
runtime smoke after building. Native Wayland is deliberately
unavailable until ScreenCast/RemoteDesktop portal and PipeWire integration can be
validated on actual compositors; XWayland is not silently treated as full access.
This is a release limitation, not a claim of completed Wayland support.

Remote and localhost OpenAI-compatible multimodal endpoints use the same strict
input alphabet. Hybrid fallback is explicit configuration. No model weights are
bundled or implicitly downloaded. Persona continuity is independent of provider.
