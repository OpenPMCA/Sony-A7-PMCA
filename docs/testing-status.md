# Testing status

Project: Sony Open PMCA. Version: 1.1.0. Verification date: 2026-10-11.

This document separates automated tests, native runtime checks and actual camera operations. GitHub workflow configuration is not evidence that its jobs have finished successfully.

## Verification matrix

| Area | Recorded result | What this proves | What it does not prove |
|---|---|---|---|
| Source unit tests | v1.1.0: 246 local tests passed with no failures/errors/skips and no resource/Tk warnings, plus successful source suites on all three native CI runners. [Release evidence](release-validation-1.1.0.json). | Covered parsing, download, cache, transport and GUI contracts. | Uncovered hardware behavior or every model/application combination. |
| Native Tk GUI | Current correction: real Tk smoke passed, including simulated unsupported-body and disconnect transitions. Earlier audit also recorded 23 acceptance and 8 packed native-scroll cases. | Navigation, list reachability, mouse/trackpad event dispatch, busy controls and Logs behavior under controlled providers. | Windows/Linux native appearance before those runners execute. |
| Store APK downloads | 26 actual HTTPS downloads passed package/API/certificate parsing. | The audited sources delivered inspectable APKs with expected identity and compatible declared minimum API. | Cryptographic trust in every publisher or runtime compatibility on every camera. |
| Apple Silicon frozen runtime | Published v1.1.0 CI ZIP passed frozen libusb/Tcl/certificate/SPK/encrypted TLS checks, 47-module Python-version-matched source parity, deep/strict ad-hoc signature, ZIP integrity and runtime/signature after extraction to a fresh path containing spaces. | Required local dependencies and encrypted loopback exchange worked on the test host. | Apple notarization or older-macOS compatibility. |
| Camera installation | RecipeLab installation on Sony ILCE-7 completed with camera result code 0 and user confirmation. | That selected transfer succeeded on the tested body. | Other app installs or Windows/Linux camera operations. |
| Shutter metadata | A/B layouts, flash/rollover, model mismatch, capture-date provenance and bounded MTP contracts passed independently built fixtures plus local ExifTool 13.45 comparisons. | Covered decoder behavior and honest unavailable/ambiguous states. | A current physical-camera count; the camera was disconnected for final verification. |
| Windows EXE | **Passed in CI** ([Run 38135433837](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/runs/38135433837)). | Native 64-bit Windows build, PyInstaller one-file packaging, and `--check-runtime` frozen diagnostic executed and passed on `windows-2022`. | Physical camera communication over Windows WPD driver in production. |
| Linux AppImage | **Passed in CI** ([Run 38135433837](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/runs/38135433837)). | Native Linux build, Xvfb GUI smoke test, `appimagetool` packaging, and final `.AppImage` `--check-runtime` execution passed on `ubuntu-22.04`. | Physical camera communication over Linux libusb in production. |

## Reproduce local verification

```sh
python -W error::ResourceWarning -m unittest discover -s tests -v
python tests/smoke_gui.py
```

The smoke test uses fake camera/network providers and does not install an application. Native GUI tests require a display; Linux CI runs them under Xvfb.

For native bundles, use the packaging verifier to wait for the process and validate the report:

```sh
# Apple Silicon macOS
python packaging/build.py verify --executable 'dist/Sony Open PMCA.app/Contents/MacOS/Sony Open PMCA' --arch arm64

# Windows x64
python packaging/build.py verify --executable 'dist/Sony-Open-PMCA-1.0.0-windows-x64.exe' --arch x64

# Linux x86_64, testing the final AppImage rather than only its unpackaged binary
APPIMAGE_EXTRACT_AND_RUN=1 xvfb-run -a python packaging/build.py verify --executable dist/Sony-Open-PMCA-1.0.0-linux-x86_64.AppImage --arch x64
```

## CI and durable evidence

- [Native build/test workflow](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/workflows/build.yml).
- [Actual catalog download evidence](appstore-download-validation.json).
- [Machine-readable local release validation](release-validation.json).
- [Historical local camera-support candidate validation](camera-support-validation.json).
- [Published v1.1.0 validation](release-validation-1.1.0.json).
- [Release readiness and remaining gates](release-readiness.md).

Native CI Run 38135433837 passed all three platform jobs at release source commit `bbbaea537e2a0e792cabcb90617cc9855bb2a8ed`. Its artifacts are published in [v1.1.0](https://github.com/OpenPMCA/Sony-Open-PMCA/releases/tag/v1.1.0). The earlier run 38132375470 was cancelled after a macOS test opened an unmocked native confirmation dialog; it is not counted as all-platform success. Local verification uses cached real APKs; Each native CI runner executed 246 tests: 239 passed and 7 optional real-APK/ExifTool reference tests were skipped because those external fixtures/tools were absent. All 246 ran locally. This is not hardware testing.

## Historical isolated v1.0.0 macOS candidate

The camera-support correction was built separately at `dist/camera-support-correction/Sony Open PMCA.app`. Its ZIP is `dist/camera-support-correction/Sony-Open-PMCA-1.0.0-macos-arm64.zip` and SHA-256 is `3af99aae7b73e0ca8220de8e3a05dab42eba5454fc1603defc354a92516d66d1`. It requires macOS 27.0 and uses an ad-hoc signature, not Developer ID/notarization.

A matching candidate Cask is stored beside that ZIP. The previous root `dist` artifacts and tracked `Casks/sony-open-pmca.rb` remain unchanged; this candidate is not published. No physical camera operations or new APK downloads were performed.


## Outstanding release gates

- Successful native Windows and Linux final-artifact checks, followed by suitable platform/camera tests before broad hardware claims.
- A tested macOS deployment floor and a Developer ID signing/notarization decision. The historical local Python/Tk build requires macOS 27; the published v1.1.0 CI ZIP requires macOS 14.0 or newer and remains ad-hoc signed.
- Published v1.1.0 assets and the Homebrew Cask checksum are verified against the exact CI ZIP; future releases must repeat this check.
- A normal-MTP camera session with an existing suitable image for live shutter validation. No automatic shutter actuation is part of this verification.

Tests and public reports use synthetic or redacted identifiers. No unrelated APK was installed during catalog/download testing.
