# Sony A7 PMCA

[![Native builds](https://github.com/OpenPMCA/Sony-A7-PMCA/actions/workflows/build.yml/badge.svg?branch=main)](https://github.com/OpenPMCA/Sony-A7-PMCA/actions/workflows/build.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE.txt)

A native desktop app manager and diagnostics toolkit for Sony cameras that support **PlayMemories Camera Apps**.

Sony A7 PMCA focuses on a straightforward workflow: connect a camera, inspect its information, download or select an APK, and install it with explicit confirmation. It builds on [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE) and the OpenMemories community.

> **Status:** Version 1.0.0 is under active validation. macOS Apple Silicon has local build/runtime evidence and an ILCE-7 RecipeLab installation was confirmed. Windows EXE and Linux AppImage have native CI build paths; their actual results are tracked separately. A prepared package or passing source test is not a production compatibility guarantee.

## What it does

- **Info:** automatic connection tracking, reconnect, camera identity, transport capabilities and available lens information. Body firmware is kept separate from the standard Picture Transfer Protocol version.
- **Application:** compact local APK staging above a scrollable Store. Downloaded APKs are checked for package identity, Android minimum API and a parsable signing certificate before installation.
- **Logs:** search and severity filtering, complete error copying, export and auto-follow that pauses when reading earlier output.
- **Community catalog:** curated download sources with version information and model-specific caveats. Metadata refresh never installs an app automatically.
- **Shutter metadata:** bounded read-only parsing of Sony MakerNote counters from an existing camera image. Results identify the examined image and limitations, including flash rollover. This is an image-time count, not a guaranteed live lifetime counter.

The existing command-line toolkit remains available for advanced workflows. The desktop app deliberately keeps only **Info**, **Application** and **Logs**.

## Compatibility and installation

Use a Sony camera with PlayMemories Camera Apps support, a USB data cable and **MTP** selected in the camera menu. Not every Sony Alpha body supports camera apps. Consult the [OpenMemories device list](https://openmemories.readthedocs.io/devices.html) and each application's own compatibility requirements.

| Platform | Distribution target | Current evidence |
|---|---|---|
| Apple Silicon macOS | Native app bundle and ZIP; Homebrew cask | Local ARM64 runtime, encrypted TLS and bundle integrity verified. The current local dependencies require macOS 27 or newer. |
| Windows x64 | Standalone `.exe` | Native Windows build and runtime checks are defined in CI. See the current workflow result before relying on a build. |
| Linux x86_64 | `.AppImage` | Native Linux build and final AppImage runtime checks are defined in CI. See the current workflow result before relying on a build. |

Build artifacts are produced by [GitHub Actions](https://github.com/OpenPMCA/Sony-A7-PMCA/actions). Stable downloads will be listed under [Releases](https://github.com/OpenPMCA/Sony-A7-PMCA/releases) when published. A release URL in the cask does **not** mean the binary has already been published.

Homebrew installation is prepared for after a corresponding release is available:

```sh
brew tap OpenPMCA/Sony-A7-PMCA https://github.com/OpenPMCA/Sony-A7-PMCA
brew install --cask sony-a7-pmca
```

The current macOS build is ad-hoc signed, not Apple Developer ID signed or notarized. See [distribution and release gates](docs/distribution.md) for the exact limitations.

## Build from source

```sh
git clone --recurse-submodules https://github.com/OpenPMCA/Sony-A7-PMCA.git
cd Sony-A7-PMCA
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python pmca-gui.py
```

On Windows, activate the environment with `.venv\Scripts\Activate.ps1`. Source execution requires a Tk-capable Python interpreter and the platform's camera transport dependencies. macOS and Linux use libusb. Windows uses native Windows Portable Devices with a libusb fallback.

Native packaging must run on the target operating system:

```sh
python packaging/build.py build
python packaging/build.py package
```

See the [macOS guide](docs/macOS.md), [backend API](docs/backend-api.md) and [distribution guide](docs/distribution.md) for setup, diagnostics and native build details.

## Testing status

Testing results distinguish software contracts from native runtime and physical-camera evidence. See [Testing status](docs/testing-status.md) for commands, dated outcomes, open gaps and the latest CI links.

The catalog download audit checks manifest package/API/certificate data. It does **not** establish that every catalog app runs on every camera. RecipeLab is the application whose installation was confirmed on the ILCE-7. Live shutter validation remains pending a suitable connected-camera image.

Run local checks without making a camera installation:

```sh
python -W error::ResourceWarning -m unittest discover -s tests -v
python tests/smoke_gui.py
```

The frozen app also provides `--check-runtime <report.json>` for bundled-library, certificate, encryption and local TLS diagnostics. CI validates the actual final executable or AppImage rather than treating build configuration as a successful runtime test.

## Safety, privacy and attribution

- Keep the camera powered and connected during a transfer. Do not interrupt an active installation.
- Install only applications you trust. Package/API/certificate checks are not a security audit or a universal compatibility guarantee.
- The utility does not require disabling System Integrity Protection, killing camera services or changing unrelated computer security settings.
- Local logs and diagnostics can contain camera identifiers. Review and redact them before sharing an issue or report.
- The included camera-installation certificate is the upstream public test fixture used by the local market server, not a user account credential or a production web-server secret.

This is an independent community project, not an official Sony product. Camera modification carries risk. Read the [original app-installation notes](docs/AppInstallation.md) before advanced use.

The original **MIT license and copyright attribution to ma1co are retained** in [LICENSE.txt](LICENSE.txt). Community camera applications remain separate projects under their maintainers' licenses; the Store references their download sources rather than bundling their APKs.
