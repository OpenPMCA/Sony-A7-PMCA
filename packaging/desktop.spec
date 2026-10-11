# PyInstaller specification for Windows one-file EXE and Linux directory (for AppImage)
# Build:
#   Windows: python -m PyInstaller packaging/desktop.spec
#   Linux:   python -m PyInstaller packaging/desktop.spec

import ctypes.util
import os
from pathlib import Path
import sys

root = Path(SPECPATH).resolve().parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from pmca import __version__ as version

versionDir = root / 'build' / 'sony-open-pmca-version'
versionDir.mkdir(parents=True, exist_ok=True)
(versionDir / 'frozenversion.py').write_text('version = %r\n' % version)


def find_libusb():
    if sys.platform == 'win32':
        # 1. libusb_package wheel
        try:
            import libusb_package
            dll_path = libusb_package.get_library_path()
            if dll_path and Path(dll_path).exists():
                return Path(dll_path).resolve()
        except ImportError:
            pass
        # 2. ctypes.util.find_library
        lib_name = ctypes.util.find_library('libusb-1.0') or ctypes.util.find_library('usb-1.0')
        if lib_name and Path(lib_name).exists():
            return Path(lib_name).resolve()
        # 3. PATH search
        for name in ['libusb-1.0.dll']:
            for p in os.environ.get('PATH', '').split(os.pathsep):
                candidate = Path(p) / name
                if candidate.exists():
                    return candidate.resolve()
        raise RuntimeError(
            'libusb dynamic library (libusb-1.0.dll) not found for Windows.\n'
            'Install via: pip install libusb-package (pinned 1.0.30.0)\n'
            'Or place libusb-1.0.dll on PATH.'
        )
    elif sys.platform.startswith('linux'):
        lib_name = ctypes.util.find_library('usb-1.0') or ctypes.util.find_library('libusb-1.0')
        if lib_name:
            for search_dir in [
                '/usr/lib/x86_64-linux-gnu',
                '/usr/lib64',
                '/usr/lib',
                '/lib/x86_64-linux-gnu',
                '/lib64',
                '/usr/local/lib',
            ]:
                cand = Path(search_dir) / lib_name
                if cand.exists():
                    return cand.resolve()
                cand_so0 = Path(search_dir) / 'libusb-1.0.so.0'
                if cand_so0.exists():
                    return cand_so0.resolve()
            return Path(lib_name)
        for cand_path in [
            '/usr/lib/x86_64-linux-gnu/libusb-1.0.so.0',
            '/usr/lib/x86_64-linux-gnu/libusb-1.0.so',
            '/usr/lib64/libusb-1.0.so.0',
            '/usr/lib64/libusb-1.0.so',
            '/usr/lib/libusb-1.0.so.0',
            '/usr/lib/libusb-1.0.so',
        ]:
            p = Path(cand_path)
            if p.exists():
                return p.resolve()
        raise RuntimeError(
            'libusb 1.0 shared library (libusb-1.0.so) not found for Linux.\n'
            'Install via: sudo apt-get install libusb-1.0-0 libusb-1.0-0-dev'
        )
    else:
        raise RuntimeError(
            'packaging/desktop.spec is designed for Windows and Linux.\n'
            'On macOS, reuse sony-open-pmca.spec.'
        )


libusb_bin = find_libusb()

# Common data files
datas = [
    (str(root / 'certs' / 'localtest.me.pem'), 'certs'),
    (str(root / 'assets' / 'sony-open-pmca.png'), 'assets'),
    (str(root / 'assets' / 'sony-open-pmca.svg'), 'assets'),
    (str(root / 'LICENSE.txt'), '.'),
]

binaries = [(str(libusb_bin), '.')]

if sys.platform == 'win32':
    hiddenimports = [
        'usb.backend.libusb1',
        'frozenversion',
        'pmca.usb.driver.windows',
        'pmca.usb.driver.windows.wpd',
        'comtypes',
        'comtypes.client',
        'win32com',
        'win32com.client',
    ]
    excludes = ['pmca.usb.driver.osx']
    icon_file = root / 'assets' / 'sony-open-pmca.ico'
    app_icon = str(icon_file) if icon_file.exists() else None

    a = Analysis(
        [str(root / 'pmca-gui.py')],
        pathex=[str(versionDir), str(root)],
        binaries=binaries,
        datas=datas,
        hiddenimports=hiddenimports,
        excludes=excludes,
        runtime_hooks=[str(root / "packaging/runtime_hook_libusb.py")],
    )
    pyz = PYZ(a.pure)
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name='Sony-Open-PMCA',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        icon=app_icon,
    )
elif sys.platform.startswith('linux'):
    datas.append((str(root / 'packaging' / 'linux' / 'sony-open-pmca.desktop'), '.'))
    hiddenimports = ['usb.backend.libusb1', 'frozenversion']
    excludes = ['pmca.usb.driver.windows', 'pmca.usb.driver.osx']

    a = Analysis(
        [str(root / 'pmca-gui.py')],
        pathex=[str(versionDir), str(root)],
        binaries=binaries,
        datas=datas,
        hiddenimports=hiddenimports,
        excludes=excludes,
        runtime_hooks=[str(root / "packaging/runtime_hook_libusb.py")],
    )
    pyz = PYZ(a.pure)
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='Sony-Open-PMCA',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name='Sony-Open-PMCA',
    )
