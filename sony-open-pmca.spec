# Build with: .venv/bin/python -m PyInstaller sony-open-pmca.spec

import ctypes.util
from pathlib import Path
import subprocess
import sys

if sys.platform != 'darwin':
 raise RuntimeError('This app specification requires macOS')

root = Path(SPECPATH)
def find_libusb():
 lib = ctypes.util.find_library('usb-1.0')
 if lib and Path(lib).exists():
  return str(Path(lib).resolve())
 for candidate in ['/opt/homebrew/lib/libusb-1.0.dylib', '/usr/local/lib/libusb-1.0.dylib']:
  if Path(candidate).exists():
   return str(Path(candidate).resolve())
 raise RuntimeError('Install libusb before building: brew install libusb')

libusb = find_libusb()

from pmca import __version__ as version
versionDir = root / 'build' / 'sony-open-pmca-version'
versionDir.mkdir(parents=True, exist_ok=True)
(versionDir / 'frozenversion.py').write_text('version = %r\n' % version)

a = Analysis(
 [str(root / 'pmca-gui.py')],
 pathex=[str(versionDir)],
 binaries=[(str(Path(libusb).resolve()), '.')],
 datas=[
  (str(root / 'certs/localtest.me.pem'), 'certs'),
  (str(root / 'assets/sony-open-pmca.png'), 'assets'),
  (str(root / 'assets/sony-open-pmca.svg'), 'assets'),
  (str(root / 'LICENSE.txt'), '.'),
 ],
 hiddenimports=['usb.backend.libusb1', 'frozenversion'],
 excludes=['pmca.usb.driver.windows'],
)
pyz = PYZ(a.pure)
exe = EXE(
 pyz, a.scripts, [],
 exclude_binaries=True,
 name='Sony Open PMCA',
 console=False,
 strip=False,
 upx=False,
 target_arch='arm64',
 argv_emulation=False,
)
coll = COLLECT(
 exe, a.binaries, a.datas,
 strip=False,
 upx=False,
 name='Sony Open PMCA',
)
app = BUNDLE(
 coll,
 name='Sony Open PMCA.app',
 bundle_identifier='org.openpmca.sonyopenpmca',
 icon=str(root / 'assets/sony-open-pmca.icns'),
 version='1.0.0',
 info_plist={
  'CFBundleDisplayName': 'Sony Open PMCA',
  'CFBundleShortVersionString': '1.0.0',
  'CFBundleVersion': '1.0.0',
  'NSHighResolutionCapable': True,
 },
)
