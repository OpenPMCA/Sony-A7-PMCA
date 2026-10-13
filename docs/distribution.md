# Sony Open PMCA distribution

Sony Open PMCA retains the same native Info, Application and Logs flows on each platform. The product version is 1.2.0. Automatic Store synchronization fetches metadata only. APK download requires a selected action. Installation requires a separate confirmation and a usable camera.

## Native builds and runtime checks

PyInstaller builds must run on the target operating system. This Apple Silicon host cannot produce or execute native Windows or Linux binaries. The repository workflow prepares native jobs with read-only repository permissions and uploads build artifacts. It does not create a tag or publish a release.

| Platform | Intended artifact | Driver default | Verification status |
|---|---|---|---|
| Apple Silicon macOS | `Sony-Open-PMCA-1.2.0-macos-arm64.zip` | libusb MTP | v1.2.0 passed native `macos-14` CI (Run 38355014314); published ZIP independently passed relocation/runtime, deep/strict ad-hoc signature and 47-module source-parity checks. |
| Windows x64 | `Sony-Open-PMCA-1.2.0-windows-x64.exe` | Native Windows Portable Devices, with libusb fallback | v1.2.0 passed native `windows-2022` CI (Run 38355014314), including the final executable runtime diagnostic. |
| Linux x86_64 | `Sony-Open-PMCA-1.2.0-linux-x86_64.AppImage` | libusb | v1.2.0 passed native `ubuntu-22.04` CI (Run 38355014314), including the final AppImage runtime diagnostic. |

Install the repository requirements in an isolated build environment, then run:

```sh
python -W error::ResourceWarning -m unittest discover -s tests -v
python tests/smoke_gui.py
python packaging/build.py build
python packaging/build.py package
```

Linux requires a working Tk interpreter, Xvfb for headless GUI tests, and libusb development libraries at build time. The AppImage tool is pinned to an upstream HTTPS asset and checked against its recorded SHA-256. Windows uses the pinned libusb-package wheel to obtain a libusb 1.0 DLL. The old libusb 0.1 DLL is not accepted.

The Windows/Linux specification includes a narrow frozen-runtime hook that resolves libusb from the bundle directory. It does not depend on a user having system libusb or linker-development tools. AppRun preserves arguments containing spaces and does not add the current working directory to the library search path.

The final deliverable must execute its own dependency and encrypted loopback diagnostic:

```sh
# macOS
python packaging/build.py verify --executable 'dist/Sony Open PMCA.app/Contents/MacOS/Sony Open PMCA' --arch arm64

# Windows, including GUI-subsystem process completion
python packaging/build.py verify --executable 'dist/Sony-Open-PMCA-1.2.0-windows-x64.exe' --arch x64

# Linux, including the actual AppImage launcher and container
APPIMAGE_EXTRACT_AND_RUN=1 xvfb-run -a python packaging/build.py verify --executable dist/Sony-Open-PMCA-1.2.0-linux-x86_64.AppImage --arch x64
```

The verifier waits for process completion and rejects incorrect architecture, source-mode output, failed libusb loading, missing Tcl, certificate failures, failed encryption roundtrip or failed TLS handshake. Static tests and workflow configuration do not prove native execution.

## macOS archive and Homebrew

The packager validates the ARM64 executable and deep/strict code-signature integrity, then creates a ZIP preserving bundle symlinks. It derives the cask checksum from that exact ZIP. It also reads native Mach-O deployment targets across bundled frameworks and records the highest minimum operating-system requirement in the cask.

The historical local v1.0.0 Python and Tcl/Tk dependencies require macOS 27.0. The published v1.2.0 macOS artifact uses native CI Python 3.11 and requires macOS 14.0 (Sonoma) or newer, verified from its bundled Mach-O dependencies and its successful `macos-14` runtime. The bundled libusb requires macOS 26.0. The bootloader's lower deployment target does not make this particular archive compatible with older macOS releases. An older-system release must be built and tested with older compatible dependencies. The separate v1.2.0 native CI artifact and its encrypted runtime were verified in Run 38355014314.

The cask lives in `Casks/sony-open-pmca.rb` and now matches the exact published v1.2.0 ZIP (SHA-256 `ae123f7a6e56659b2b864d96d7b39b0ac48cfb252af3ce335d09f06c826e8113`). The release is available at [v1.2.0](https://github.com/OpenPMCA/Sony-Open-PMCA/releases/tag/v1.2.0):

```sh
brew tap OpenPMCA/Sony-Open-PMCA https://github.com/OpenPMCA/Sony-Open-PMCA
brew install --cask sony-open-pmca
```

The cask definition can be evaluated locally without creating a tap or installing the application:

```sh
HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ANALYTICS=1 brew ruby -e 'require "cask"; c = Cask::CaskLoader.load(File.read(ARGV.fetch(0))); puts c.depends_on.inspect' Casks/sony-open-pmca.rb
```

The local bundle is ad-hoc signed, not Developer ID signed or notarized. Homebrew metadata does not replace Apple notarization. Do not disable Gatekeeper, System Integrity Protection or camera services to bypass a release limitation.

## Production release gates

- Native Windows and Linux jobs must finish and verify their actual final artifacts. Test USB communication and selected installation on supported cameras on those platforms before declaring camera compatibility.
- The v1.2.0 macOS artifact has a verified macOS 14.0 floor and deliberately ships ad-hoc signed; Developer ID signing/notarization remain uncompleted and disclosed.
- Regenerate the cask and checksum from the final published ZIP. Do not reuse the checksum from a different native-runner or local build.
- The user explicitly authorized release v1.2.0 on 2026-10-11. Source publication, tag and binary publication proceed only after their verification gates; do not treat the historical v1.0.0 reports as v1.2.0 build evidence.
- A successful APK package/API/certificate check does not prove an application works on every camera model. Keep model requirements and maintainer caveats visible. RecipeLab is the application whose installation was confirmed on the connected ILCE-7.

Primary tooling references: [GitHub native runner architectures](https://docs.github.com/en/actions/reference/runners/github-hosted-runners), [PyInstaller documentation](https://pyinstaller.org/en/stable/), [AppImage tool releases](https://github.com/AppImage/appimagetool/releases), and [Homebrew cask cookbook](https://docs.brew.sh/Cask-Cookbook).
