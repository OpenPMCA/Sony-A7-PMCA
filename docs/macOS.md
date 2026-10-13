# Sony Open PMCA on macOS

RecipeLab and other PMCA apps run on the camera, not on macOS. Sony Open PMCA transfers a deliberately selected APK through the Sony installer protocol; copying it onto the memory card does not install it.

## Published release and development

[v1.1.0](https://github.com/OpenPMCA/Sony-Open-PMCA/releases/tag/v1.1.0) is a published Apple Silicon release requiring macOS 14 Sonoma or newer. Its CI archive, encrypted runtime, ad-hoc signature and source parity were verified; [the release evidence](release-validation-1.1.0.json) records exactly what was tested. It is not Developer ID signed or notarized.

[v1.2.0](https://github.com/OpenPMCA/Sony-Open-PMCA/releases/tag/v1.2.0) is the current published reliability/UI release, built and runtime-tested on native `macos-14`. Its exact CI ZIP requires macOS 14.0, matches the public Cask/checksum and passed relocated runtime plus 47-module source parity; [new evidence](release-validation-1.2.0.json) is separate from v1.1.0 history. Do not use the older macOS-27-only local archive to infer this release's compatibility.

Camera/Applications/Activity are native Tk views. Read-only Info and install controls depend on actual connection, model/protocol eligibility and operation state. Installation on ILCE-7 with RecipeLab is the only physical installation result recorded here; other pairings and live image counters need their own verification.

## Why MTP is the desktop default

MTP exposes protocol operations useful for camera diagnostics, bounded image metadata and the PlayMemories installer proxy. Mass Storage normally exposes a mounted storage volume, not the complete camera OS or internal app-install database.

The legacy backend also has Sony vendor commands over SCSI opcode `0x7a`; that is different from ordinary file access. They require a compatible driver that can already communicate safely. The current macOS desktop deliberately uses `libusb-mtp` and does not capture mounted MSC volumes. Standard SCSI Inquiry names such as `DSC` are not the real body model. Even an eligible legacy MSC installation path must transition into the MTP installer proxy for app transfer.

For the desktop workflow, choose **USB Connection → MTP** on the camera, finish external photo transfers, close other camera clients and connect one physical camera. A mode mismatch is not evidence that SIP needs disabling or a system camera service needs killing. No automatic unmount/eject, firmware/service-mode changes, photo capture or unrelated APK installation is required.

## Open and use the release

1. Download the exact release ZIP and compare its SHA-256 with the published checksum; extract `Sony Open PMCA.app`.
2. Confirm the GUI version matches the release you opened. An already-running older process does not update when a new app is copied to disk.
3. In Camera, verify the reported mode/model and use the explicit read-only Info action. PTP DeviceVersion is not automatically body firmware.
4. In Applications, inspect the selected APK's package/version/declared minimum API and app/model caveats. Download is a separate action; install requires confirmation.
5. During installation keep power and USB connected. Completion needs the camera's successful result, not a progress percentage or download success.
6. Activity provides filtered logs and export/copy; v1.2.0's approved retention is the latest 5,000 lines with explicit omission notice, not automatic disk logging.

Ad-hoc signing does not remove Gatekeeper/notarization requirements. If macOS refuses to open the app, report the exact message; do not disable Gatekeeper or SIP or use undocumented permission workarounds.

## Source setup and native build

Use ARM64 Python in an isolated environment; do not use `sudo pip`:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
brew install libusb
```

Tk support must match the Python minor version (for example `python-tk@3.14` for Homebrew Python 3.14). Local framework deployment targets may be newer than CI's; inspect the built dependencies rather than inferring compatibility from the bootloader alone.

```sh
.venv/bin/python -m PyInstaller sony-open-pmca.spec
.venv/bin/python packaging/build.py verify --executable 'dist/Sony Open PMCA.app/Contents/MacOS/Sony Open PMCA' --arch arm64
.venv/bin/python packaging/build.py package
```

The packager verifies architecture/signature, preserves bundle symlinks and derives the Cask's minimum OS and checksum from that exact ZIP. Final release downloads and Cask metadata must match those bytes.

## Verification boundaries

```sh
.venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -v
.venv/bin/python tests/smoke_gui.py
```

Unit/benchmark/smoke providers must be controlled so no test opens a real permission dialog, contacts GitHub or captures a real camera unexpectedly. The native runtime command checks bundled libusb/Tcl, certificate parsing, SPK and encrypted loopback TLS; it does not enumerate USB or prove hardware compatibility.

The desktop backend lock serializes operations within one process only. Before a live test, coordinate exclusive access with other app/framework sessions, confirm the intended body and use a read-only existing-image path. No automatic photo, mode switch, firmware/service command or extra app install is implied by an offline test or a release request.
