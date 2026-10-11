# Sony Open PMCA

[![Native CI](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/workflows/build.yml/badge.svg?branch=main)](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/workflows/build.yml)
[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://github.com/OpenPMCA/Sony-Open-PMCA/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE.txt)
[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)

Native cross-platform desktop application to install custom apps, manage firmware tweaks, and read camera diagnostics on Sony digital cameras supporting **PlayMemories Camera Apps (PMCA)**.

Built on the open-source reverse-engineering work of [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE) by ma1co and the OpenMemories community.

---

## 📸 Working Devices (Supported Cameras)

Only cameras with the built-in Android-based PlayMemories Camera Apps subsystem are supported. Cameras released from late 2017 onward (such as α7 III, α7R III, α9, α6400, α7 IV) do **not** have the PMCA subsystem.

### Alpha Full-Frame Series (ILCE)

| Camera Model | Generation | Model Code | PMCA Apps | Shutter Count | Status / Notes |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **Sony α7** | Gen 1 | `ILCE-7` | ✅ | ✅ (Tag 9050a) | **Verified** (RecipeLab 1.6.2 installed & tested) |
| **Sony α7R** | Gen 1 | `ILCE-7R` | ✅ | ✅ (Tag 9050a) | Supported |
| **Sony α7S** | Gen 1 | `ILCE-7S` | ✅ | ✅ (Tag 9050a) | Supported |
| **Sony α7 II** | Gen 2 | `ILCE-7M2` | ✅ | ✅ (Tag 9050a) | Supported |
| **Sony α7R II** | Gen 2 | `ILCE-7RM2` | ✅ | Tag 9050b | Supported |
| **Sony α7S II** | Gen 2 | `ILCE-7SM2` | ✅ | Tag 9050b | Supported |

### Alpha APS-C Series (ILCE)

| Camera Model | Generation | Model Code | PMCA Apps | Shutter Count | Status / Notes |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **Sony α6000** | APS-C | `ILCE-6000` | ✅ | ✅ (Tag 9050a) | Supported |
| **Sony α6300** | APS-C | `ILCE-6300` | ✅ | Tag 9050b | Supported |
| **Sony α6500** | APS-C | `ILCE-6500` | ✅ | Tag 9050b | Supported |
| **Sony α5100** | APS-C | `ILCE-5100` | ✅ | ✅ (Tag 9050a) | Supported (BetterManual target) |
| **Sony α5000** | APS-C | `ILCE-5000` | ✅ | ✅ (Tag 9050a) | Supported |
| **Sony QX1** | Lens-style | `ILCE-QX1` | ✅ | ✅ (Tag 9050a) | Supported |

### NEX Series

| Camera Model | Model Code | PMCA Apps | Status / Notes |
| :--- | :--- | :---: | :--- |
| **Sony NEX-5R** | `NEX-5R` | ✅ | First PMCA camera generation |
| **Sony NEX-5T** | `NEX-5T` | ✅ | Supported |
| **Sony NEX-6** | `NEX-6` | ✅ | Supported |

### Cyber-shot Series (DSC)

| Camera Model | Series | PMCA Apps | Status / Notes |
| :--- | :--- | :---: | :--- |
| **Sony RX100 III** | `DSC-RX100M3` | ✅ | Supported |
| **Sony RX100 IV** | `DSC-RX100M4` | ✅ | Supported |
| **Sony RX100 V** | `DSC-RX100M5` | ✅ | Supported |
| **Sony RX10 II** | `DSC-RX10M2` | ✅ | Supported |
| **Sony RX10 III** | `DSC-RX10M3` | ✅ | Supported |
| **Sony RX1R II** | `DSC-RX1RM2` | ✅ | Supported |
| **Sony HX60 / HX60V** | `DSC-HX60` | ✅ | Supported (GPS model supported) |
| **Sony HX90 / HX90V** | `DSC-HX90` | ✅ | Supported (GPS model supported) |
| **Sony HX400 / HX400V** | `DSC-HX400` | ✅ | Supported |
| **Sony WX500** | `DSC-WX500` | ✅ | Supported |

> ℹ️ **Incompatible Models:** α7 III, α7 IV, α7R III/IV/V, α7S III, α7C, α9, α1, α6100, α6400, α6600, α6700, ZV-1, ZV-E10, and all FX series cameras do **not** run PMCA apps.

---

## 💻 Installation & Downloads

| Operating System | Package Format | Installation Method | Architecture |
| :--- | :--- | :--- | :--- |
| **macOS** (Homebrew) | Cask | `brew tap OpenPMCA/Sony-Open-PMCA https://github.com/OpenPMCA/Sony-Open-PMCA`<br>`brew install --cask sony-open-pmca` | Apple Silicon (`arm64`) |
| **macOS** (Manual) | `.zip` (App bundle) | Download [`Sony-Open-PMCA-1.0.0-macos-arm64.zip`](https://github.com/OpenPMCA/Sony-Open-PMCA/releases) → Extract to `/Applications` | Apple Silicon (`arm64`) |
| **Windows** | Standalone `.exe` | Download [`Sony-Open-PMCA-1.0.0-windows-x64.exe`](https://github.com/OpenPMCA/Sony-Open-PMCA/releases) → Run directly (no install required) | 64-bit Windows (`x64`) |
| **Linux** | `.AppImage` | Download [`Sony-Open-PMCA-1.0.0-linux-x86_64.AppImage`](https://github.com/OpenPMCA/Sony-Open-PMCA/releases)<br>`chmod +x Sony-Open-PMCA-*.AppImage && ./Sony-Open-PMCA-*.AppImage` | 64-bit Linux (`x86_64`) |

> ⚠️ Release binaries will be published under [GitHub Releases](https://github.com/OpenPMCA/Sony-Open-PMCA/releases). Until released, pre-built packages are generated as CI artifacts in [Actions](https://github.com/OpenPMCA/Sony-Open-PMCA/actions).

---

## ⚡ Quick Start

```
1. Set Camera USB Mode    → Camera Menu → Setup (wrench) → USB Connection → MTP
2. Connect Camera to PC   → Use a USB data cable (ensure camera is powered on)
3. Launch Sony Open PMCA  → App automatically detects camera and connects
4. Choose an Action       → Info (diagnostics) | Application (install apps) | Logs
```

---

## 🛠️ Features Matrix

| Feature | Description | State |
| :--- | :--- | :---: |
| **Automatic Detection** | Continuous PTP/MTP camera detection with instant Reconnect button | ✅ Ready |
| **Camera Diagnostics** | Reads Model, Vendor, PTP Version, Serial, and Lens metadata safely | ✅ Ready |
| **Shutter Actuation** | Decodes lifetime shutter count via Sony MakerNote Tag 0x9050 from camera storage | ✅ Ready |
| **Local APK Staging** | Browse and install any custom Android APK (validates minSdk 1–10 and signature) | ✅ Ready |
| **Application Store** | 26 community apps with verified direct HTTPS download and model caveats | ✅ Ready |
| **Smooth Mouse Scroll** | Instant 60px/notch wheel scrolling and 1:1 Apple Trackpad `<TouchpadScroll>` | ✅ Ready |
| **Activity Logging** | Live search filter, level selector (All / Errors / Info), and raw error trace copying | ✅ Ready |
| **Cross-Platform** | Native drivers: WPD on Windows, `libusb` on Linux, `libusb-mtp` on macOS | ✅ Ready |

---

## 🧪 Testing & CI Status

All builds and tests are continuously validated via GitHub Actions native runners:

| Test Target | Runner | Evidence & Results | Status |
| :--- | :--- | :--- | :---: |
| **macOS Native CI** | `macos-14` (Apple Silicon) | [Run 38111647230](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/runs/38111647230): Unit tests, Tk smoke, PyInstaller, `--check-runtime` | ✅ **PASS** |
| **Windows Native CI** | `windows-2022` (x64) | [Run 38111647230](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/runs/38111647230): Unit tests, Tk smoke, one-file EXE, `--check-runtime` | ✅ **PASS** |
| **Linux Native CI** | `ubuntu-22.04` (x86_64) | [Run 38111647230](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/runs/38111647230): Xvfb tests, smoke, `appimagetool` packaging, AppImage verification | ✅ **PASS** |
| **Unit Test Suite** | Local / CI | 165 tests (162 passed, 3 optional fixture skips without environment variable) | ✅ **PASS** |
| **Store APK Validation** | Local / CI | 26/26 community APKs downloaded & validated ([Audit Evidence](docs/appstore-download-validation.json)) | ✅ **PASS** |
| **Real Hardware** | Physical ILCE-7 | End-to-end RecipeLab 1.6.2 install verified with camera result code `0` | ✅ **PASS** |

See [docs/testing-status.md](docs/testing-status.md) for detailed test logs and verification matrix.

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

# 3. Run application
python pmca-gui.py              # Launch GUI
python pmca-console.py -h       # CLI tool

# 4. Run tests
python -W error::ResourceWarning -m unittest discover -s tests -v
```

---

## 🛡️ Safety & Disclaimer

* **Keep Connected:** Never disconnect the USB cable or power off the camera while an installation is running.
* **Camera Access Only:** This tool operates on the connected camera. It does not require `sudo`, disabling macOS System Integrity Protection (SIP), or installing kernel extensions.
* **Disclaimer:** This is an independent open-source project. Sony, PlayStation, and PlayMemories are trademarks of Sony Corporation. Use at your own risk.

---

## 📜 Attribution & License

Released under the **MIT License**. Copyright (c) 2015 ma1co and OpenPMCA contributors. See [LICENSE.txt](LICENSE.txt).

Special thanks to:
* **ma1co** for the original [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE) reverse-engineering research and tools.
* **nex-hack** community for initial camera subsystem documentation.
* **OpenMemories** community for custom camera applications and framework.
