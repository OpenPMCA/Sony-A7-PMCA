# Sony Open PMCA

[![Native CI](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/workflows/build.yml/badge.svg?branch=main)](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/workflows/build.yml)
[![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)](https://github.com/OpenPMCA/Sony-Open-PMCA/releases/tag/v1.1.0)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE.txt)
[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)

Native desktop application to install custom apps and read camera diagnostics on Sony digital cameras supporting **PlayMemories Camera Apps (PMCA)**.

Built on the open-source reverse-engineering research of [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE) by ma1co and the OpenMemories community.

---

## Table of Contents

- [Supported Cameras](#supported-cameras)
- [Installation & Downloads](#installation--downloads)
- [Quick Start](#quick-start)
- [Features](#features)
- [Build from Source](#build-from-source)
- [Safety & Disclaimer](#safety--disclaimer)
- [Attribution & License](#attribution--license)

---

## Supported Cameras

Only Sony cameras with the built-in Android-based PlayMemories Camera Apps subsystem can run PMCA apps:

| Series | Supported Camera Models | Model Codes | Shutter Counter |
| :--- | :--- | :--- | :---: |
| **Alpha Full-Frame** | α7, α7R, α7S, α7 II, α7R II, α7S II | `ILCE-7`, `7R`, `7S`, `7M2`, `7RM2`, `7SM2` | Tag 9050a / 9050b |
| **Alpha APS-C** | α5000, α5100, α6000, α6300, α6500, QX1 | `ILCE-5000`, `5100`, `6000`, `6300`, `6500`, `QX1` | Tag 9050a / 9050b |
| **NEX Series** | NEX-5R, NEX-5T, NEX-6 | `NEX-5R`, `NEX-5T`, `NEX-6` | — |
| **Cyber-shot Series** | RX100 III/IV/V, RX10 II/III, RX1R II, HX60, HX90, HX400, WX500 | `DSC-RX100M3-M5`, `RX10M2-M3`, `RX1RM2`, `HX60`, `HX90`, `HX400`, `WX500` | — |

> **Incompatible cameras:** Models released from late 2017 onward (such as α7 III, α7 IV, α7C, α9, α1, α6400, α6700, ZV-1, ZV-E10, FX series) and older pre-PMCA cameras do not have the PMCA subsystem. Installation is automatically disabled for these cameras. Shutter counter decoding reads metadata from an existing photo on storage. See [camera support details](docs/camera-support.md).

---

## Installation & Downloads

Official pre-built releases are available on [GitHub Releases](https://github.com/OpenPMCA/Sony-Open-PMCA/releases/tag/v1.1.0).

### macOS
Built for Apple Silicon (`arm64`), requiring macOS 14 Sonoma or newer.

* **Homebrew Cask** (Recommended):
  ```bash
  brew tap OpenPMCA/Sony-Open-PMCA https://github.com/OpenPMCA/Sony-Open-PMCA
  brew install --cask sony-open-pmca
  ```
* **Manual Download**:
  Download [`Sony-Open-PMCA-1.1.0-macos-arm64.zip`](https://github.com/OpenPMCA/Sony-Open-PMCA/releases/download/v1.1.0/Sony-Open-PMCA-1.1.0-macos-arm64.zip), extract it, and move `Sony Open PMCA.app` to `/Applications`. (On first launch, right-click and select **Open** to pass Gatekeeper).

### Windows
Standalone executable for 64-bit Windows (Windows 10 / 11).

* Download [`Sony-Open-PMCA-1.1.0-windows-x64.exe`](https://github.com/OpenPMCA/Sony-Open-PMCA/releases/download/v1.1.0/Sony-Open-PMCA-1.1.0-windows-x64.exe) and run it directly. No drivers or installation needed.

### Linux
Portable AppImage for 64-bit Linux (Ubuntu, Debian, Fedora, Arch).

* Download [`Sony-Open-PMCA-1.1.0-linux-x86_64.AppImage`](https://github.com/OpenPMCA/Sony-Open-PMCA/releases/download/v1.1.0/Sony-Open-PMCA-1.1.0-linux-x86_64.AppImage), make it executable, and run:
  ```bash
  chmod +x Sony-Open-PMCA-1.1.0-linux-x86_64.AppImage
  ./Sony-Open-PMCA-1.1.0-linux-x86_64.AppImage
  ```

---

## Quick Start

```
1. Set Camera USB Mode    → Menu → Setup (wrench) → USB Connection → MTP
2. Connect Camera to PC   → Use a USB data cable (camera powered on)
3. Launch Sony Open PMCA  → App automatically detects and connects
4. Choose an Action       → Info (diagnostics) | Application (install apps) | Activity (logs)
```

---

## Features

* **Automatic Detection**: Real-time camera connection and disconnection monitoring over MTP.
* **Camera Diagnostics**: Reads model name, vendor, firmware version, serial number, lens info, and PTP capabilities.
* **Shutter Count Reader**: Extracts actuation count from existing photos on storage using MakerNote Tag 9050a/b.
* **Safe App Installation**: Model-eligibility gating prevents switching unsupported cameras into installer mode. Preflights APK package ID, Android API baseline (1–10), and signing certificates.
* **Built-in App Store**: Direct downloads for 26 curated open-source camera apps (OpenMemories Tweak, BetterManual, RecipeLab, etc.).
* **Activity Logs**: Searchable real-time logs with level filtering (All / Errors / Info) and one-click clipboard copying.
* **Responsive UI**: Clean 1160x760 desktop layout with smooth mouse wheel and native trackpad scrolling.
* **Standalone Binaries**: Self-contained executables for macOS, Windows, and Linux — no Python environment required.

---

## Build from Source

```bash
git clone --recurse-submodules https://github.com/OpenPMCA/Sony-Open-PMCA.git
cd Sony-Open-PMCA

python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

python pmca-gui.py              # Launch GUI
python -W error::ResourceWarning -m unittest discover -s tests -v
```

---

## Safety & Disclaimer

* **Keep Connected:** Do not disconnect the cable or power off the camera while an app is installing.
* **Non-Destructive:** Does not modify firmware or service-mode settings. All installations require user confirmation.
* **No Root Needed:** Operates strictly on the connected USB device without requiring `sudo` or system modifications.
* **Disclaimer:** Independent open-source project. Sony, PlayStation, and PlayMemories are trademarks of Sony Corporation. Use at your own risk.

---

## Attribution & License

Released under the **MIT License**. Copyright (c) 2015 ma1co and OpenPMCA contributors. See [LICENSE.txt](LICENSE.txt).

Special thanks to:
* **ma1co** for the original [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE) reverse-engineering research.
* **nex-hack** community for initial camera subsystem documentation.
* **OpenMemories** community for custom camera applications and framework.
