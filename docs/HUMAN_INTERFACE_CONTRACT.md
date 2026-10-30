# HumanInterfacePort contract

Production application observation is `ScreenFrame`: PNG pixels, virtual desktop
size/origin, physical monitor rectangles, frame ID and wall/monotonic capture
times. There are no window titles, process IDs, OCR fields, DOM or accessibility
objects. Vision may infer semantics only from these pixels.

Input primitives are mouse move/button/scroll and keyboard press/release. Closed
composites: click, double_click, drag, move, scroll, key, hotkey, type_text and
wait. Normalized coordinates reference the entire composite screenshot, including
negative desktop origins. Monitor gaps are rejected. Text is emitted as keyboard
events, never clipboard or direct field assignment. Held input is released on
exceptions, teaching, suspension and shutdown.

Windows uses MSS screen pixels and pynput SendInput. Native desktop availability
is checked before capture and input; secure/locked desktops are not bypassed.
Linux/X11 uses MSS and explicit xorg input. Wayland is rejected before XWayland
could create a misleading partial implementation. A future portal adapter must
preserve this same port.

Inference HTTP is only cognition. SQLite, backups, configuration, tray singleton,
credential vault and power/session APIs operate on SOMA's own implementation.
None supplies application content. The source-level contract test blocks common
bypass imports/calls; this is a regression guard, not a security sandbox or an
exhaustive proof of transitive dependency behavior.
