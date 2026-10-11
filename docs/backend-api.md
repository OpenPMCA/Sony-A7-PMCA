# Sony A7 PMCA Backend API Contract (v1.0.0)

This document specifies the official backend API contract implemented across `pmca.commands.usb`, `pmca.marketserver`, and `pmca.appstore.catalog`.

---

## 1. Camera Status & Concurrency (`pmca.commands.usb`)

### `getCameraStatus(driverName='libusb-mtp', probe_communication=True)`
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
    'status': str,             # 'ready' | 'busy' | 'access_denied' | 'unsupported' | 'disconnected'
    'failure_reason': str|None,# Factual error reason when appConnected is False; None when ready
    
    # Device Identification
    'name': str|None,          # Model name (e.g. 'ILCE-7')
    'model': str|None,         # Same as name
    'manufacturer': str,       # 'Sony'
    'vendor': str|None,        # 'Sony (0x054c)' or None if disconnected
    'serial': str|None,        # Serial number (e.g. '1234567')
    'firmware_version': str|None, # Verified camera system firmware (e.g. '3.20') or 'Unavailable without firmware query'
    'ptp_device_version': str|None, # PTP transport DeviceVersion string (e.g. '3.0')
    
    # Connection Mode
    'mode': str,               # 'MTP' | 'App installation' | 'Mass Storage' | 'Service mode' | 'Access Denied' | 'Disconnected' | 'Busy'
    'source_mode': str,        # Underlying transport mode ('MTP' | 'App installation' | 'Mass Storage' | etc.) even when mode is 'Busy'
    
    # Capabilities (from standard PTP GetDeviceInfo)
    'capabilities': list[int], # Supported PTP operation codes (e.g. [0x1001, 0x9280, ...])
    'properties': list[int],   # Supported PTP device property codes (e.g. [0x5001, ...])
    'events': list[int],       # Supported PTP event codes
    'formats': list[int],      # Supported PTP capture/image format codes
    
    # Shutter Count
    'shutter_count': {
        'available': bool,     # False on standard read-only MTP
        'value': int|None,     # None when unavailable
        'reason': str,         # 'Direct shutter actuation counter is not exposed over standard MTP read-only commands without service-mode activation.'
    }
}
```

#### Status States
1. **`ready`**: Physical device detected AND live MTP/MSC session verified. `connected=True`, `appConnected=True`, `physicalDetected=True`.
2. **`access_denied`**: Physical device detected on USB, but OS driver detachment failed or interface is locked (e.g. macOS `ptpcamerad` holding interface, `EACCES` / `LIBUSB_ERROR_ACCESS` -3). `connected=False`, `appConnected=False`, `physicalDetected=True`. **Guarantees no false green "Ready" state.**
3. **`busy`**: Camera transfer currently active. `busy=True`.
4. **`unsupported`**: Device attached but in unsupported mode or error. `connected=False`, `appConnected=False`.
5. **`disconnected`**: No Sony USB device on bus. `connected=False`, `appConnected=False`, `physicalDetected=False`.

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
Downloads, cryptographically parses, and validates an APK archive.
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
Analyzes and cryptographically validates an APK package before transfer:
- Uses `ApkParser` on binary `AndroidManifest.xml` (handles both UTF-8 flag 0x100 and UTF-16 string pools).
- Extracts and checks:
  - `getPackageName()`: package identifier must be non-empty.
  - `getVersionName()`: semantic version string.
  - `getMinSdkVersion()`: ensures Android API compatibility (1 <= sdk <= 10).
  - `getCert()`: verifies presence of signature certificate.
- Output: Logs package and version, prints compatibility warnings, and returns the validated `ApkParser` instance.
- Error handling: Raises `ValueError` on corrupted files, bad zip archives, or missing manifests, stopping execution before any camera state changes.

### `installCommand(driverName=None, apkFile=None, appPackage=None, outFile=None, statusFunc=None)`
- **Immutable Preflight**: Resolves and validates `apkData` with `checkApk(io.BytesIO(apkData))` **BEFORE** calling `SonyExtCmdCamera.switchToAppInstaller()` or touching USB drivers.
- Guarantees camera mode remains unchanged if the selected APK is invalid or corrupt.
- Once preflight passes and camera is in App Installation mode, passes `io.BytesIO(apkData)` directly to `installApp`.
- Dispatches transfer progress to `statusFunc(status)` with percent and message (`Uploading`, `Downloading`, `Installing`).
- Server ACK and install completion: Waits for camera to post completion notification, asserting `Result(code=0, message='Successfully completed')`.

### `getReadOnlyCameraInfo(driverName=None)`
Non-intrusive query function reading full hardware metadata:
- Returns: `Model`, `Product code`, `Serial number` (8-digit body serial), `PTP version`, `Firmware version`, `USB mode`, and mounted `Lens` (model & firmware) via read-only vendor descriptors (`SONY_CMD_DevInfoSender_GetModelInfo`, `SONY_CMD_LensCommunicator_GetMountedLensInfo`).
- Never calls `SonyUpdaterCamera.init()` or invokes mode changes.

---

## 5. Sony ILCE-7 Shutter Counter Extraction (`pmca.util.shutter`)

### Decipher Algorithm (Tag 0x9050 / Tag9050a)
Sony MakerNote Tag `0x9050` uses a substitution cipher:
- Encipher rule: $c = b^3 \pmod{249}$
- Decipher rule: $b = c^{55} \pmod{249}$ for $c < 249$. Bytes $249 \dots 255$ are preserved unchanged.
- Pure Python execution: Uses precomputed 256-byte translation table `_DECIPHER_TABLE` with `data.translate(_DECIPHER_TABLE)` for zero-overhead decoding.

### Offsets & Lifetime Actuation Logic (Little-Endian)
- `0x31` (offset 49): `FlashStatus` (bit 0 == 1 indicates flash fired).
- `0x32` (offset 50): `ShutterCount` (24-bit LE integer, wraps modulo 65,536 on A7/A7R).
- `0x4c` (offset 76): `ShutterCount2` (24-bit LE integer, full lifetime mechanical count when `FlashStatus & 1 == 0`).
- `0x51` (offset 81): `SonyDateTime2` (6 bytes: year-2000, month, day, hour, min, sec).

### Exposure Rules & Ambiguity Classification
1. **Non-Flash Image (`FlashStatus & 1 == 0`)**:
   - `shutter_count = ShutterCount2` (true cumulative mechanical actuations, exact, not wrapped).
   - `ambiguous = False`.
2. **Flash Image (`FlashStatus & 1 == 1`)**:
   - `ShutterCount2` is suppressed / invalid on ILCE-7.
   - `shutter_count = ShutterCount % 65536`.
   - `ambiguous = True`.
   - `warning = "Image captured with flash; ShutterCount wraps modulo 65,536 on ILCE-7"`.

### Bounded MTP Image Header Extraction
- Operations checked: `PTP_OC_GetObjectHandles` (`0x1007`) and `PTP_OC_GetPartialObject` (`0x101b`).
- Format prioritization: Queries `0x3801` (EXIF/JPEG), then `0xb881` (ARW), then all formats.
- Safe Partial Extraction: Selects latest object handle and reads initial 65,536 bytes via `0x101b`.
- **Safety**: Never aborts or truncates full `GetObject` (`0x1009`) transfers, preventing USB bulk pipe stalls.
- Never trips physical shutter curtains: Requires an existing captured image on SD storage; returns clear guidance (`"No captured image found on camera storage. Take at least one photo on SD card to read shutter count."`) if no handles exist.
