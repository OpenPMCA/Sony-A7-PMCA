# Sony A7 PMCA release readiness

Verification date: 2026-10-11. Product version: 1.0.0. This report distinguishes actual local execution from native build configuration. Public distribution has not been authorized or performed.

## Verified source and native GUI behavior

- The complete source suite passes with ResourceWarning treated as an error. The latest pre-build run includes 162 tests.
- Real Tk controls were driven with fake camera/network providers. The independent acceptance run passed all 23 cases, including default, minimum and larger landscape windows, final Store row reachability, busy controls, Info provenance and Logs error copying/auto-follow.
- The native macOS failure was caused by Tk 9 delivering TouchpadScroll instead of MouseWheel. Actual Tk event dispatch now handles the native packed signed delta over canvas, row frames, labels, action buttons and scrollbar. The independent wheel run passed all eight cases, including navigation, row rebuild and horizontal-only motion. A fabricated Cocoa NSEvent with no application window number was ignored and is not counted as successful native-event injection.
- Store search is removed. Logs search is retained. Both Application panel headers have clear hierarchy. Text requested/allocated geometry shows no clipped labels in the tested minimum-size Application and Info fixtures.
- All 26 Store APKs downloaded successfully through the shared HTTPS/atomic downloader. Actual manifest package, Android minimum API and certificate parsing were checked. Evidence is saved in `docs/appstore-download-validation.json` without camera identifiers or host download paths. These checks do not establish that every application works on the ILCE-7.
- RecipeLab installation was confirmed by the user and the backend's camera completion result. It was not repeated for this audit. No other application was installed.
- Info separates standard Picture Transfer Protocol DeviceVersion from body firmware. Firmware 3.20 was reported by the user, not established by the final read-only probe.
- The image-based shutter decoder and bounded MTP reader are implemented and fixture/reference-tested. Flash rollover never produces an exact lifetime value. The result identifies the examined image, capture date when available and limited metadata coverage. No live count was obtained during final verification because the camera was disconnected. No photo was automatically captured.

## Distribution gates

- The final ARM64 macOS bundle was clean-built from the verified source snapshot. The complete code trees of ten GUI/backend modules match source. The frozen runtime passes bundled libusb/Tcl/certificate/encryption checks and an AES256-SHA TLS 1.2 loopback handshake. Deep/strict ad-hoc signature verification passes. The final ZIP passes structural checks and its checksum matches the actual evaluated Homebrew cask.
- The local Python/Tcl/Tk frameworks require macOS 27.0. The cask must enforce that minimum for this exact archive. Older Apple Silicon compatibility requires a separate native build with compatible dependencies and testing.
- Windows EXE and Linux AppImage build specifications, bundled libusb lookup and native CI jobs are prepared. Neither final artifact was built or executed on this macOS host. Successful native runner execution is required before either platform is described as production-ready.
- The Linux job verifies the actual final AppImage, not only the raw PyInstaller directory. The Windows diagnostic process is awaited before checking its report.
- The local macOS bundle is ad-hoc signed. Developer ID signing and Apple notarization are not completed.
- The Homebrew cask references a future release URL. It is not presently a published downloadable installation. The cask checksum must match the exact published ZIP, not a different CI or local artifact.
- No commit, push, tag, GitHub release, tap publication or deployment was performed. The working tree retains prior uncommitted user changes.

Local validation references: `/tmp/pmca-coordinator-final-source-tests.log`, `/tmp/pmca-native-acceptance-zCWJmR/native-report.json`, `/tmp/pmca-native-acceptance-zCWJmR/touchpad-dispatch.json`, and `/tmp/pmca-native-acceptance-zCWJmR/text-geometry.json`. Temporary files can expire. The durable APK evidence and this report retain the relevant outcomes and limitations.

Final local archive: `dist/Sony-A7-PMCA-1.0.0-macos-arm64.zip`. SHA-256: `bb3a09234b97c480d39ed0a16b68646c1378c355e306cf71d18a340208074cb5`. Homebrew evaluation confirms ARM64 and macOS 27 or newer for this exact build. This does not publish the release URL.

The actual final ZIP was also extracted into a fresh directory whose path contains spaces. The extracted application passed deep/strict signature verification and the complete frozen runtime diagnostic, including encrypted TLS, from that relocated path. The final post-package strict suite passed all 162 tests in `/tmp/pmca-coordinator-final-delivery-tests.log`.
