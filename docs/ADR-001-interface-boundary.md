# ADR 001: One body port

Accepted 2026-10-30. The runtime may observe application state only as captured
pixels and act only through mouse and keyboard events. Provider output is parsed
as a closed JSON action alphabet; no code execution or tool dispatch exists.

The body may query display geometry, desktop session availability and device
permissions. These are technical capabilities, never application semantics.
Storage, clock, inference HTTP and lifecycle APIs serve SOMA's own implementation.
They do not read user files, application databases, windows, processes or controls.

Upstream audit found exec/eval, clipboard, window metadata and accessibility paths
in otherwise useful references. Whole upstream runtimes are therefore not embedded.
Only documented concepts are adapted. All new application interaction must pass
through HumanInterfacePort, including recovery and learned skills.
