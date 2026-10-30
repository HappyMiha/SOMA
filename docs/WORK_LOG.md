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
