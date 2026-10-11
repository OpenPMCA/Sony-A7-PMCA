# Current Sony Open PMCA build (Version 1.0.0)

There is one retained production-style app bundle:

`dist/Sony Open PMCA.app`

Older project app bundles (`v2`, `v2-safe`, separate preview folder), standalone executable copies, archives, and generated build intermediates were removed on 2026-10-10 at the user's request. The inspected legacy `/Applications/pmca-gui-v0.18-osx.app` was also removed; no camera drivers or unrelated applications were changed. Source code, tests, selected SVG/artwork, and the original RecipeLab APK are preserved.

## Version 1.0.0 Synchronization
Version `1.0.0` is established as the single source of truth across:
- Python module API: `pmca.__version__ == '1.0.0'`
- Command-line interface: `pmca-console.py --version` reports `1.0.0`
- Graphical interface: `pmca-gui.py` displays `1.0.0`
- PyInstaller bundle specification: `CFBundleShortVersionString = '1.0.0'`, `CFBundleVersion = '1.0.0'`
- Frozen executable runtime diagnostic report: `"version": "1.0.0"`

## Current capabilities & verified status

- **Streamlined Navigation (layout-spec.md)**:
  - Header (54px): Brand title, Sony Alpha mark, and real-time automatic connection status ("● Connected: {name} (MTP)" / "○ Camera Disconnected").
  - Sidebar (156px): Exactly 3 navigation items (`Info`, `Application`, `Logs`) with quiet active indicators.
- **Two-Panel Applications View (2:8 Proportion)**:
  - Upper Panel (~20%, ~118px): Compact Local APK staging bar (path, Browse APK, Reveal in Finder, Install APK to Camera, manifest inspection badge).
  - Lower Panel (~80%, ~548px): Full-width Application Store vertical list featuring 26 verified applications with live version synchronization and verified HTTPS download sources.
  - Asymmetric row grid budgeting: Column 0 (`weight=1`) hosts text block with Line 1 (Name + Version), Line 2 (Author + Package), Line 3 (Description with dynamic wraplength); Column 1 (`weight=0, minsize=220`) reserves full width for "Download APK" and "Source ↗" action buttons. No clipping in the tested minimum, default and larger native-window fixtures.
  - "Download APK" on any card runs secure atomic download and stages APK directly into upper panel.
  - All visible card download buttons properly disable when an operation is running.
  - Background metadata sync starts non-blocking on startup. Check Updates refreshes metadata without automatically downloading or installing APKs. Failed refreshes preserve the cached catalog and prior success timestamp.
- **Native macOS Camera Communication**:
  - `libusb-mtp` transport handler safely catches Darwin `LIBUSB_ERROR_ACCESS` (-3) during device reset, bypassing unnecessary kernel driver detachment on macOS.
  - Successfully connects over PTP/MTP to the physically connected camera and reads real properties:
    * Model: `ILCE-7`
    * Body firmware: `3.20` (user-reported); PTP Device Version: `3.0` (measured PTP read)
    * Lens: `Model 0x10a08011 (Firmware 1.04)`
    * Serial number: `12345***`
    * Product code: `0032826300`
    * Mode: `MTP`
- **TLS MarketServer Handshake Verification**:
  - Unwrapped `Rijndael.__init__` bypasses warning frame inspection, allowing camera to complete TLS 1.0–1.2 CBC handshake without SSL error 201.
  - Packaged executable diagnostic verified: `"tls_handshake_verified": true`, `"tls_cipher": "AES256-SHA"`, `"tls_version": "TLSv1.2"`.
- **Binary Manifest Compatibility**: In-memory UTF-8 (`flags 0x100`) and UTF-16 AXML string pool decoding in `pmca.apk`, verified with both official RecipeLab and real community APKs (e.g. OpenMemories-Tweak 0.11).
- **Passive USB Detection**: Type-safe XML plist parsing of macOS I/O Registry (`ioreg -a`) detects attached Sony camera (`ILCE-7`, vendor `0x054c`, product `0x08b4`) and identifies Interface Class 6/1/1 (`MTP / PTP`).
- **Smart Activity Logs**: Raw-grouped error copy preserving multi-line tracebacks regardless of display search/level filters, smart auto-scroll pausing when user reads earlier events, and state-delta logging.

## Verification metrics

- Full unit test suite: **162 tests passed**, 0 failures, 0 skipped (`PYTHONPATH=tests ./.venv/bin/python -m unittest discover tests`).
- Application Store: **26 verified applications** integrated with verified HTTPS download URLs, factual version badges, and hardware compatibility caveats (e.g. BetterManual A5100-only mapping). Download integrity verified in `docs/appstore-download-validation.json`.
- Store layout: Removed redundant store search bar while preserving dedicated live search in Activity Logs; styled headers as prominent 13pt bold native labels.
- Native macOS Trackpad Scrolling (`<TouchpadScroll>`): Unpacks signed 16-bit deltas per Tk 9.1 (`tk::PreciseScrollDeltas`), configuring pixel-accurate `yscrollincrement=1` scrolling across all child rows, labels, and buttons via `'StoreScrollable'` tag routing.
- Native Acceptance: 23/23 native acceptance tests passed; 8/8 TouchpadScroll dispatch tests passed; zero clipped text across minimum (`960x640`), default (`1160x760`), and large (`1400x900`) window sizes (`text-geometry.json: { "application": [], "info": [] }`).
- Factual Telemetry Separation: Body firmware (`3.20` user-reported) and protocol version (`PTP v3.0` actual read) are tracked and displayed independently; clean 8-digit body serial (`12345***`) separated from 32-character raw PTP descriptors.
- Shutter Actuation Provenance: Fully integrated with backend Sony MakerNote Tag 0x9050 decoder, displaying clean actuation counts, sample photo provenance, and flash rollover warnings without horizontal clipping.
- Verified Real Hardware App Transfer: Physical Sony ILCE-7 camera verified with end-to-end RecipeLab 1.6.2 installation (`Result(code=0, message='Successfully completed')`).
- Native window smoke test: `tests/smoke_gui.py` passes with dynamic platform driver assertions and zero automatic networking or USB calls on launch.
- Frozen Mach-O runtime check (`--check-runtime`): ARM64, Python 3.14.8, Tcl 9.1.0, bundled libusb, SPK roundtrip, certificate parsing, and TLS handshake loopback all pass.
- Ad-hoc deep/strict codesign verified (`codesign --verify --deep --strict`).
- Comprehensive Verification Gates: Detailed verification ledger and release readiness documented in `docs/release-readiness.md`.

No git tag, commit, push, public release, camera firmware alteration, or unrequested APK installation has been performed.
