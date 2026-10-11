# Sony Open PMCA Backend API Contract (v1.1.0)

This document specifies the official backend API contract implemented across `pmca.commands.usb`, `pmca.marketserver`, and `pmca.appstore.catalog`.

---

## 1. Camera Status & Concurrency (`pmca.commands.usb`)

### `getCameraStatus(driverName=None, probe_communication=True, quiet=False)`
Alias: `checkCameraConnection`

Non-intrusive read-only query of hardware USB connection, MTP communication, and extended camera capabilities.

#### Concurrency
- Uses a reentrant lock `camera_operation` (`threading.RLock()`) shared across `installApp`, `installCommand`, and `infoCommand`.
- Non-blocking: If an active installation or transfer is in progress (`is_camera_busy() == True`), `getCameraStatus` immediately returns `status='busy'` without touching USB endpoints or interrupting the transfer.
- Provenance tracking: If a camera was previously verified, `status='busy'` preserves the verified model and mode. It does **not** assert new physical or app connectivity when busy is triggered without a verified camera.

#### Return Dictionary Schema
```python
{
    # 3-Tier Connectivity Model
    'connected': bool,         # True ONLY if real MTP/MSC session communication succeeded and camera is ready for commands
    'physicalDetected': bool,  # True if a Sony USB device is physically enumerated on the USB bus
    'appConnected': bool,      # True if live MTP/PTP/MSC session communication was verified
    'busy': bool,              # True if an exclusive USB transfer is active
    
    # Status Classification
    'status': str,             # 'ready' | 'busy' | 'unverified' | 'access_denied' | 'unsupported' | 'multiple_devices' | 'disconnected'
    'failure_reason': str|None,# Factual error reason when appConnected is False; None when ready
    
    # Device Identification
    'name': str|None,          # Model name (e.g. 'ILCE-7')
    'model': str|None,         # Same as name
    'manufacturer': str,       # 'Sony'
    'vendor': str|None,        # 'Sony (0x054c)' or None if disconnected
    'serial': str|None,        # Vendor-verified body serial only; None when unavailable
    'raw_serial': str|None,    # Optional USB/PTP transport token, never guessed to be a body serial
    'firmware_version': str|None, # Verified camera system firmware (e.g. '3.20') or 'Unavailable without firmware query'
    'ptp_device_version': str|None, # PTP transport DeviceVersion string (e.g. '3.0')
    
    # Connection Mode
    'mode': str,               # 'MTP' | 'App installation' | 'Mass Storage' | 'Service mode' | 'Access Denied' | 'Disconnected' | 'Busy'
    'source_mode': str,        # Underlying transport mode ('MTP' | 'App installation' | 'Mass Storage' | etc.) even when mode is 'Busy'
    
    # Installation eligibility (populated for verified MTP/installer sessions)
    'camera_support': dict,   # Optional pinned reference profile; pmca_apps is True, False or None
    'app_installation_supported': bool, # Model plus actual transport/proxy gate; missing means unconfirmed
    'app_installation_reason': str,     # Optional explanation; not a guarantee that a particular APK runs

    # Capabilities (from standard PTP GetDeviceInfo)
    'capabilities': list[int], # Supported PTP operation codes (e.g. [0x1001, 0x9280, ...])
    'properties': list[int],   # Supported PTP device property codes (e.g. [0x5001, ...])
    'events': list[int],       # Supported PTP event codes
    'formats': list[int],      # Supported PTP capture/image format codes
    
    # Shutter Count
    'shutter_count': {
        'available': bool,     # True only after a supported existing-image counter was read
        'value': int|None,     # None when unavailable
        'reason': str,         # Optional factual reason when unavailable; see image-counter metadata below
    }
}
```

#### Status States
1. **`ready`**: Physical device detected AND live MTP/MSC session verified. `connected=True`, `appConnected=True`, `physicalDetected=True`.
2. **`access_denied`**: Physical device detected on USB, but OS driver detachment failed or interface is locked (e.g. macOS `ptpcamerad` holding interface, `EACCES` / `LIBUSB_ERROR_ACCESS` -3). `connected=False`, `appConnected=False`, `physicalDetected=True`. **Guarantees no false green "Ready" state.**
3. **`busy`**: Camera transfer currently active. `busy=True`.
4. **`unsupported`**: Device attached but in unsupported mode or error. `connected=False`, `appConnected=False`.
5. **`disconnected`**: No Sony USB device on bus. `connected=False`, `appConnected=False`, `physicalDetected=False`.
6. **`unverified`**: Passive USB detection without a communication probe. `connected=False`, `appConnected=False`.
7. **`multiple_devices`**: More than one Sony USB device is attached; no camera is arbitrarily selected or reported install-ready.

Body firmware, vendor serial and image-counter metadata are reused only for a matching model and a non-placeholder transport or vendor identity. Unverified, failed, disconnected and non-MTP status transitions invalidate the previous MTP body cache. A first read-only MTP Info query also records model/transport installation eligibility. `camera_support['model']` is the normalized reference profile; the top-level `model` preserves the actual device-reported code, including GPS suffixes.

---

## 2. Market Server & TLS Loopback (`pmca.marketserver.server`)

### `LocalMarketServer(certFile, host='127.0.0.1', port=4443)`
- Targeted deprecation compatibility: `tlslite.utils.rijndael.Rijndael.__init__` is unwrapped with `inspect.unwrap()`, eliminating `TypeError: 'NoneType' object is not iterable` in frozen PyInstaller environments without broad monkeypatching.
- Socket lifecycle: `server_close()` is invoked upon context manager exit (`ServerContext.__exit__`).
- Clean exception handling: `finish_request` catches `tlslite.errors.TLSError`, `ConnectionResetError`, and `BrokenPipeError`, closing both TLS and underlying sockets in `finally:` without leaking port bindings.

### `verify_tls_handshake(certFile=None, host='127.0.0.1', timeout=5)`
Self-contained loopback diagnostic verifying TLS 1.2 CBC encryption (`AES128-SHA` / `AES256-SHA`) on an ephemeral port.
```python
# Returns:
{
    'success': bool,       # True only if handshake and HTTP GET -> SPK record exchange succeeded
    'cipher': str|None,    # Negotiated cipher (e.g. 'AES256-SHA')
    'version': str|None,   # Negotiated TLS version (e.g. 'TLSv1.2')
    'port': int|None,      # Bound ephemeral port
    'error': str|None,     # Error message if failed
}
```
*Note for GUI/Runtime integration*: Callers must check `res.get('success') is True` rather than `bool(res)` since dictionaries are always truthy.

---

## 3. Catalog & Metadata Synchronization (`pmca.appstore.catalog`)

### `loadCatalog(cachePath=None)`
Returns deep copy of cached catalog apps, falling back to `SEED_APPS` (12 verified applications). Seeds are never mutated.

### `saveCatalog(catalog, cachePath=None, last_success=None)`
Atomically writes catalog payload to persistent cache using temporary files and POSIX `os.replace`. Preserves `last_successful_sync` unless a new successful timestamp is provided.

### `syncCatalogMetadata(existingCatalog=None, timeout=10, abort_event=None, cachePath=None, force=False)`
Refreshes application release metadata with hourly caching and rate-limit backoff.
- **Hourly cache**: Skips network requests if `last_successful_sync` was within 3600 seconds (unless `force=True`).
- **Offline / Rate-limit safety**: If GitHub API returns HTTP 403 or network is unreachable, sync does **not** advance `last_successful_sync`.
- **Return Type (`SyncResult`)**:
  - Unpackable as 2-tuple: `catalog, updated = syncCatalogMetadata(...)`
  - Named attributes:
    - `res.catalog`: dict of apps
    - `res.updated`: bool (True if any versions changed)
    - `res.success`: bool (True if all attempted queries succeeded)
    - `res.partial`: bool (True if some succeeded while others hit errors)
    - `res.errors`: list of error strings
    - `res.last_success`: ISO timestamp of latest successful refresh
    - `res.updated_count`: number of updated apps

### `downloadCatalogApp(app, filename, progress=None, timeout=30)`
Downloads, parses, and validates an APK archive against the declared package/API baseline and certificate-presence checks.
- Enforces HTTPS URL scheme.
- Downloads chunked stream to `.pmca-app-*.apk` temporary file with `progress(downloaded_bytes, total_bytes)` reporting.
- Validates binary manifest with `ApkParser`:
  - Matches `getPackageName()` against expected app package.
  - Asserts `minSdkVersion` is between 1 and 10.
  - Verifies presence of APK signature certificate (`getCert()`).
- Atomically replaces `filename` via `os.replace`. Destination is untouched if download or validation fails.

---

## 4. APK Validation & Preflight Installation (`pmca.commands.usb`)

### `checkApk(apkFile)`
Parses and validates an APK package before transfer:
- Uses `ApkParser` on binary `AndroidManifest.xml` (handles both UTF-8 flag 0x100 and UTF-16 string pools).
- Extracts and checks:
  - `getPackageName()`: package identifier must be non-empty.
  - `getVersionName()`: non-empty version string.
  - `getMinSdkVersion()`: checks the declared minimum API baseline (1 <= sdk <= 10), not all runtime or camera-specific API requirements.
  - `getCert()`: verifies presence of signature certificate.
- Output: Logs package and version, prints compatibility warnings, and returns the validated `ApkParser` instance. Certificate presence is not publisher trust, a full APK-signature audit or proof that the app works on the selected camera.
- Error handling: Raises `ValueError` on corrupted files, bad zip archives, or missing manifests, stopping execution before any camera state changes.

### `installCommand(driverName=None, apkFile=None, appPackage=None, outFile=None, statusFunc=None)`
- **Immutable Preflight**: Resolves and validates `apkData` with `checkApk(io.BytesIO(apkData))` **BEFORE** calling `SonyExtCmdCamera.switchToAppInstaller()` or touching USB drivers.
- Guarantees camera mode remains unchanged if the selected APK is invalid or corrupt.
- **Camera eligibility gate**: Before a mode switch, checks the pinned model profile plus the actual Sony transport. Known app-ineligible or unconfirmed models are not switched into the installer. An already-active genuine Sony installer proxy can confirm an otherwise unlisted model; MTP installer proxy operations are rechecked before `installApp`, and a different reported model after the mode transition cancels transfer rather than selecting that camera.
- Once preflight passes and camera is in App Installation mode, passes `io.BytesIO(apkData)` directly to `installApp`.
- Dispatches transfer progress to `statusFunc(status)` with percent and message (`Uploading`, `Downloading`, `Installing`).
- Server ACK and install completion: Waits for camera to post completion notification, asserting `Result(code=0, message='Successfully completed')`.

### `getReadOnlyCameraInfo(driverName=None)`
Non-intrusive query function reading full hardware metadata:
- Normal MTP/MSC returns `Model`, `Product code`, `Serial number` (vendor-reported body serial), `PTP version`, `Firmware version`, `USB mode`, and mounted `Lens` (model & firmware) via read-only vendor descriptors (`SONY_CMD_DevInfoSender_GetModelInfo`, `SONY_CMD_LensCommunicator_GetMountedLensInfo`).
- MTP installer mode returns flat GUI-compatible fields from the same open session, with unavailable firmware/serial explanations unless a matching verified identity is cached. It cannot refresh image-counter metadata and does not reopen a competing camera session.
- Never calls `SonyUpdaterCamera.init()` or invokes mode changes.

---

## 5. Sony PMCA Alpha Shutter Counter Extraction (`pmca.util.shutter`)

### Decipher Algorithm (Tag 0x9050)
Sony MakerNote Tag `0x9050` uses a modular exponentiation substitution cipher:
- Encipher rule: $c = b^3 \pmod{249}$
- Decipher rule: $b = c^{55} \pmod{249}$ for $c < 249$. Bytes $249 \dots 255$ are preserved as identity.
- Pure Python execution: Uses precomputed 256-byte translation table `_DECIPHER_TABLE` with `data.translate(_DECIPHER_TABLE)` for zero-overhead decoding.

### Model Families & Layout Routing
Supported camera models strictly cover PMCA-compatible Alpha still camera families:

1. **Tag9050a (Gen 1 PMCA Alpha bodies)**:
   - Models: `ILCE-7`, `ILCE-7R`, `ILCE-7S`, `ILCE-7M2`, `ILCE-6000`, `ILCE-5000`, `ILCE-5100`, `ILCE-QX1`.
   - `0x31`: `FlashStatus` (bit 0 == 1 indicates flash fired).
   - `0x32`: `ShutterCount` (24-bit LE integer, wraps modulo 65,536 on A7/A7R).
   - `0x4c`: `ShutterCount2` (24-bit LE integer, usable non-flash counter value as of the examined image when `FlashStatus & 1 == 0`).
   - `0x51`: `SonyDateTime2` (6 bytes: year-2000, month, day, hour, min, sec; null when all zero).

2. **Tag9050b (Gen 2 PMCA Alpha bodies)**:
   - Models: `ILCE-7RM2`, `ILCE-7SM2`, `ILCE-6300`, `ILCE-6500`.
   - `0x39`: `FlashStatus` (bit 0 == 1 indicates flash fired).
   - `0x3a`: `ShutterCount` (24-bit LE integer, primary exposure counter, valid with or without flash, no 16-bit rollover).
   - `0x58`: `ShutterCount2` (24-bit LE integer, valid when `FlashStatus & 1 == 0`).
   - `0x61`: `SonyTimeMinSec` (minute, second only; full capture timestamp extracted from EXIF DateTimeOriginal or PTP ObjectInfo).

3. **Unsupported Models (DSC, NEX, Gen 3/4 non-PMCA bodies)**:
   - Early rejection: Returns `available=False, reason="Camera model ... shutter count extraction is not implemented for this model/metadata layout"` without issuing PTP object reads or guessing offsets.

### Exposure Rules & Ambiguity Classification
1. **Tag9050a Non-Flash (`FlashStatus & 1 == 0`)**:
   - `shutter_count = ShutterCount2` (counter value as of the examined image; not a guaranteed lifetime or shutter-replacement history).
   - `ambiguous = False`.
2. **Tag9050a Flash (`FlashStatus & 1 == 1`)**:
   - `ShutterCount2` is suppressed / invalid.
   - `shutter_count = None`, `shutter_count_modulo = ShutterCount % 65536`.
   - `ambiguous = True`, warning notes modulo 65,536 wrapping.
3. **Tag9050b Non-Flash & Flash**:
   - Primary `shutter_count` read from `0x3a` (full 24-bit LE integer, `ambiguous = False`).
   - Secondary `shutter_count2` read from `0x58` when non-flash; suppressed when flash fired.
   - Caveat: Electronic / silent exposures may not increment mechanical counter on ILCE-7RM2.

### Bounded MTP Image Header Extraction
- Operations checked: `PTP_OC_GetObjectHandles` (`0x1007`), `PTP_OC_GetObjectInfo` (`0x1008`) and `PTP_OC_GetPartialObject` (`0x101b`).
- Format prioritization: Queries `0x3801` (EXIF/JPEG), then `0xb881` (ARW), then all formats.
- Safe Partial Extraction: Examines a bounded sample of at most ten image handles, reads ObjectInfo to order candidates by available capture time, and reads only the initial 65,536 bytes via `0x101b`. Reports filename, examined/total counts and `coverage_limited`; a sampled result is not called the latest image on all storage.
- **Safety**: Never aborts or truncates full `GetObject` (`0x1009`) transfers, preventing USB bulk pipe stalls.
- Never trips physical shutter curtains: Requires an existing captured image on SD storage; returns clear guidance (`"No captured image found on camera storage. Take at least one photo on SD card to read shutter count."`) if no handles exist.
