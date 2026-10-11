# GUI preview validation — Version 1.0.0 (2026-10-10)

## Architecture & Implementation Overview

- **ARM64 macOS app bundle** (`dist/Sony Open PMCA.app`) bundling Python 3.14.8, Tcl 9.1.0, libusb 1.0.30, and the installation certificate.
- **Single Source of Truth Versioning**: Synchronized version `1.0.0` across `pmca.__version__`, `pmca-console.py`, `pmca-gui.py`, `sony-open-pmca.spec` (`CFBundleShortVersionString`/`CFBundleVersion`), and runtime diagnostics.
- **Streamlined Navigation (layout-spec.md)**:
  - Header (54px): Brand title, Sony Alpha mark, and real-time automatic connection status ("● Connected: {name} (MTP)" / "○ Camera Disconnected").
  - Sidebar (156px): Exactly 3 navigation items (`Info`, `Application`, `Logs`) with quiet active indicators.
- **Two-Panel Applications Layout (2:8 Proportion)**:
  - Upper Panel (~20%, ~118px): Compact Local APK staging bar (path, Browse APK, Reveal in Finder, Install APK to Camera, manifest inspection badge).
  - Lower Panel (~80%, ~548px): Full-width vertical list of 26 verified applications with asymmetric grid budgeting:
    * Column 0 (`weight=1`): Line 1 (Name + Version), Line 2 (Author + Package), Line 3 (Description with dynamic wraplength).
    * Column 1 (`weight=0, minsize=220`): Action buttons ("Download APK" and "Source ↗").
    * Zero text or button clipping across all tested resolutions.
  - "Download APK" on any card runs secure atomic download and stages APK directly into upper panel.
  - Card download buttons disable during transfer/install operations.
  - Background metadata sync starts non-blocking on startup. Check Updates refreshes metadata without automatically downloading or installing APKs. Failed refreshes preserve the cached catalog and prior success timestamp.
- **Native macOS Camera Communication**:
  - `libusb-mtp` transport handler safely catches Darwin `LIBUSB_ERROR_ACCESS` (-3) during device reset, bypassing unnecessary kernel driver detachment on Darwin.
  - Successfully connects over PTP/MTP to the physically connected camera and reads real properties:
    * Model: `ILCE-7`
    * Body firmware: `3.20` (user-reported); PTP Device Version: `3.0` (measured PTP read)
    * Lens: `Model 0x10a08011 (Firmware 1.04)`
    * Serial number: `12345***`
    * Product code: `0032826300`
    * Mode: `MTP`
- **TLS MarketServer Handshake Verification**:
  - Unwrapped `Rijndael.__init__` bypasses warning frame inspection, resolving the frozen PyInstaller `TypeError: 'NoneType' object is not iterable` crash during camera app installation (Communication error 201: SSL error).
  - Packaged executable diagnostic verified: `"tls_handshake_verified": true`, `"tls_cipher": "AES256-SHA"`, `"tls_version": "TLSv1.2"`.
- **Binary Manifest Compatibility**: In-memory `StringBlock` decoder in `pmca.apk` supporting both UTF-8 string pools (Android AXML `flags 0x100`) and legacy UTF-16 pools without altering installed `site-packages`.
- **Passive USB Detection**: Type-safe XML plist parsing of macOS I/O Registry (`ioreg -a`) detects attached Sony cameras (`idVendor == 0x054c`) and identifies Interface Class 6/1/1 (`MTP / PTP`) without driver detachment or handle acquisition.
- **Smart Activity Logs**: Raw-grouped error copy preserving multi-line tracebacks regardless of display search/level filters, smart auto-scroll pausing when user reads earlier events, and state-delta logging.

---

## Verification Results

### 1. Automated Test Suites
- **Unit Tests**: Full test suite expanded to **162 tests passed**, 0 failures, 0 skipped (`PYTHONPATH=tests ./.venv/bin/python -m unittest discover tests`).
- **Real-window Smoke Test**: `tests/smoke_gui.py` passes using native Tk controls, task queue, log redirection, empty APK validation guard, and verifies zero automatic network or USB calls on startup.

### 2. Live Camera Communication Verification
- Verified real-world read-only PTP communication with attached Sony ILCE-7:
  - `infoCommand('libusb-mtp')` successfully executes PTP commands (`GetDeviceInfo`, `OpenSession`, `SonyDiExtCmd_write`, `SonyDiExtCmd_read`).
  - Read factual values: Model `ILCE-7`, Body Firmware `3.20` (user-reported), PTP Version `3.0` (measured), Lens `Model 0x10a08011 (Firmware 1.04)`, Serial `12345***`, Product code `0032826300`.
  - Zero host elevation needed: standard user privileges, no sudo, no SIP changes, `ptpcamerad` remains active.

### 3. Binary Manifest & Network Boundary Verification
- Real community APK binary manifest verification: parsed `OpenMemories-Tweak.apk` 0.11 (package `com.github.ma1co.openmemories.tweak`, version `0.11`, API `10`, cert length 707).
- Real UTF-16 manifest fixture parsed (`com.voxivoid.recipelab`, API `9`).
- Actual HTTPS downloads and manifest/API/certificate parsing passed for all 26 catalog entries. See `docs/appstore-download-validation.json`. This audit did not install additional applications.
- Atomic download rejection verified: wrong package mismatch, out-of-range API (>10), invalid ZIP, and insecure URLs all cleanly reject without touching or leaving partial files.

### 4. Native Layout & Geometry Verification
- Verified via direct Cocoa `contentView` bitmap rasterization (`NSBitmapImageRep`):
  - **Minimum Size (`960x640`)**: Zero unmapped widgets; zero clipped text across all containers (`text-geometry.json: { "application": [], "info": [] }`).
  - **Default Size (`1160x760`)**: Zero unmapped widgets; spacious vertical list layout with 26 verified applications.
  - **Large Size (`1400x900`)**: Responsive horizontal and vertical scaling.
- Dynamic `<Configure>` wraplength calculation on container widgets completely eliminates description and note clipping across all window sizes.
- Native macOS trackpad scrolling verified via `<TouchpadScroll>` signed 16-bit delta unpacking per Tk 9.1 spec (`tk::PreciseScrollDeltas`), pixel-accurate `yscrollincrement=1`, and `'StoreScrollable'` bindtag routing across all child widgets.

### 5. Frozen App Bundle Validation
- Executable runtime check (`"dist/Sony Open PMCA.app/Contents/MacOS/Sony Open PMCA" --check-runtime`):
  - `version`: "1.0.0"
  - `frozen`: true
  - `architecture`: arm64
  - `python`: 3.14.8
  - `tcl_version`: 9.1.0
  - `libusb_loads`: true (loaded from inside bundle Frameworks)
  - `spk_roundtrip`: true
  - `certificate_key_parses`: true
  - `tls_handshake_verified`: true (tested loopback TLS 1.2 CBC with AES256-SHA)
  - `tls_cipher`: "AES256-SHA"
  - `tls_version`: "TLSv1.2"
- Code signing verified: `codesign --verify --deep --strict "dist/Sony Open PMCA.app"`.

No git commit, push, release publication, live camera write, or firmware alteration has been performed.
