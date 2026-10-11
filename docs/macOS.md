# Sony Open PMCA on macOS

RecipeLab runs on the camera's Android platform, not on macOS. PMCA runs on the Mac and transfers the APK through Sony's app-install protocol. Copying an APK onto a memory card does not install it.

## Current status: GUI/download preview

The current bundle is **not an installation-ready release**. It provides the redesigned interface and explicit RecipeLab download/inspection while camera access is being repaired.

- Camera, Applications, and Activity tabs, using native Aqua controls and the macOS system font.
- The user-selected SVG mark as PNG/ICNS.
- Explicit stable RecipeLab download, HTTPS-only redirects, package/SDK validation, and preservation of existing files on failure.
- Local APK selection and package/version/SDK preview.
- Timestamped/error-tagged logs with copy/clear controls.
- **Camera info and Install are disabled** in the Mac preview, including after a download completes. No camera session or network request starts on launch.

The camera is currently charging; physical tests are paused. See [validation results](gui-validation.md) and [USB access status](usb-access-status.md).

## Open the delivered preview

The preview from this session is at `dist/Sony Open PMCA.app`.

1. Quit any still-running older Sony Open PMCA instance. Older on-disk app bundles have been removed, but a process already running can still display its old window.
2. Open the preview app in Finder. You do not need to connect a camera for GUI/download testing.
3. In **Applications**, choose a local `RecipeLab.apk` or click **Download RecipeLab…** and choose where to save it.
4. Read package/version/SDK details and download status. Downloading does not install anything.
5. In **Activity**, review timestamped output. Copy the log if an error needs investigation.

This is a local, ad-hoc signed ARM64 build, not a published/notarized release. Do not disable Gatekeeper, SIP, or other security settings to open it. If macOS refuses to open it, report the exact message.

## Source setup and build

Use native ARM64 Python and a project virtual environment. Do not use `sudo pip`.

If `.venv` does not exist:

```bash
python3 -m venv .venv
```

Install libusb if it is absent:

```bash
brew install libusb
```

Install dependencies:

```bash
.venv/bin/python -m pip install -r requirements.txt
```

Tkinter needs a Homebrew package matching the Python minor version. For Python 3.14:

```bash
brew install python-tk@3.14
```

Generate icons from the selected SVG geometry if artwork changes (requires Command Line Tools and Python):

```bash
sh assets/make-icons.sh
```

Build the preview in a separate directory:

```bash
.venv/bin/python -m PyInstaller --distpath dist sony-open-pmca.spec
```

Python/Tcl/Tk, libusb, the installation certificate, artwork, and upstream license are bundled. The built app does not require a separate Python installation.

## Offline verification

Full suite, with no network or camera operations:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Actual frozen executable, without opening a window or enumerating USB:

```bash
"dist/Sony Open PMCA.app/Contents/MacOS/Sony Open PMCA" --check-runtime "$PWD/dist/runtime-check.json"
```

The JSON should report `frozen: true`, `architecture: arm64`, Tcl's version, successful libusb loading, SPK round-trip, and certificate/key parsing. Its libusb path should point inside this bundle. This is not proof of live camera access.

A separate real-window smoke test exercises Tk controls/queue/worker/logs with camera and network operations replaced. It temporarily enables camera controls **only in the test process**, with commands mocked:

```bash
.venv/bin/python tests/smoke_gui.py
```

The automation environment cannot run this native window test because macOS window-service/cache access is sandbox-restricted. It must be run normally by the user; do not count unit tests as a visual pass.

## Why USB still needs work

Earlier user tests found the ILCE-7 in both Mass Storage and MTP, but `detach_kernel_driver` failed with errno 13. In MTP the system `ptpcamerad` owned the interface.

The SDK/libusb document `com.apple.vm.device-access` plus `IOServiceAuthorize()` for non-root capture. The ad-hoc entitlement candidate passed static signature verification but its runtime diagnostic exited 137 without a report. The same bundle without that entitlement passed. The default preview therefore does not ship the failed permission experiment.

Do not run the installer with sudo, disable SIP, kill system camera services, or attempt to seize a mounted camera disk. The next transport should use Apple's ImageCaptureCore PTP API and receive a separate design/prototype/hardware validation.

## Later camera-test boundary

When native transport is implemented and the camera is charged:

- Use explicit MTP, not Auto, Mass Storage, or PC Remote.
- Finish photo transfers, close other camera applications, and connect only one camera with a data-capable cable.
- Verify model/firmware information first. No device, timeout, or traceback is not success.
- Confirm RecipeLab's native features support the particular model and firmware. A compatible Android manifest alone does not prove this.
- Install only after explicit confirmation, keep power/USB connected, and verify both package transfer and app behavior on camera.

No firmware changes, camera installation, commit, push, or release publication have been performed by this session. A successful real installation and the user's later explicit permission remain required before publication.
