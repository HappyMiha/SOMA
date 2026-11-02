"""Developer build utility; never shipped as an agent tool."""

import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / 'artifacts' / sys.platform


def notices():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    licenses = ARTIFACTS / 'licenses'
    licenses.mkdir(exist_ok=True)
    components = []
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        name, version = dist.metadata['Name'], dist.version
        components.append({'type': 'library', 'name': name, 'version': version,
                           'purl': f'pkg:pypi/{name.lower()}@{version}',
                           'licenses': [{'license': {'name': dist.metadata.get('License-Expression') or
                                                    dist.metadata.get('License', 'See bundled license')}}]})
        for file in dist.files or []:
            if Path(str(file)).name.lower().startswith(('license', 'copying', 'notice')):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    target = licenses / name / Path(str(file)).name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # Avoid replacing one package's different same-name licenses.
                    if target.exists() and target.read_bytes() != source.read_bytes():
                        target = target.with_name(hashlib.sha256(str(file).encode()).hexdigest()[:8] + '-' + target.name)
                    shutil.copyfile(source, target)
    required = ROOT / 'packaging/licenses'
    if required.exists():
        shutil.copytree(required, licenses / 'required-license-texts', dirs_exist_ok=True)
    sbom = {'bomFormat': 'CycloneDX', 'specVersion': '1.5', 'version': 1,
            'metadata': {'component': {'type': 'application', 'name': 'SOMA', 'version': '0.2.0'}},
            'components': components}
    (ARTIFACTS / 'sbom.cdx.json').write_text(json.dumps(sbom, indent=2), 'utf-8')
    subprocess.run([sys.executable, '-m', 'pip', 'freeze', '--all'], check=True,
                   stdout=(ARTIFACTS / ('requirements-' + sys.platform + '.lock.txt')).open('w'))


def linux_deb():
    import tempfile
    # Stage on Linux's native filesystem: DrvFs checkouts can expose every file
    # as 0777, which is unsuitable for both dpkg control files and installed code.
    with tempfile.TemporaryDirectory(prefix='soma-deb-') as temporary:
        package = Path(temporary) / 'root'
        (package / 'opt').mkdir(parents=True)
        shutil.copytree(ROOT / 'dist' / sys.platform / 'SOMA', package / 'opt/soma', symlinks=True)
        applications = package / 'usr/share/applications'
        applications.mkdir(parents=True)
        shutil.copyfile(ROOT / 'packaging/linux/soma.desktop', applications / 'soma.desktop')
        autostart = package / 'etc/xdg/autostart'
        autostart.mkdir(parents=True)
        shutil.copyfile(ROOT / 'packaging/linux/soma.desktop', autostart / 'soma.desktop')
        control = package / 'DEBIAN'
        control.mkdir()
        (control / 'control').write_text('Package: soma-desktop\nVersion: 0.2.0\nSection: utils\nPriority: optional\n'
            'Architecture: amd64\nMaintainer: SOMA Project\n'
            'Depends: libc6 (>= 2.38), libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-randr0, '
            'libxcb-render-util0, libxcb-shape0, libxcb-sync1, libxcb-xfixes0, libxcb-xkb1, '
            'libxkbcommon-x11-0, libegl1, libopengl0, libgl1, libdbus-1-3, libx11-6, libx11-xcb1, libxtst6\n'
            'Recommends: gnome-keyring\nDescription: SOMA / SOMIK native pixels-only desktop personality\n', 'utf-8')
        package.chmod(0o755)
        for path in package.rglob('*'):
            if not path.is_symlink():
                path.chmod(0o755 if path.is_dir() or path == package / 'opt/soma/SOMA' else 0o644)
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(package),
                        str(ARTIFACTS / 'SOMA-0.2.0-linux-amd64.deb')], check=True)


def checksums():
    paths = sorted(p for p in ARTIFACTS.iterdir() if p.suffix in {'.exe', '.deb', '.zip'})
    (ARTIFACTS / 'SHA256SUMS.txt').write_text(''.join(
        hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n' for p in paths), 'utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--notices-only', action='store_true')
    parser.add_argument('--iscc', type=Path)
    args = parser.parse_args()
    notices()
    if args.notices_only:
        return
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
                    '--distpath', str(ROOT / 'dist' / sys.platform),
                    '--workpath', str(ROOT / 'build' / sys.platform), str(ROOT / 'packaging/soma.spec')],
                    cwd=ROOT, check=True)
    if sys.platform == 'win32':
        if not args.iscc:
            raise SystemExit('Pass --iscc path/to/ISCC.exe to build the Windows installer')
        subprocess.run([str(args.iscc), str(ROOT / 'packaging/windows/soma.iss')], cwd=ROOT, check=True)
    else:
        linux_deb()
    checksums()


if __name__ == '__main__':
    main()
