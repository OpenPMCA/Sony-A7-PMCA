#!/usr/bin/env python3
"""Sony Open PMCA desktop distribution and packaging CLI.

Actions:
  build: Run PyInstaller for the native platform.
  package: Produce the native distribution asset (macOS ZIP + Cask, Windows EXE, Linux AppImage).
  verify: Execute frozen runtime check (--check-runtime) and strictly validate report fields.
"""

import argparse
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import urllib.request

# Pinned upstream build dependencies
APPIMAGETOOL_VERSION = "1.9.1"
APPIMAGETOOL_URL = f"https://github.com/AppImage/appimagetool/releases/download/{APPIMAGETOOL_VERSION}/appimagetool-x86_64.AppImage"
APPIMAGETOOL_SHA256 = "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"

LIBUSB_PACKAGE_VERSION = "1.0.30.0"
LIBUSB_PACKAGE_WIN_AMD64_SHA256 = "90808da724c8939a333d931d0c7226372ca5fefd98e2f2f3ef79fd918aa37522"

REPO_ROOT = Path(__file__).resolve().parent.parent


def get_version() -> str:
    """Read version from pmca package."""
    sys_path_added = str(REPO_ROOT) not in sys.path
    if sys_path_added:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from pmca import __version__ as ver
        return ver
    except Exception as error:
        raise RuntimeError("Cannot read application version") from error
    finally:
        if sys_path_added:
            sys.path.remove(str(REPO_ROOT))


def normalize_arch(arch: str) -> str:
    """Normalize architecture names."""
    a = arch.lower()
    if a in ("arm64", "aarch64"):
        return "arm64"
    if a in ("x86_64", "amd64", "x64"):
        return "x64"
    return a


def get_asset_name(os_name: str, version: str = None, arch: str = None) -> str:
    """Return canonical versioned asset name for platform."""
    version = version or get_version()
    os_lower = os_name.lower()
    if "darwin" in os_lower or "mac" in os_lower:
        target_arch = arch or "arm64"
        return f"Sony-Open-PMCA-{version}-macos-{target_arch}.zip"
    elif "win" in os_lower:
        target_arch = arch or "x64"
        return f"Sony-Open-PMCA-{version}-windows-{target_arch}.exe"
    elif "linux" in os_lower:
        target_arch = arch or "x86_64"
        return f"Sony-Open-PMCA-{version}-linux-{target_arch}.AppImage"
    else:
        target_arch = arch or "unknown"
        return f"Sony-Open-PMCA-{version}-{os_lower}-{target_arch}.bin"


def get_apprun_content() -> str:
    """Return AppRun launcher script with quoted argument forwarding."""
    return """#!/bin/sh
set -e

APPDIR="$(dirname "$(readlink -f "$0")")"
export APPDIR

# Environment for bundled libraries, Tcl/Tk, and certs
export LD_LIBRARY_PATH="$APPDIR/usr/lib:$APPDIR/usr/lib/x86_64-linux-gnu:$APPDIR/usr/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="$APPDIR/usr/bin:$APPDIR${PATH:+:$PATH}"

# Run frozen binary, forwarding all arguments quoted
if [ -x "$APPDIR/usr/bin/Sony-Open-PMCA" ]; then
    exec "$APPDIR/usr/bin/Sony-Open-PMCA" "$@"
elif [ -x "$APPDIR/Sony-Open-PMCA" ]; then
    exec "$APPDIR/Sony-Open-PMCA" "$@"
else
    echo "Error: Sony-Open-PMCA binary not found in AppDir" >&2
    exit 1
fi
"""


def find_libusb(platform_override: str = None) -> Path:
    """Locate libusb shared library or raise an explicit RuntimeError with install guidance."""
    target_platform = platform_override or sys.platform

    if target_platform == "darwin":
        lib = ctypes.util.find_library("usb-1.0")
        if lib and Path(lib).exists():
            return Path(lib).resolve()
        for p in [
            "/opt/homebrew/lib/libusb-1.0.dylib",
            "/usr/local/lib/libusb-1.0.dylib",
        ]:
            if Path(p).exists():
                return Path(p).resolve()
        raise RuntimeError(
            "libusb shared library (libusb-1.0.dylib) not found for macOS.\n"
            "Install via: brew install libusb"
        )

    elif target_platform == "win32":
        try:
            import libusb_package
            dll_path = libusb_package.get_library_path()
            if dll_path and Path(dll_path).exists():
                return Path(dll_path).resolve()
        except ImportError:
            pass
        lib_name = ctypes.util.find_library("libusb-1.0") or ctypes.util.find_library("usb-1.0")
        if lib_name and Path(lib_name).exists():
            return Path(lib_name).resolve()
        for name in ["libusb-1.0.dll"]:
            for p in os.environ.get("PATH", "").split(os.pathsep):
                cand = Path(p) / name
                if cand.exists():
                    return cand.resolve()
        raise RuntimeError(
            "libusb dynamic library (libusb-1.0.dll) not found for Windows.\n"
            "Install via: pip install libusb-package (pinned 1.0.30.0)\n"
            "Or place libusb-1.0.dll on PATH."
        )

    elif target_platform.startswith("linux"):
        lib_name = ctypes.util.find_library("usb-1.0") or ctypes.util.find_library("libusb-1.0")
        if lib_name:
            for sdir in [
                "/usr/lib/x86_64-linux-gnu",
                "/usr/lib64",
                "/usr/lib",
                "/lib/x86_64-linux-gnu",
                "/lib64",
                "/usr/local/lib",
            ]:
                cand = Path(sdir) / lib_name
                if cand.exists():
                    return cand.resolve()
                cand_so = Path(sdir) / "libusb-1.0.so.0"
                if cand_so.exists():
                    return cand_so.resolve()
            return Path(lib_name)
        for cand_path in [
            "/usr/lib/x86_64-linux-gnu/libusb-1.0.so.0",
            "/usr/lib/x86_64-linux-gnu/libusb-1.0.so",
            "/usr/lib64/libusb-1.0.so.0",
            "/usr/lib64/libusb-1.0.so",
            "/usr/lib/libusb-1.0.so.0",
            "/usr/lib/libusb-1.0.so",
        ]:
            p = Path(cand_path)
            if p.exists():
                return p.resolve()
        raise RuntimeError(
            "libusb 1.0 shared library (libusb-1.0.so) not found for Linux.\n"
            "Install via: sudo apt-get install libusb-1.0-0 libusb-1.0-0-dev"
        )
    else:
        raise RuntimeError(f"Unsupported platform: {target_platform}. libusb location unknown.")


def validate_runtime_report(
    report_data_or_path, expected_version: str = None, expected_arch: str = None
) -> dict:
    """Strictly validate runtime report fields and return validation dict.
    
    Enforces exact boolean True for:
      - frozen
      - libusb_loads
      - spk_roundtrip
      - certificate_key_parses
      - tls_handshake_verified
    Enforces matching version and architecture.
    """
    expected_version = expected_version or get_version()
    if isinstance(report_data_or_path, (str, Path)):
        p = Path(report_data_or_path)
        if not p.exists():
            return {"valid": False, "errors": [f"Report file not found: {p}"]}
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    elif isinstance(report_data_or_path, dict):
        data = report_data_or_path
    else:
        return {"valid": False, "errors": ["Invalid report input type"]}

    errors = []

    # Strict boolean checks (must be True, not just truthy)
    boolean_fields = [
        "frozen",
        "libusb_loads",
        "spk_roundtrip",
        "certificate_key_parses",
        "tls_handshake_verified",
    ]
    for field in boolean_fields:
        val = data.get(field)
        if val is not True:
            errors.append(f"Field '{field}' must be strictly True, got: {val!r}")

    # Version check
    actual_ver = data.get("version")
    if actual_ver != expected_version:
        errors.append(f"Version mismatch: expected '{expected_version}', got '{actual_ver}'")

    # Architecture check
    if expected_arch:
        actual_arch = str(data.get("architecture", "")).lower()
        exp_arch_norm = normalize_arch(expected_arch)
        act_arch_norm = normalize_arch(actual_arch)
        if exp_arch_norm != act_arch_norm:
            errors.append(
                f"Architecture mismatch: expected '{expected_arch}', got '{actual_arch}'"
            )

    # Tcl check
    tcl_ver = data.get("tcl_version")
    if not tcl_ver or not isinstance(tcl_ver, str):
        errors.append(f"Invalid or missing tcl_version: {tcl_ver!r}")

    return {"valid": len(errors) == 0, "errors": errors, "report": data}


def get_macos_minimum(app_path: Path) -> str:
    """Read the highest macOS deployment target among bundled native dependencies."""
    binary = app_path / 'Contents' / 'MacOS' / 'Sony Open PMCA'
    versions = []
    seen = set()
    for path in app_path.rglob('*'):
        if not path.is_file() or path.resolve() in seen:
            continue
        seen.add(path.resolve())
        with path.open('rb') as stream:
            magic = stream.read(4)
        if path != binary and path.suffix not in ('.dylib', '.so') and magic not in (
                b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf',
                b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'):
            continue
        output = subprocess.check_output(['otool', '-l', str(path)]).decode('utf-8')
        for block in re.split(r'Load command \d+', output):
            if 'cmd LC_BUILD_VERSION' in block:
                field = 'minos'
            elif 'cmd LC_VERSION_MIN_MACOSX' in block:
                field = 'version'
            else:
                continue
            match = re.search(r'^\s*' + field + r'\s+(\d+\.\d+(?:\.\d+)?)', block, re.MULTILINE)
            if match:
                versions.append(tuple(int(component) for component in match.group(1).split('.')))
    if not versions:
        raise RuntimeError('No macOS deployment targets found in bundle')
    return '.'.join(str(component) for component in max(versions))


def render_cask(version: str = None, sha256_hex: str = "", min_macos: str = "11.0") -> str:
    """Render Homebrew cask Ruby definition for Sony Open PMCA."""
    version = version or get_version()
    if not sha256_hex or len(sha256_hex) != 64:
        raise ValueError("Valid 64-character SHA-256 checksum is required for Homebrew cask")
    releases = {'11': 'big_sur', '12': 'monterey', '13': 'ventura',
                '14': 'sonoma', '15': 'sequoia', '26': 'tahoe', '27': 'golden_gate'}
    major = min_macos.split('.')[0]
    if major not in releases:
        raise ValueError('Unknown minimum macOS version: %s' % min_macos)
    return f"""cask "sony-open-pmca" do
  version "{version}"
  sha256 "{sha256_hex}"

  url "https://github.com/OpenPMCA/Sony-Open-PMCA/releases/download/v#{{version}}/Sony-Open-PMCA-#{{version}}-macos-arm64.zip"
  name "Sony Open PMCA"
  desc "GUI application to manage apps on Sony Alpha cameras"
  homepage "https://github.com/OpenPMCA/Sony-Open-PMCA"

  depends_on arch: :arm64
  depends_on macos: :{releases[major]}

  app "Sony Open PMCA.app"

  zap trash: [
    "~/Library/Saved Application State/org.openpmca.sonyopenpmca.savedState",
  ]
end
"""


def compute_sha256(file_path: Path) -> str:
    """Compute hex SHA-256 digest of file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def package_macos(app_path: Path = None, out_dir: Path = None, version: str = None) -> dict:
    """Package existing macOS .app bundle into deterministic ARM64 ZIP and generate Cask."""
    ver = version or get_version()
    dist_dir = out_dir or (REPO_ROOT / "dist")
    target_app = app_path or (dist_dir / "Sony Open PMCA.app")

    if not target_app.exists():
        raise FileNotFoundError(f"macOS app bundle not found at {target_app}")

    # Verify architecture is ARM64
    bin_path = target_app / "Contents" / "MacOS" / "Sony Open PMCA"
    file_out = subprocess.check_output(["file", str(bin_path)]).decode("utf-8")
    if "arm64" not in file_out.lower():
        raise RuntimeError(f"macOS binary is not ARM64: {file_out}")

    # Verify code signature
    subprocess.check_call(["codesign", "--verify", "--deep", "--strict", str(target_app)])

    # Create a versioned ZIP preserving bundle symlinks
    zip_name = get_asset_name("macos", version=ver, arch="arm64")
    zip_path = dist_dir / zip_name
    if zip_path.exists():
        zip_path.unlink()

    # Preserve symlinks without adding AppleDouble metadata to the archive
    subprocess.check_call(["ditto", "-c", "-k", "--norsrc", "--keepParent", str(target_app), str(zip_path)])

    sha256_hex = compute_sha256(zip_path)

    # Render and write Casks/sony-open-pmca.rb
    cask_dir = REPO_ROOT / "Casks"
    cask_dir.mkdir(parents=True, exist_ok=True)
    cask_file = cask_dir / "sony-open-pmca.rb"
    cask_content = render_cask(version=ver, sha256_hex=sha256_hex, min_macos=get_macos_minimum(target_app))
    cask_file.write_text(cask_content, encoding="utf-8")

    return {
        "zip_path": zip_path,
        "sha256": sha256_hex,
        "cask_path": cask_file,
    }


def download_and_verify_appimagetool(dest_path: Path) -> Path:
    """Download appimagetool and verify against pinned SHA-256."""
    if dest_path.exists():
        if compute_sha256(dest_path) == APPIMAGETOOL_SHA256:
            return dest_path
        dest_path.unlink()

    print(f"Downloading appimagetool {APPIMAGETOOL_VERSION}...")
    urllib.request.urlretrieve(APPIMAGETOOL_URL, dest_path)
    digest = compute_sha256(dest_path)
    if digest != APPIMAGETOOL_SHA256:
        dest_path.unlink()
        raise ValueError(
            f"appimagetool checksum mismatch!\nExpected: {APPIMAGETOOL_SHA256}\nGot:      {digest}"
        )
    dest_path.chmod(0o755)
    return dest_path


def package_linux_appimage(
    dist_dir: Path = None, appimagetool_path: Path = None, version: str = None
) -> dict:
    """Assemble Linux AppDir and create AppImage."""
    ver = version or get_version()
    d_dir = dist_dir or (REPO_ROOT / "dist")
    binary_dir = d_dir / "Sony-Open-PMCA"
    if not binary_dir.exists():
        raise FileNotFoundError(f"Linux binary directory not found at {binary_dir}")

    appdir = d_dir / "Sony-Open-PMCA.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)
    appdir.mkdir(parents=True, exist_ok=True)

    # Copy binary and resources into AppDir
    shutil.copytree(binary_dir, appdir / "usr" / "bin")

    # Install AppRun
    apprun = appdir / "AppRun"
    apprun.write_text(get_apprun_content(), encoding="utf-8")
    apprun.chmod(0o755)

    # Install Desktop Entry
    desktop_src = REPO_ROOT / "packaging" / "linux" / "sony-open-pmca.desktop"
    shutil.copy2(desktop_src, appdir / "sony-open-pmca.desktop")

    # Install Icon
    icon_src = REPO_ROOT / "assets" / "sony-open-pmca.png"
    if icon_src.exists():
        shutil.copy2(icon_src, appdir / "sony-open-pmca.png")
        shutil.copy2(icon_src, appdir / ".DirIcon")

    # Run appimagetool
    tool_bin = appimagetool_path
    if not tool_bin:
        found = shutil.which("appimagetool")
        if found:
            tool_bin = Path(found)
    if not tool_bin or not Path(tool_bin).is_file():
        cache_dir = REPO_ROOT / "build" / "tools"
        cache_dir.mkdir(parents=True, exist_ok=True)
        tool_bin = download_and_verify_appimagetool(cache_dir / "appimagetool-x86_64.AppImage")

    out_name = get_asset_name("linux", version=ver, arch="x86_64")
    out_path = d_dir / out_name

    env = os.environ.copy()
    env["ARCH"] = "x86_64"
    env["APPIMAGE_EXTRACT_AND_RUN"] = "1"
    subprocess.check_call([str(tool_bin), str(appdir), str(out_path)], env=env)

    return {"appimage_path": out_path, "sha256": compute_sha256(out_path)}


def package_windows_exe(dist_dir: Path = None, version: str = None) -> dict:
    """Verify and rename Windows one-file EXE to canonical versioned asset name."""
    ver = version or get_version()
    d_dir = dist_dir or (REPO_ROOT / "dist")
    exe_src = d_dir / "Sony-Open-PMCA.exe"
    if not exe_src.exists():
        raise FileNotFoundError(f"Windows EXE not found at {exe_src}")

    target_name = get_asset_name("windows", version=ver, arch="x64")
    target_path = d_dir / target_name
    if exe_src != target_path:
        shutil.copy2(exe_src, target_path)

    return {"exe_path": target_path, "sha256": compute_sha256(target_path)}


def run_verify(executable_path: Path, expected_arch: str = None) -> int:
    """Run --check-runtime on the frozen binary and strictly validate output."""
    report_file = REPO_ROOT / "dist" / "runtime-check.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    if report_file.exists():
        report_file.unlink()

    cmd = [str(executable_path), "--check-runtime", str(report_file)]
    print(f"Executing runtime check: {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        print(f"Runtime check process timed out after 60s")
        return 124
    if proc.returncode != 0:
        print(f"Runtime check process failed with status {proc.returncode}")
        print("stdout:", proc.stdout)
        print("stderr:", proc.stderr)
        return proc.returncode

    val = validate_runtime_report(
        report_file, expected_version=get_version(), expected_arch=expected_arch
    )
    if not val.get("valid"):
        print("Runtime report validation FAILED:")
        for err in val.get("errors", []):
            print(f"  - {err}")
        return 1

    print("Runtime report validation PASSED:")
    print(json.dumps(val.get("report", {}), indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Sony Open PMCA Packaging CLI")
    subparsers = parser.add_subparsers(dest="action", required=True)

    # Build action
    p_build = subparsers.add_parser("build", help="Build native executable/bundle")
    p_build.add_argument("--spec", help="Path to PyInstaller spec file")

    # Package action
    p_pkg = subparsers.add_parser("package", help="Create distribution archive/asset")
    p_pkg.add_argument("--version", default=get_version(), help="Asset version")

    # Verify action
    p_verify = subparsers.add_parser("verify", help="Verify frozen runtime report")
    p_verify.add_argument("--executable", help="Path to frozen executable")
    p_verify.add_argument("--report", help="Path to existing report JSON")
    p_verify.add_argument("--arch", help="Expected architecture")

    args = parser.parse_args()

    if args.action == "build":
        spec = args.spec
        if not spec:
            if sys.platform == "darwin":
                spec = str(REPO_ROOT / "sony-open-pmca.spec")
            else:
                spec = str(REPO_ROOT / "packaging" / "desktop.spec")
        subprocess.check_call([sys.executable, "-m", "PyInstaller", spec])

    elif args.action == "package":
        if sys.platform == "darwin":
            res = package_macos(version=args.version)
            print(f"macOS package created: {res['zip_path']} (SHA-256: {res['sha256']})")
            print(f"Cask updated: {res['cask_path']}")
        elif sys.platform.startswith("linux"):
            res = package_linux_appimage(version=args.version)
            print(f"Linux AppImage created: {res['appimage_path']} (SHA-256: {res['sha256']})")
        elif sys.platform == "win32":
            res = package_windows_exe(version=args.version)
            print(f"Windows EXE verified: {res['exe_path']} (SHA-256: {res['sha256']})")
        else:
            print(f"Packaging not supported on platform: {sys.platform}")
            sys.exit(1)

    elif args.action == "verify":
        if args.report:
            val = validate_runtime_report(
                args.report, expected_version=get_version(), expected_arch=args.arch
            )
            if not val.get("valid"):
                print("Validation failed:")
                for err in val.get("errors", []):
                    print(f"  - {err}")
                sys.exit(1)
            print("Validation successful.")
        elif args.executable:
            code = run_verify(Path(args.executable), expected_arch=args.arch)
            sys.exit(code)
        else:
            if sys.platform == "darwin":
                exe = REPO_ROOT / "dist" / "Sony Open PMCA.app" / "Contents" / "MacOS" / "Sony Open PMCA"
                code = run_verify(exe, expected_arch="arm64")
                sys.exit(code)
            else:
                print("Must supply --executable or --report")
                sys.exit(1)


if __name__ == "__main__":
    main()
