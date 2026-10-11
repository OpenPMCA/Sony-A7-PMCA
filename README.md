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
  - [1. Tested (Hardware-Verified)](#1-tested-hardware-verified)
  - [2. Supported (Should Work)](#2-supported-should-work)
  - [3. Incompatible (Won't Work)](#3-incompatible-wont-work)
- [Installation & Downloads](#installation--downloads)
- [Quick Start](#quick-start)
- [Features](#features)
- [Build from Source](#build-from-source)
- [Safety & Disclaimer](#safety--disclaimer)
- [Attribution & License](#attribution--license)

---

## Supported Cameras

Only Sony cameras with the built-in Android-based PlayMemories Camera Apps subsystem are capable of running PMCA apps.

### 1. Tested (Hardware-Verified)

These models have been physically tested and verified on real hardware in this project:

| Model | Code | Status |
| :--- | :--- | :--- |
| **Sony α7** | `ILCE-7` | **Verified**: RecipeLab v1.6.2 installed on hardware with return code `0`. Tag 9050a shutter counter verified. |

### 2. Supported (Should Work)

These cameras feature the PMCA subsystem in the [upstream device reference](https://github.com/ma1co/fwtool.py/blob/cdba742b73eed5981480c326aeb30033aabf0223/devices.yml). They share the same MTP communication and app-installer protocol paths:

| Model | Series | Counter Layout | Notes |
| :--- | :--- | :---: | :--- |
| **α7R**, **α7S**, **α7 II** | Alpha Full-Frame | Tag 9050a | `ILCE-7R`, `ILCE-7S`, `ILCE-7M2` |
| **α7R II**, **α7S II** | Alpha Full-Frame | Tag 9050b | `ILCE-7RM2`, `ILCE-7SM2` (no flash rollover) |
| **α5000**, **α5100**, **α6000**, **QX1** | Alpha APS-C | Tag 9050a | `ILCE-5000`, `ILCE-5100`, `ILCE-6000`, `ILCE-QX1` |
| **α6300**, **α6500** | Alpha APS-C | Tag 9050b | `ILCE-6300`, `ILCE-6500` |
| **NEX-5R**, **NEX-5T**, **NEX-6** | NEX Series | Unsupported | Wi-Fi / NFC app install supported |
| **RX100 III**, **IV**, **V** | Cyber-shot RX | Unsupported | 1-inch sensor compacts |
| **RX10 II**, **III**, **RX1R II** | Cyber-shot RX | Unsupported | Bridge and 35mm full-frame |
| **HX60/V**, **HX90/V**, **HX400/V**, **WX500** | Cyber-shot HX/WX | Unsupported | Travel zoom compacts |

> **Note on Shutter Count:** Shutter decoding reads metadata from an **existing photo** on the camera's SD card via MakerNote Tag 0x9050. No photo is automatically taken. Models marked "Unsupported" do not use Tag 0x9050. Unlisted models default to read-only diagnostics unless active installer mode is detected. See [camera support details](docs/camera-support.md).

### 3. Incompatible (Won't Work)

These cameras do **not** have the PMCA subsystem. The app detects them and allows read-only hardware inspection, but automatically disables installation controls to prevent errors:

* **Modern Alpha (2017+)**: α7 III, α7 IV, α7C, α7C II, α7R III/IV/V, α7S III, α9 series, α1, α6100, α6400, α6600, α6700, ZV-1, ZV-E10, FX3, FX30.
* **Earlier Non-PMCA Cameras**: NEX-3, NEX-5, NEX-5N, NEX-7, RX100 (Gen 1/2), RX1, RX1R, and A-mount SLT bodies (A77, A99, etc.).

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
