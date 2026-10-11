# Sony A7 PMCA distribution

Sony A7 PMCA retains the same native Info, Application and Logs flows on each platform. The product version is 1.0.0. Automatic Store synchronization fetches metadata only. APK download requires a selected action. Installation requires a separate confirmation and a usable camera.

## Native builds and runtime checks

PyInstaller builds must run on the target operating system. This Apple Silicon host cannot produce or execute native Windows or Linux binaries. The repository workflow prepares native jobs with read-only repository permissions and uploads build artifacts. It does not create a tag or publish a release.

| Platform | Intended artifact | Driver default | Verification status |
|---|---|---|---|
| Apple Silicon macOS | `Sony-A7-PMCA-1.0.0-macos-arm64.zip` | libusb MTP | Local ARM64 bundle and frozen runtime verified. Final archive is regenerated after source stabilization. |
| Windows x64 | `Sony-A7-PMCA-1.0.0-windows-x64.exe` | Native Windows Portable Devices, with libusb fallback | Native build and runtime execution require the Windows runner. |
| Linux x86_64 | `Sony-A7-PMCA-1.0.0-linux-x86_64.AppImage` | libusb | Native build and final AppImage execution require the Linux runner. |

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
python packaging/build.py verify --executable 'dist/Sony A7 PMCA.app/Contents/MacOS/Sony A7 PMCA' --arch arm64

# Windows, including GUI-subsystem process completion
python packaging/build.py verify --executable 'dist/Sony-A7-PMCA-1.0.0-windows-x64.exe' --arch x64

# Linux, including the actual AppImage launcher and container
APPIMAGE_EXTRACT_AND_RUN=1 xvfb-run -a python packaging/build.py verify --executable dist/Sony-A7-PMCA-1.0.0-linux-x86_64.AppImage --arch x64
```

The verifier waits for process completion and rejects incorrect architecture, source-mode output, failed libusb loading, missing Tcl, certificate failures, failed encryption roundtrip or failed TLS handshake. Static tests and workflow configuration do not prove native execution.

## macOS archive and Homebrew

The packager validates the ARM64 executable and deep/strict code-signature integrity, then creates a ZIP preserving bundle symlinks. It derives the cask checksum from that exact ZIP. It also reads native Mach-O deployment targets across bundled frameworks and records the highest minimum operating-system requirement in the cask.

The current local Python and Tcl/Tk dependencies require macOS 27.0. The bundled libusb requires macOS 26.0. The bootloader's lower deployment target does not make this particular archive compatible with older macOS releases. An older-system release must be built and tested with older compatible dependencies. The native macOS CI job is intended to produce that separate artifact, but its execution has not been verified here.

The cask lives in `Casks/sony-a7-pmca.rb`. Its download URL references this repository's future release. That release is not yet published, so these are installation commands for after publication, not currently available downloads:

```sh
brew tap OpenPMCA/Sony-A7-PMCA https://github.com/OpenPMCA/Sony-A7-PMCA
brew install --cask sony-a7-pmca
```

The cask definition can be evaluated locally without creating a tap or installing the application:

```sh
HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ANALYTICS=1 brew ruby -e 'require "cask"; c = Cask::CaskLoader.load(File.read(ARGV.fetch(0))); puts c.depends_on.inspect' Casks/sony-a7-pmca.rb
```

The local bundle is ad-hoc signed, not Developer ID signed or notarized. Homebrew metadata does not replace Apple notarization. Do not disable Gatekeeper, System Integrity Protection or camera services to bypass a release limitation.

## Production release gates

- Native Windows and Linux jobs must finish and verify their actual final artifacts. Test USB communication and selected installation on supported cameras on those platforms before declaring camera compatibility.
- The macOS public artifact needs a tested compatibility floor and a deliberate Developer ID signing/notarization decision.
- Regenerate the cask and checksum from the final published ZIP. Do not reuse the checksum from a different native-runner or local build.
- Publication requires explicit authorization. No commit, push, tag, GitHub release, tap repository or public binary upload was performed during this implementation.
- A successful APK package/API/certificate check does not prove an application works on every camera model. Keep model requirements and maintainer caveats visible. RecipeLab is the application whose installation was confirmed on the connected ILCE-7.

Primary tooling references: [GitHub native runner architectures](https://docs.github.com/en/actions/reference/runners/github-hosted-runners), [PyInstaller documentation](https://pyinstaller.org/en/stable/), [AppImage tool releases](https://github.com/AppImage/appimagetool/releases), and [Homebrew cask cookbook](https://docs.brew.sh/Cask-Cookbook).
