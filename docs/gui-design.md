# Sony Open PMCA native desktop direction

This is the existing Tk desktop utility, not a web page or a new GUI framework. Camera owners need clear diagnostics, deliberate local APK/download workflows and understandable recovery when a camera is unavailable.

## Layout and interaction

- Keep Camera, Applications and Activity navigation, native OS controls/system fonts, the supplied mark and restrained orange branding.
- Use the current 1160×760 default and 960×640 minimum; validate both plus larger windows rather than shrinking controls to fit an untested layout.
- Applications keeps compact local APK staging above the 26-card Store. There is no Store search; Activity search remains.
- Keyboard focus must be visible, including on Store actions below the canvas viewport. Metadata refresh should preserve the selected package and useful viewport/focus context.
- Preserve immediate 60 px/notch wheel movement, 1:1 packed vertical TouchpadScroll, horizontal-only no-op and scoped Store bindtags. Activity scrolling remains independent. `after_idle` is not a 60-FPS guarantee.
- Use concise mode-specific guidance, factual progress and native focus states. Do not invent camera metadata, completed installs, celebratory animation or root/full-access promises.

## v1.2.0 responsiveness and Activity policy

The approved v1.2.0 implementation targets bounded main-thread queue work, batched log display, debounced/chunked Activity filtering and continuous indeterminate animation. The initial queue/filter tuning values and timing targets must be checked against measured real-widget workloads; they are not recorded performance results.

Activity retains the latest **5,000 complete lines** before filtering and shows how many older rows were removed since Clear. Copy/Export describe their retained current-view scope; copy errors may lack earlier context after eviction. Clear resets history/partial buffers/omission count without losing unrelated task completions. No automatic log files or hidden per-line/byte truncation are part of this policy.

Keep native selection and user scroll intent. Logs should not jump to the bottom while a person is reading/selecting older rows. Camera-operation ownership and local network activity are separate: downloading must not hide camera disconnects, overwrite another operation's progress or clear a hardware busy guard.

## Safety and transport

- macOS desktop defaults to the MTP-only libusb context. It does not seize a mounted Mass Storage camera volume; legacy CLI transports remain separate.
- Mass Storage exposes a storage volume, not unrestricted camera OS/firmware/app access. Existing Sony MSC vendor commands require a compatible accessible channel; app transfer ultimately uses the MTP installer proxy.
- Camera information and installation eligibility are distinct. Read-only Info may work on a body that cannot run PMCA apps; unknown/generic identity must not enable installation.
- Validate an immutable APK snapshot before installation confirmation or camera mode changes. Downloading never installs and cannot establish camera-specific app compatibility.
- Camera access on macOS requires its existing explicit confirmation and OS access. Finish external photo transfers first; do not kill services, unmount/eject disks automatically or use host privilege escalation.
- Cancel is cooperative for local download/catalog work only. Preserve existing destinations and remove only owned partial files. Do not promise safe cancellation/rollback of an in-flight camera write; keep power/USB connected and protect close during hardware operations.

## Startup and verification

The production constructors start camera-monitoring and catalog-sync workers. Cached metadata, rate limits and shutdown events bound those paths; do not describe the application as having no startup work merely because a smoke test mocks the workers. Unit/benchmark tests must replace all real camera/network/cache/dialog providers.

Source tests, real-widget acceptance and before/after measurements prove the covered software paths, not visual quality on every display or hardware compatibility on every body. Release gates also require actual native macOS/Windows/Linux builds and final-runtime verification. Only ILCE-7 plus RecipeLab has recorded physical installation evidence; image-counter live verification remains separate.
