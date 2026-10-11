# Camera support and verification

Sony Open PMCA distinguishes reference eligibility, runtime protocol capability, application prerequisites and physical verification. Version 1.1.0 does not guarantee that every feature or APK works on every PMCA body.

## Evidence and runtime gates

| Check | Source | Meaning |
|---|---|---|
| Model eligibility | [fwtool.py devices.yml, revision cdba742b](https://github.com/ma1co/fwtool.py/blob/cdba742b73eed5981480c326aeb30033aabf0223/devices.yml) | An `apps` entry identifies a PMCA subsystem. Its value is not an Android API level or installed-app result. |
| Normal Sony MTP support | DeviceInfo operation codes for Sony extension read/write/reconnect | Read-only communication and the expected vendor command path can be checked independently of model eligibility. |
| Sony installer mode | Required SEN_PRXY_MSG proxy operations | Actual installer protocol detection can confirm an otherwise unlisted model in that mode. |
| APK preflight | Manifest package, declared minimum API 1-10 and signing certificate parsing | Rejects malformed/incompatible-baseline files. It is not a publisher security audit or proof of camera-specific app behavior. |
| Physical installation | Original α7 plus RecipeLab | The selected installation completed on the tested ILCE-7. Other models/platforms remain unverified on hardware. |

Known app-ineligible bodies cannot be switched into the installer simply because they respond to USB. Read-only information remains available when communication succeeds. The GUI explains when installation is blocked or the model is unconfirmed. Cached vendor serial, firmware and photo-counter data are reused only for a matched camera identity.

The shared model reference contains the complete pinned upstream dataset, including camcorder/action-camera records. The README table focuses on its 25 still-camera model codes. HX60V/HX90V/HX400V use their normalized upstream HX family profiles in `camera_support.model` for app eligibility. The top-level status `model` retains the device-reported GPS variant code; a shared eligibility profile does not prove GPS application compatibility.

## Image-counter routing

| Implemented model group | Counter layout | Interpretation |
|---|---|---|
| ILCE-7/7R/7S/7M2, ILCE-5000/5100/6000/QX1 | Tag9050a | Non-flash secondary counter at the verified A offset. Flash ambiguity is reported instead of presenting a wrapped value as an exact total. |
| ILCE-7RM2/7SM2/6300/6500 | Tag9050b | Primary exposure counter at the verified B offset. It is not read from A-model offsets. Silent/electronic exposures may not increment this field. |
| NEX, Cyber-shot and other unimplemented layouts | No decoder provided in this release | A clear unsupported-decoder state is not a claim that the camera can never store actuation metadata. |

Routing/offset reference: [ExifTool Sony tag documentation](https://exiftool.org/TagNames/Sony.html) and the Sony.pm model conditions for Tag9050a/b. Automated fixtures are compared with the independent ExifTool reference where available.

The counter is as of an examined image, not a live meter or a guaranteed shutter-replacement history. Reads use bounded MTP partial-object transfers and a disclosed metadata sample. No photo is automatically taken. A missing photo, missing operation, unsupported layout or ambiguous field is returned as such. Live hardware counter verification remains pending.

## Camera applications

Model eligibility alone cannot establish APK compatibility. Keep the maintainer's model/firmware instructions:

| Example | Requirement or evidence limit |
|---|---|
| RecipeLab | Installation was confirmed on the ILCE-7; other bodies need their own app compatibility evidence. |
| BetterManual | Designed around Alpha 5100 control mapping. |
| GPS Downloader | Requires built-in GPS hardware; a non-GPS family variant cannot be inferred to satisfy this. |
| OpenMemories: Launcher | Camcorder/action-camera workflow rather than a universal still-camera launcher. |
| CustomLut | Experimental; maintainer evidence is for A6000. |
| LensCatalog | Read the maintainer's manual-lens/EXIF and stabilization requirements. Lack of one hardware feature is not proof that the entire application is incompatible. |

Do not mark all model/application combinations as tested based on a successful APK download. The durable download evidence is in [appstore-download-validation.json](appstore-download-validation.json); it contains no physical compatibility claim beyond the separately recorded RecipeLab result.
