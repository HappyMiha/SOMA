# Third-party notices

SOMA uses independently installed/bundled dependencies; their exact versions and
license texts are included under `licenses/` and `sbom.cdx.json` in each package.
The build environment inventory is also included; some development-only packages
may appear in the SBOM even though PyInstaller does not bundle them.

PySide6 Essentials / Shiboken and the Qt libraries are dynamically linked,
unmodified distributions of Qt for Python. Applicable LGPLv3/GPLv3/commercial
terms and exceptions are included in their license files. SOMA uses Qt Core,
Gui, Widgets, Network and (on Linux) DBus; it does not ship Qt WebEngine. Users
can replace the dynamic libraries in `_internal` with compatible modified builds.
Qt and PySide source/build instructions: https://code.qt.io/pyside/pyside-setup.git/
and https://code.qt.io/qt/qtbase.git/ . Match the versions in the package SBOM.
No restriction on reverse engineering for debugging modifications to these LGPL
libraries is imposed by SOMA. Package maintainers must retain these materials.

MSS (MIT), pynput (LGPLv3), Pillow (HPND), HTTPX/HTTPCore (BSD-3-Clause),
keyring and its dependencies retain their bundled notices. Python and the
PyInstaller bootloader retain their own licenses and distribution exceptions.

Upstream agent projects listed in `docs/UPSTREAM_EVALUATION.md` were audited as
references. No source, model weights, branding, benchmark images or datasets from
those repositories is bundled. Aloha's pinned LICENSE is Apache-2.0; Letta's brand
assets are excluded from its code license. Model weights and inference services
are selected separately by the user and are not licensed by this package.

The new SOMA source has no open-source license grant pending the owner's choice.
This development build is unsigned. No Windows or Linux signing certificate was
invented; release signing remains a release gate.
