# Sony Open PMCA

[![Native CI](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/workflows/build.yml/badge.svg?branch=main)](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/workflows/build.yml)
[![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)](https://github.com/OpenPMCA/Sony-Open-PMCA/releases/tag/v1.1.0)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE.txt)
[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)

Native cross-platform desktop application to install custom apps, inspect camera diagnostics, and decode shutter actuations on Sony digital cameras supporting **PlayMemories Camera Apps (PMCA)**.

Built on the open-source reverse-engineering research of [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE) by ma1co and the OpenMemories community.

---

## 📑 Table of Contents

- [Supported Cameras](#-supported-cameras)
  - [1. Tested (Hardware-Verified)](#1-tested-hardware-verified)
  - [2. Supported (Should Work — PMCA-Capable)](#2-supported-should-work--pmca-capable)
  - [3. Unconfirmed (Unlisted Models)](#3-unconfirmed-unlisted-models)
  - [4. Incompatible (Won't Work — No PMCA Subsystem)](#4-incompatible-wont-work--no-pmca-subsystem)
- [Installation & Downloads](#-installation--downloads)
  - [macOS](#macos)
  - [Windows](#windows)
  - [Linux](#linux)
- [Quick Start](#-quick-start)
- [Features](#-features)
- [Build from Source](#-build-from-source)
- [Testing & CI Status](#-testing--ci-status)
- [Safety & Disclaimer](#-safety--disclaimer)
- [Attribution & License](#-attribution--license)

---

## 📸 Supported Cameras

Camera compatibility is classified into four distinct categories based on physical hardware verification, PMCA framework capability in the [upstream device reference](https://github.com/ma1co/fwtool.py/blob/cdba742b73eed5981480c326aeb30033aabf0223/devices.yml), and protocol detection:

### 1. Tested (Hardware-Verified)
These models have been physically connected and verified end-to-end on real hardware in this project.

| Camera Model | Series | Model Code | PMCA Apps | Shutter Counter | Verification Evidence |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **Sony α7** | Alpha Full-Frame | `ILCE-7` | ✅ | ✅ (Tag 9050a) | **Confirmed on hardware**: RecipeLab v1.6.2 installation completed with camera result code `0` on macOS. |

---

### 2. Supported (Should Work — PMCA-Capable)
These cameras feature the built-in Android-based PMCA subsystem in the upstream reference. They share the same MTP communication and app-installer protocol paths. APK compatibility depends on individual application requirements and camera firmware.

#### Alpha Full-Frame Series (ILCE)
| Camera Model | Generation | Model Code | PMCA Apps | Shutter Counter | Notes |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **Sony α7R** | Gen 1 | `ILCE-7R` | ✅ | ✅ (Tag 9050a) | Full PMCA support; shutter count wraps modulo 65,536 on flash |
| **Sony α7S** | Gen 1 | `ILCE-7S` | ✅ | ✅ (Tag 9050a) | Full PMCA support |
| **Sony α7 II** | Gen 2 | `ILCE-7M2` | ✅ | ✅ (Tag 9050a) | Full PMCA support |
| **Sony α7R II** | Gen 2 | `ILCE-7RM2` | ✅ | ✅ (Tag 9050b) | Full PMCA support; primary exposure counter (Tag 9050b) |
| **Sony α7S II** | Gen 2 | `ILCE-7SM2` | ✅ | ✅ (Tag 9050b) | Full PMCA support; primary exposure counter (Tag 9050b) |

#### Alpha APS-C Series (ILCE)
| Camera Model | Series | Model Code | PMCA Apps | Shutter Counter | Notes |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **Sony α5000** | APS-C | `ILCE-5000` | ✅ | ✅ (Tag 9050a) | Full PMCA support |
| **Sony α5100** | APS-C | `ILCE-5100` | ✅ | ✅ (Tag 9050a) | Target body for BetterManual custom controls |
| **Sony α6000** | APS-C | `ILCE-6000` | ✅ | ✅ (Tag 9050a) | Most popular PMCA body; CustomLut target |
| **Sony α6300** | APS-C | `ILCE-6300` | ✅ | ✅ (Tag 9050b) | Full PMCA support; primary exposure counter (Tag 9050b) |
| **Sony α6500** | APS-C | `ILCE-6500` | ✅ | ✅ (Tag 9050b) | Full PMCA support; primary exposure counter (Tag 9050b) |
| **Sony QX1** | Lens-style | `ILCE-QX1` | ✅ | ✅ (Tag 9050a) | E-mount lens-style camera with PMCA subsystem |

#### NEX Series
| Camera Model | Model Code | PMCA Apps | Shutter Counter | Notes |
| :--- | :--- | :---: | :---: | :--- |
| **Sony NEX-5R** | `NEX-5R` | ✅ | Unsupported | First PMCA camera generation; Wi-Fi app installer |
| **Sony NEX-5T** | `NEX-5T` | ✅ | Unsupported | Full PMCA support with NFC |
| **Sony NEX-6** | `NEX-6` | ✅ | Unsupported | Full PMCA support with OLED EVF |

#### Cyber-shot Series (DSC)
| Camera Model | Series | Model Code | PMCA Apps | Shutter Counter | Notes |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **Sony RX100 III** | RX Series | `DSC-RX100M3` | ✅ | Unsupported | 1-inch sensor compact with popup EVF |
| **Sony RX100 IV** | RX Series | `DSC-RX100M4` | ✅ | Unsupported | High frame rate 4K PMCA compact |
| **Sony RX100 V** | RX Series | `DSC-RX100M5` | ✅ | Unsupported | Fast phase-detect AF PMCA compact |
| **Sony RX10 II** | RX Series | `DSC-RX10M2` | ✅ | Unsupported | Bridge camera with constant F2.8 zoom |
| **Sony RX10 III** | RX Series | `DSC-RX10M3` | ✅ | Unsupported | Super-zoom 24–600mm bridge camera |
| **Sony RX1R II** | RX Series | `DSC-RX1RM2` | ✅ | Unsupported | Full-frame 42MP fixed 35mm compact |
| **Sony HX60 / HX60V** | HX Series | `DSC-HX60` | ✅ | Unsupported | Travel zoom (GPS model supported) |
| **Sony HX90 / HX90V** | HX Series | `DSC-HX90` | ✅ | Unsupported | Compact 30x zoom with popup EVF |
| **Sony HX400 / HX400V** | HX Series | `DSC-HX400` | ✅ | Unsupported | 50x optical zoom bridge camera |
| **Sony WX500** | WX Series | `DSC-WX500` | ✅ | Unsupported | Compact selfie-screen travel zoom |

> ℹ️ **Image Counter Notes**: Tag 9050a and Tag 9050b decoders read metadata from an **existing captured photo** on camera storage (via bounded partial MTP read). Live counter reads require examining a photo; no photos are automatically triggered or taken. For NEX and Cyber-shot models, Tag 0x9050 decoding is explicitly reported as unsupported. See [Camera Support Details](docs/camera-support.md).

---

### 3. Unconfirmed (Unlisted Models)
Cameras not present in the reference database (or custom/newer revisions).
* **Default State**: PMCA app installation is disabled in standard MTP mode to avoid accidental misconfiguration.
* **Diagnostic Inspection**: Read-only diagnostic queries ("Get camera info", USB descriptors, properties) remain fully functional.
* **Activation**: If the camera is switched to or detected in active Sony App Installation mode on the wire, installation controls are safely unlocked.

---

### 4. Incompatible (Won't Work — No PMCA Subsystem)
These cameras do **not** have the Android-based PlayMemories Camera Apps subsystem. The GUI detects the camera and keeps read-only diagnostics enabled, but **automatically disables installation controls** to prevent errors.

* **Modern Alpha Cameras (Late 2017+)**:
  * Full-frame: α7 III, α7 IV, α7C, α7C II, α7CR, α7R III, α7R IV, α7R V, α7S III, α9, α9 II, α9 III, α1
  * APS-C & Vlog: α6100, α6400, α6600, α6700, ZV-1, ZV-1 II, ZV-E10, ZV-E10 II, FX3, FX30
* **Earlier Non-PMCA Cameras (Pre-PMCA)**:
  * NEX Series: NEX-3, NEX-5, NEX-5N, NEX-7, NEX-C3, NEX-F3, NEX-VG10
  * Cyber-shot Series: RX100 (Gen 1), RX100 II, RX1, RX1R, HX5V, HX9V, HX20V, HX30V, HX50V, HX100V, HX200V, HX300
  * A-Mount SLT Series: SLT-A33, SLT-A37, SLT-A55, SLT-A57, SLT-A58, SLT-A65, SLT-A77, SLT-A77 II, SLT-A99, SLT-A99 II

---

## 💻 Installation & Downloads

Official pre-built releases are available on [GitHub Releases](https://github.com/OpenPMCA/Sony-Open-PMCA/releases/tag/v1.1.0).

### macOS
Native standalone bundle built for Apple Silicon (`arm64`), compatible with macOS 14 Sonoma or newer.

#### Option A: Homebrew Cask (Recommended)
```bash
brew tap OpenPMCA/Sony-Open-PMCA https://github.com/OpenPMCA/Sony-Open-PMCA
brew install --cask sony-open-pmca
```

#### Option B: Manual Application Bundle
1. Download [`Sony-Open-PMCA-1.1.0-macos-arm64.zip`](https://github.com/OpenPMCA/Sony-Open-PMCA/releases/download/v1.1.0/Sony-Open-PMCA-1.1.0-macos-arm64.zip).
2. Extract the archive and move `Sony Open PMCA.app` to your `/Applications` directory.
3. **First launch**: The application is ad-hoc signed. If macOS Gatekeeper shows a security prompt, right-click `Sony Open PMCA.app` in Finder and select **Open**, or run:
   ```bash
   xattr -cr "/Applications/Sony Open PMCA.app"
   ```

### Windows
Standalone single-file executable for 64-bit Windows (Windows 10 / Windows 11).

1. Download [`Sony-Open-PMCA-1.1.0-windows-x64.exe`](https://github.com/OpenPMCA/Sony-Open-PMCA/releases/download/v1.1.0/Sony-Open-PMCA-1.1.0-windows-x64.exe).
2. Run the executable directly. No installer or manual driver configuration is needed; it automatically communicates through native Windows Portable Devices (WPD) with embedded libusb fallback.

### Linux
Portable AppImage for 64-bit Linux distributions (Ubuntu, Debian, Fedora, Arch, etc.).

1. Download [`Sony-Open-PMCA-1.1.0-linux-x86_64.AppImage`](https://github.com/OpenPMCA/Sony-Open-PMCA/releases/download/v1.1.0/Sony-Open-PMCA-1.1.0-linux-x86_64.AppImage).
2. Make the file executable and run:
   ```bash
   chmod +x Sony-Open-PMCA-1.1.0-linux-x86_64.AppImage
   ./Sony-Open-PMCA-1.1.0-linux-x86_64.AppImage
   ```
3. *Tip for non-root USB access*: Ensure your user is in the `plugdev` group or install standard udev rules if camera permissions are restricted.

---

## ⚡ Quick Start

```
1. Set Camera USB Mode    → Camera Menu → Setup (wrench) → USB Connection → MTP
2. Connect Camera to PC   → Use a USB data cable (ensure camera is powered on)
3. Launch Sony Open PMCA  → App automatically detects camera and connects
4. Choose an Action       → Info (diagnostics) | Application (install apps) | Activity (logs)
```

---

## 🛠️ Features

* **Automatic Camera Detection & Hot-Plug Monitoring**: Seamless real-time PTP/MTP camera detection with instant manual Reconnect button.
* **Camera Hardware Diagnostics**: Safely inspects camera Model, Vendor, PTP Version, Body Serial, attached Lens, Product Code, and PTP capabilities.
* **Image-Based Shutter Actuation Counter**: Decodes shutter count from existing photos on storage using Sony MakerNote Tag 0x9050, supporting both Tag 9050a (Gen 1 Alpha) and Tag 9050b (Gen 2 Alpha) layouts.
* **Safe APK Installation & Eligibility Gating**: Model-eligibility gate prevents ineligible bodies from switching into installer mode. Preflights APK package identifier, camera Android baseline (API 1–10), and signature certificate.
* **Built-in Application Store**: Browse and download 26 curated open-source community applications (e.g. OpenMemories Tweak, BetterManual, RecipeLab) with direct HTTPS downloads and model-specific compatibility caveats.
* **Activity Logging & Error Reporting**: Live log search filtering, severity level selector (All / Errors / Info), auto-scrolling, one-click error copying, and atomic log export for debugging.
* **Responsive Native UI**: 1160x760 landscape desktop interface with smooth 60px/notch wheel scrolling and native Apple Trackpad 1:1 `<TouchpadScroll>` gesture support.
* **Cross-Platform Standalone Binaries**: Native standalone packages for macOS (Apple Silicon), Windows (x64), and Linux (x86_64 AppImage) with no external Python runtime required.

---

## 🔨 Build from Source

```bash
# 1. Clone repository with submodules
git clone --recurse-submodules https://github.com/OpenPMCA/Sony-Open-PMCA.git
cd Sony-Open-PMCA

# 2. Create virtual environment & install dependencies
python3 -m venv .venv
source .venv/bin/activate       # On Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Launch application
python pmca-gui.py              # Launch GUI
python pmca-console.py -h       # CLI tool

# 4. Run test suite
python -W error::ResourceWarning -m unittest discover -s tests -v
```

---

## 🧪 Testing & CI Status

All builds and tests are continuously validated via GitHub Actions native runners:

| Test Target | Runner | Evidence & Results | Status |
| :--- | :--- | :--- | :---: |
| **macOS Native CI** | `macos-14` (Apple Silicon) | [Run 38135433837](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/runs/38135433837): Unit tests, Tk smoke, PyInstaller, `--check-runtime` | ✅ **PASS** |
| **Windows Native CI** | `windows-2022` (x64) | [Run 38135433837](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/runs/38135433837): Unit tests, Tk smoke, one-file EXE, `--check-runtime` | ✅ **PASS** |
| **Linux Native CI** | `ubuntu-22.04` (x86_64) | [Run 38135433837](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/runs/38135433837): Xvfb tests, smoke, `appimagetool` packaging, AppImage verification | ✅ **PASS** |
| **Unit Test Suite** | Local / Native CI | 246 local tests passed (no skips); native CI runners passed ([Evidence](docs/release-validation-1.1.0.json)) | ✅ **PASS** |
| **Store APK Validation** | Local download audit | 26/26 community APKs downloaded & validated ([Audit Evidence](docs/appstore-download-validation.json)) | ✅ **PASS** |
| **Real Hardware** | Physical ILCE-7 | End-to-end RecipeLab 1.6.2 install verified with camera result code `0` | ✅ **PASS** |

See [docs/testing-status.md](docs/testing-status.md) for detailed test logs and verification matrix.

---

## 🛡️ Safety & Disclaimer

* **Keep Connected**: Never disconnect the USB cable or power off the camera while an app installation is in progress.
* **Non-Destructive Operations**: This tool does not perform unsolicited firmware flashing, service-mode changes, or background installations. All operations require explicit user interaction.
* **Camera Access Only**: The application operates solely on the connected USB camera. It does not require administrator privileges (`sudo`), disabling macOS System Integrity Protection (SIP), or installing third-party kernel extensions.
* **Disclaimer**: This is an independent open-source project. Sony, PlayStation, and PlayMemories are registered trademarks of Sony Corporation. Use at your own risk.

---

## 📜 Attribution & License

Released under the **MIT License**. Copyright (c) 2015 ma1co and OpenPMCA contributors. See [LICENSE.txt](LICENSE.txt).

Special thanks to:
* **ma1co** for the original [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE) reverse-engineering research and tools.
* **nex-hack** community for initial camera subsystem documentation.
* **OpenMemories** community for custom camera applications and framework.
