# Testing status

Project: Sony A7 PMCA. Version: 1.0.0. Verification date: 2026-10-11.

This document separates automated tests, native runtime checks and actual camera operations. GitHub workflow configuration is not evidence that its jobs have finished successfully.

## Verification matrix

| Area | Recorded result | What this proves | What it does not prove |
|---|---|---|---|
| Source unit tests | Renamed source and relocated folder baseline: 164 tests passed with ResourceWarning treated as an error. Scroll-performance regressions are rechecked before publication. | Covered parsing, download, cache, transport and GUI contracts. | Uncovered hardware behavior or every model/application combination. |
| Native Tk GUI | Prior behavior audit: 23 acceptance cases and 8 packed native-scroll cases passed. Rename regression checks are run separately. | Navigation, list reachability, mouse/trackpad event dispatch, busy controls and Logs behavior under controlled providers. | Windows/Linux native appearance before those runners execute. |
| Store APK downloads | 26 actual HTTPS downloads passed package/API/certificate parsing. | The audited sources delivered inspectable APKs with expected identity and compatible declared minimum API. | Cryptographic trust in every publisher or runtime compatibility on every camera. |
| Apple Silicon frozen runtime | Pre-migration archive passed libusb/Tcl/certificate/encryption/TLS, code-tree parity and deep/strict ad-hoc signature checks. The renamed archive is reverified separately. | Required local dependencies and encrypted loopback exchange worked on the test host. | Apple notarization or older-macOS compatibility. |
| Camera installation | RecipeLab installation on Sony ILCE-7 completed with camera result code 0 and user confirmation. | That selected transfer succeeded on the tested body. | Other app installs or Windows/Linux camera operations. |
| Shutter metadata | Decoder, flash/rollover and bounded MTP contracts tested with fixtures/reference data. | Covered decoder behavior and honest unavailable/ambiguous states. | A current physical-camera count; the camera was disconnected for final verification. |
| Windows EXE | **Passed in CI** ([Run 38108354284](https://github.com/OpenPMCA/Sony-A7-PMCA/actions/runs/38108354284)). | Native 64-bit Windows build, PyInstaller one-file packaging, and `--check-runtime` frozen diagnostic executed and passed on `windows-2022`. | Physical camera communication over Windows WPD driver in production. |
| Linux AppImage | **Passed in CI** ([Run 38108354284](https://github.com/OpenPMCA/Sony-A7-PMCA/actions/runs/38108354284)). | Native Linux build, Xvfb GUI smoke test, `appimagetool` packaging, and final `.AppImage` `--check-runtime` execution passed on `ubuntu-22.04`. | Physical camera communication over Linux libusb in production. |

## Reproduce local verification

```sh
python -W error::ResourceWarning -m unittest discover -s tests -v
python tests/smoke_gui.py
```

The smoke test uses fake camera/network providers and does not install an application. Native GUI tests require a display; Linux CI runs them under Xvfb.

For native bundles, use the packaging verifier to wait for the process and validate the report:

```sh
# Apple Silicon macOS
python packaging/build.py verify --executable 'dist/Sony A7 PMCA.app/Contents/MacOS/Sony A7 PMCA' --arch arm64

# Windows x64
python packaging/build.py verify --executable 'dist/Sony-A7-PMCA-1.0.0-windows-x64.exe' --arch x64

# Linux x86_64, testing the final AppImage rather than only its unpackaged binary
APPIMAGE_EXTRACT_AND_RUN=1 xvfb-run -a python packaging/build.py verify --executable dist/Sony-A7-PMCA-1.0.0-linux-x86_64.AppImage --arch x64
```

## CI and durable evidence

- [Native build/test workflow](https://github.com/OpenPMCA/Sony-A7-PMCA/actions/workflows/build.yml).
- [Actual catalog download evidence](appstore-download-validation.json).
- [Machine-readable local release validation](release-validation.json).
- [Release readiness and remaining gates](release-readiness.md).

The initial public migration triggers the native workflow. Status updates must reference that run's actual conclusion and logs; a pending, failed or skipped job must never be described as passed.

## Outstanding release gates

- Successful native Windows and Linux final-artifact checks, followed by suitable platform/camera tests before broad hardware claims.
- A tested macOS deployment floor and a Developer ID signing/notarization decision. The current locally built Python/Tk require macOS 27 or newer.
- Publication of the exact release asset referenced by the Homebrew cask. Its checksum must match that exact ZIP.
- A normal-MTP camera session with an existing suitable image for live shutter validation. No automatic shutter actuation is part of this verification.

Tests and public reports use synthetic or redacted identifiers. No unrelated APK was installed during catalog/download testing.
