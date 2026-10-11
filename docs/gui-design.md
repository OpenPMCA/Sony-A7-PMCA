# Sony A7 PMCA GUI direction

This is a redesign of the existing Tk desktop utility, not a web page or a new GUI framework. The audience is the camera owner; the current job is safe camera inspection and deliberate camera-app download/installation.

- Use macOS Aqua controls and the system font. Use Menlo only for activity logs.
- Keep navigation as native tabs: Camera, Applications, Activity. Additional real tools can become their own view/task later; do not add unfinished features or a plugin framework now.
- Use the user-supplied SVG mark, with its orange accent confined mainly to branding. Keep the operating system's normal control colors and focus states.
- Use a 4-point spacing rhythm, a quiet header, a camera key/value summary, and a clear APK workflow. Avoid invented camera state, metrics, or success banners.
- Start idle. Do not enumerate cameras or fetch an app list on launch.
- Download RecipeLab only on button click. Validate the official repository asset, package, and SDK; preserve existing files on failure. Downloading never installs.
- The local Mac preview disables camera/install actions until a supported native camera backend is implemented. GUI/download tests remain available. Never infer camera-access success from a valid signature or offline tests.
- The Mac transport selection uses an MTP-only libusb context. Do not capture a mounted Mass Storage camera through this app; the broader legacy CLI transports remain available separately.
- Read camera info only on user request. Mac device capture requires a confirmation and OS authorization; it may temporarily disconnect other clients.
- Validate an immutable APK snapshot before installation confirmation. Never reopen a changed pathname for transfer.
- Show real progress when reported; use indeterminate progress when no total is known. Show completed installation only after a verified server result.
- Buffer fragmented log writes into timestamped lines, distinguish stderr/errors, and provide copy/clear controls.
- Disable conflicting actions and refuse normal close/quit while an operation is active. Do not add celebratory animation.

Offline tests cover data flow, error/cancel paths, logs, downloads, parsing, and packaging. They do not establish live USB access, installation success, color output, or visual quality of the real window. Those checks wait until the camera is charged and the user can test normally.

## Two-panel Applications Layout
- Upper panel: Local APK File (Import & Install). Allows browsing local APK files, inspecting manifest metadata (package name, version, min Android SDK API 1–10), and initiating camera installation.
- Lower panel: Downloadable Applications Catalog. Contains verified camera apps:
  - Featured: RecipeLab (voxivoid) picture profile and film simulation manager with direct release downloader.
  - Community Catalog: PMCA / OpenMemories App Store catalog with on-demand refresh, app selection, metadata preview, and "Download App APK…" action.
- Pipeline: Downloading any catalog app validates the APK manifest (package identifier, SDK 1–10), writes the validated file to the user's chosen destination, and automatically populates the upper panel's Selected APK staging area ready for camera installation.
- Default geometry is 940x720 with minsize 880x640; footer is anchored to the bottom before notebook expansion to eliminate text baseline clipping on macOS Aqua.
