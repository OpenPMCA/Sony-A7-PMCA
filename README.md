# Sony Open PMCA

[![Native CI](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/workflows/build.yml/badge.svg?branch=main)](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/workflows/build.yml)
[![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)](https://github.com/OpenPMCA/Sony-Open-PMCA/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE.txt)
[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)

Native desktop app installation and read-only diagnostics for Sony cameras with **PlayMemories Camera Apps (PMCA)**. The separate CLI retains advanced tools.

Built on the open-source reverse-engineering work of [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE) by ma1co and the OpenMemories community.

---

## Supported cameras

**PMCA-capable is not the same as hardware-tested.** The models below have an `apps` entry in the [pinned upstream device reference](https://github.com/ma1co/fwtool.py/blob/cdba742b73eed5981480c326aeb30033aabf0223/devices.yml). Their installer path is shared, but APK compatibility still depends on the app and camera firmware.

| Camera family | Models and USB model codes | Installation evidence in this project | Image-counter decoder |
|---|---|---|---|
| Original full-frame Alpha | α7 `ILCE-7` | **RecipeLab installation confirmed** on macOS | A layout; fixture-tested |
| Other original full-frame Alpha | α7R `ILCE-7R`, α7S `ILCE-7S`, α7 II `ILCE-7M2` | Upstream PMCA eligibility; not physically tested here | A layout; fixture-tested |
| Later PMCA full-frame Alpha | α7R II `ILCE-7RM2`, α7S II `ILCE-7SM2` | Upstream PMCA eligibility; not physically tested here | B layout; fixture-tested |
| Early APS-C Alpha | α5000 `ILCE-5000`, α5100 `ILCE-5100`, α6000 `ILCE-6000`, QX1 `ILCE-QX1` | Upstream PMCA eligibility; not physically tested here | A layout; fixture-tested |
| Later PMCA APS-C Alpha | α6300 `ILCE-6300`, α6500 `ILCE-6500` | Upstream PMCA eligibility; not physically tested here | B layout; fixture-tested |
| NEX | NEX-5R, NEX-5T, NEX-6 | Upstream PMCA eligibility; not physically tested here | Not implemented |
| Cyber-shot RX | RX100 III `DSC-RX100M3`, IV `DSC-RX100M4`, V `DSC-RX100M5`; RX10 II `DSC-RX10M2`, III `DSC-RX10M3`; RX1R II `DSC-RX1RM2` | Upstream PMCA eligibility; not physically tested here | Not implemented |
| Cyber-shot HX/WX | HX60/HX60V `DSC-HX60`/`DSC-HX60V`, HX90/HX90V `DSC-HX90`/`DSC-HX90V`, HX400/HX400V `DSC-HX400`/`DSC-HX400V`, WX500 `DSC-WX500` | Upstream PMCA eligibility; not physically tested here | Not implemented |

A/B are model-specific Sony MakerNote layouts, not camera firmware versions. Counter decoding reads an **existing photo** and reports its capture-time metadata. Live counter reads have not been physically verified here. Flash, electronic-shutter behavior and sampled-image coverage can limit the result. See [camera support details](docs/camera-support.md).

**Not app-capable in the reference:** examples include α9, α7 III, α7R III, α6400, α6600, original RX100/RX10 and A-mount α77 II. Use model-specific eligibility, not a release-year cutoff. New or unlisted models remain unconfirmed unless a genuine Sony installer protocol is detected.

**App requirements differ:** BetterManual targets α5100 controls; GPS Downloader needs built-in GPS; OpenMemories: Launcher targets camcorder/action-camera workflows. These requirements are separate from PMCA eligibility. Download validation is not proof that an app runs on every listed body.

---

## 💻 Installation & Downloads

| Operating System | Package Format | Installation Method | Architecture |
| :--- | :--- | :--- | :--- |
| **macOS** (Homebrew) | Cask | `brew tap OpenPMCA/Sony-Open-PMCA https://github.com/OpenPMCA/Sony-Open-PMCA`<br>`brew install --cask sony-open-pmca` | Apple Silicon (`arm64`) |
| **macOS** (Manual) | `.zip` (App bundle) | Download [`Sony-Open-PMCA-1.1.0-macos-arm64.zip`](https://github.com/OpenPMCA/Sony-Open-PMCA/releases) → Extract to `/Applications` | Apple Silicon (`arm64`) |
| **Windows** | Standalone `.exe` | Download [`Sony-Open-PMCA-1.1.0-windows-x64.exe`](https://github.com/OpenPMCA/Sony-Open-PMCA/releases) → Run directly (no install required) | 64-bit Windows (`x64`) |
| **Linux** | `.AppImage` | Download [`Sony-Open-PMCA-1.1.0-linux-x86_64.AppImage`](https://github.com/OpenPMCA/Sony-Open-PMCA/releases)<br>`chmod +x Sony-Open-PMCA-*.AppImage && ./Sony-Open-PMCA-*.AppImage` | 64-bit Linux (`x86_64`) |

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
| **Image counter metadata** | Routes Alpha A/B MakerNotes from an existing image with capture-time and sampling caveats | Fixture-tested; live verification pending |
| **Local APK Staging** | Validate package, declared minSdk 1–10 and certificate presence; confirm installation on an eligible camera | Model and transport gated |
| **Application Store** | 26 community apps with verified direct HTTPS download and model caveats | ✅ Ready |
| **Smooth Mouse Scroll** | Instant 60px/notch wheel scrolling and 1:1 Apple Trackpad `<TouchpadScroll>` | ✅ Ready |
| **Activity Logging** | Live search filter, level selector (All / Errors / Info), and raw error trace copying | ✅ Ready |
| **Cross-Platform** | Native Windows, Linux and Apple Silicon builds; hardware USB checks remain model/platform-specific | CI builds passed for the linked revision |

---

## 🧪 Testing & CI Status

All builds and tests are continuously validated via GitHub Actions native runners:

| Test Target | Runner | Evidence & Results | Status |
| :--- | :--- | :--- | :---: |
| **macOS Native CI** | `macos-14` (Apple Silicon) | [Run 38111647230](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/runs/38111647230): Unit tests, Tk smoke, PyInstaller, `--check-runtime` | ✅ **PASS** |
| **Windows Native CI** | `windows-2022` (x64) | [Run 38111647230](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/runs/38111647230): Unit tests, Tk smoke, one-file EXE, `--check-runtime` | ✅ **PASS** |
| **Linux Native CI** | `ubuntu-22.04` (x86_64) | [Run 38111647230](https://github.com/OpenPMCA/Sony-Open-PMCA/actions/runs/38111647230): Xvfb tests, smoke, `appimagetool` packaging, AppImage verification | ✅ **PASS** |
| **Unit Test Suite** | Current local correction candidate | 238 tests passed, no skips with 4 cached real APK fixtures ([Evidence](docs/camera-support-validation.json)); linked CI covers its earlier revision | ✅ **PASS** |
| **Store APK Validation** | Local download audit | 26/26 community APKs downloaded & validated ([Audit Evidence](docs/appstore-download-validation.json)) | ✅ **PASS** |
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
