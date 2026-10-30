# SOMA repository instructions

SOMA and SOMIK are one persistent identity. Follow docs/SOMA_IMPLEMENTATION_SPEC.md.
All production interaction with applications MUST pass through HumanInterfacePort:
monitor pixels, native mouse events, native keyboard events. No DOM/CDP, app APIs,
accessibility/UIA, clipboard, hidden shell or user-file/process/window inspection.
Own memory/configuration, inference and OS session lifecycle are separate internals.

Never call a mock or fixture a real autonomous agent. Report actual OS/session,
model, device tests, commit and limitations. Do not close acceptance phases only
because code exists. Native Wayland remains unavailable until a tested portal
adapter exists. Keep persona ID/history stable on every upgrade and failure.

Teaching hooks may exist only during explicit visible demonstrations. Privacy
must omit both pixels and keys. Journal before native input and never blindly
replay unresolved actions. Stale inference must be invalidated by lifecycle changes.

The user-level karpathy workflow remains opt-in when explicitly invoked.
Run relevant tests with a workspace-owned --basetemp if system Temp has old ACLs.
Build platform bundles separately (dist/win32, dist/linux); maintain bundled
license texts, SBOM and checksums. No source licensing choice or release signing
certificate has been supplied by the owner.
