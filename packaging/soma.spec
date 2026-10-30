# Build from the project root: python -m PyInstaller packaging/soma.spec
from pathlib import Path
import sys

root = Path(SPECPATH).parent
windows = sys.platform == 'win32'
backend = 'win32' if windows else 'xorg'
hidden = ['pynput.mouse._' + backend, 'pynput.keyboard._' + backend,
          'pynput._util.' + backend, 'keyring.backends.Windows' if windows else 'keyring.backends.SecretService']
datas = [(str(root / 'docs'), 'docs'), (str(root / 'README.md'), '.'),
         (str(root / 'THIRD_PARTY_NOTICES.md'), '.'), (str(root / 'LICENSE'), '.'),
         (str(root / 'artifacts' / sys.platform / 'licenses'), 'licenses'),
         (str(root / 'artifacts' / sys.platform / 'sbom.cdx.json'), '.')]
a = Analysis([str(root / 'packaging/entrypoint.py')], pathex=[str(root)],
    binaries=[], datas=datas, hiddenimports=hidden, hookspath=[], hooksconfig={},
    runtime_hooks=[], excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineQuick', 'PySide6.QtQml', 'PySide6.QtQuick',
        'PySide6.QtQuickWidgets', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'tkinter'],
    noarchive=False)
if windows:
    # Qt's unversioned ICU imports use Windows' system ICU. A third-party
    # Poppler ICU found on PATH exports versioned *_78 symbols and breaks
    # QtCore at startup if collected under the same icuuc.dll basename.
    a.binaries = [entry for entry in a.binaries
                  if Path(entry[0]).name.lower() not in {'icuuc.dll', 'icudt78.dll'}]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='SOMA', debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    manifest=str(root / 'packaging/windows/app.manifest') if windows else None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='SOMA')
