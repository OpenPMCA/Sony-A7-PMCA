# Sony A7 PMCA: macOS USB Access & Verification Status (v1.0.0)

## Verified Hardware & Driver Architecture

- **Target Device**: Sony Alpha 7 (ILCE-7), firmware 3.20.
- **Communication Layer**: Standard PTP/MTP transport over `libusb-mtp` (`USB_CLASS_PTP`, Class 6/1/1).
- **System Service Handling**:
  - macOS system service `/usr/libexec/ptpcamerad` claims USB interfaces for digital cameras.
  - In `pmca.usb.driver.generic.libusb`, kernel driver detachment catches Darwin `LIBUSB_ERROR_ACCESS` (-3) safely.
  - Bounded PTP commands communicate directly through USB bulk endpoints without requiring kernel kext detachment, `com.apple.vm.device-access` entitlements, `sudo`, SIP modification, or killing `ptpcamerad`.
- **On-Device Execution & Verification**:
  - Live on-device installation of RecipeLab 1.6.2 was completed and verified on physical ILCE-7 hardware (`Result(code=0, message='Successfully completed')`).
  - Read-only camera inspection (`getReadOnlyCameraInfo`) successfully reads model, product code, body serial, mounted lens data, and PTP device version in 0.06 seconds without triggering updater standby or mode switches.
  - Pure Python shutter actuation counter decodes Sony MakerNote Tag 0x9050 using modular exponentiation ($b = c^{55} \pmod{249}$), with bounded 64 KB header reads (`PTP_OC_GetPartialObject 0x101b`) and flash modulo protection.

## Driver Selection Defaults

- **Windows (`win32`)**: Native Windows Portable Devices (WPD) via `windows.wpd.MtpContext` (`driverName=None`).
- **Linux**: Generic `libusb-1.0` (`driverName='libusb'`).
- **macOS (`darwin`)**: MTP-only libusb context (`driverName='libusb-mtp'`), preventing mass storage kernel detachment conflicts.

## Privacy & Safety Invariants

- Real camera serial numbers, user account IDs, and private host paths are omitted from public documentation, fixtures, and repositories.
- Automatic photo capture is strictly disabled to protect mechanical shutter curtains.
- No firmware flashing or service-mode writes are performed during status monitoring or app installations.
