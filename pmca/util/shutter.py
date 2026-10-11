"""Sony Alpha Shutter Count parser and MTP/file reader for ILCE-7 cameras.

Implements the verified Sony Tag 0x9050 (Tag9050a) Little-Endian decipher algorithm:
    b = pow(c, 55, 249) if c < 249 else c
Offsets within deciphered Tag9050a:
    0x31 (49 dec): FlashStatus (bit 0 == 1 means flash fired)
    0x32 (50 dec): ShutterCount (24-bit LE, wraps modulo 65,536 on A7/A7R)
    0x4c (76 dec): ShutterCount2 (24-bit LE, valid lifetime count when FlashStatus & 1 == 0)
    0x51 (81 dec): SonyDateTime2 (6 bytes: year-2000, month, day, hour, min, sec)
"""
from datetime import datetime
import json
import os
import shutil
import struct
import subprocess

from ..usb import MtpException

# Supported camera models routing to Tag9050a layout
TAG9050A_MODELS = frozenset([
    'ILCE-7', 'ILCE-7R', 'ILCE-7S', 'ILCE-7M2',
    'ILCE-6000', 'ILCE-5000', 'ILCE-5100', 'ILCE-QX1'
])

# 256-byte substitution decipher table: b = pow(c, 55, 249) if c < 249 else c
_DECIPHER_TABLE = bytes(pow(c, 55, 249) if c < 249 else c for c in range(256))


def decipher_sony_payload(data: bytes) -> bytes:
 """Apply Sony Tag 0x9050 substitution cipher to raw ciphertext bytes."""
 if not isinstance(data, (bytes, bytearray)):
  raise TypeError("Data must be bytes or bytearray")
 return bytes(data).translate(_DECIPHER_TABLE)


def parse_sony_tag9050(decrypted: bytes, model='ILCE-7'):
 """Parse decrypted Tag9050a bytes into verified shutter count and metadata."""
 if model and model not in TAG9050A_MODELS:
  raise ValueError("Model %s does not use Tag9050a layout (requires Tag9050b/c parser)" % model)

 if len(decrypted) < 80:
  raise ValueError("Decrypted Tag9050 payload too short (must be at least 80 bytes, got %d)" % len(decrypted))

 flash_status = decrypted[0x31]
 flash_fired = bool(flash_status & 1)

 # 24-bit LE integers
 shutter_count_raw = decrypted[0x32] | (decrypted[0x33] << 8) | (decrypted[0x34] << 16)
 shutter_count2 = decrypted[0x4c] | (decrypted[0x4d] << 8) | (decrypted[0x4e] << 16)

 # Parse timestamp if present (0x51..0x56) using calendar validation
 date_str = None
 if len(decrypted) >= 87:
  date_bytes = decrypted[0x51:0x57]
  if len(date_bytes) == 6:
   y, m, d, hh, mm, ss = date_bytes
   try:
    dt = datetime(2000 + y, m, d, hh, mm, ss)
    date_str = dt.strftime("%Y:%m:%d %H:%M:%S")
   except ValueError:
    pass

 if not flash_fired:
  # Non-flash image: ShutterCount2 is the true lifetime 24-bit mechanical actuation count
  shutter_count = shutter_count2
  shutter_count_modulo = None
  ambiguous = False
  warning = None
 else:
  # Flash fired: ShutterCount2 is suppressed/invalid. Fallback wraps modulo 65,536 on ILCE-7
  shutter_count = None
  shutter_count_modulo = shutter_count_raw % 65536
  ambiguous = True
  warning = "Image captured with flash; ShutterCount2 suppressed. 16-bit counter shows %d (modulo 65,536 on ILCE-7)" % shutter_count_modulo

 return {
  'shutter_count': shutter_count,
  'shutter_count2': shutter_count2,
  'shutter_count_raw': shutter_count_raw,
  'shutter_count_modulo': shutter_count_modulo,
  'flash_status': flash_status,
  'flash_fired': flash_fired,
  'ambiguous': ambiguous,
  'warning': warning,
  'date': date_str,
 }


def _parse_tiff_directory(data: bytes, tiff_start: int, ifd_offset: int, is_le: bool, max_bound: int):
 """Parse a TIFF IFD directory returning tag dictionary: {tag: (type, count, val_or_offset)}."""
 fmt = '<' if is_le else '>'
 if ifd_offset + 2 > max_bound:
  return {}, 0
 num_entries = struct.unpack_from(fmt + 'H', data, ifd_offset)[0]
 pos = ifd_offset + 2
 entries = {}
 for _ in range(num_entries):
  if pos + 12 > max_bound:
   break
  tag, typ, count, val_offset = struct.unpack_from(fmt + 'HHII', data, pos)
  entries[tag] = (typ, count, val_offset)
  pos += 12
 next_ifd = struct.unpack_from(fmt + 'I', data, pos)[0] if pos + 4 <= max_bound else 0
 return entries, next_ifd


def extract_tag9050_from_image_bytes(image_bytes: bytes, model='ILCE-7'):
 """Pure Python extraction and parsing of Tag9050 strictly bound inside JPEG APP1 or TIFF/ARW header."""
 if not image_bytes or len(image_bytes) < 64:
  raise ValueError("Image bytes too short")

 tiff_start = None
 tiff_bound = len(image_bytes)
 is_le = True

 if image_bytes.startswith(b'\xff\xd8'):
  # Scan JPEG markers strictly bound to APP1
  pos = 2
  while pos + 4 <= len(image_bytes):
   if image_bytes[pos] != 0xff:
    break
   # Skip fill bytes 0xFF
   while pos < len(image_bytes) and image_bytes[pos] == 0xff:
    pos += 1
   if pos >= len(image_bytes):
    break
   marker = image_bytes[pos]
   pos += 1
   if marker in (0xd9, 0xda): # EOI or SOS: stop parsing
    break
   if pos + 2 > len(image_bytes):
    break
   length = (image_bytes[pos] << 8) | image_bytes[pos + 1]
   if marker == 0xe1 and length >= 8: # APP1
    if image_bytes[pos + 2:pos + 8] == b'Exif\0\0':
     tiff_start = pos + 8
     tiff_bound = min(len(image_bytes), pos + 2 + length)
     break
   pos += 2 + length
 elif image_bytes.startswith(b'II*\0') or image_bytes.startswith(b'MM\0*'):
  tiff_start = 0
  tiff_bound = len(image_bytes)

 if tiff_start is None:
  raise ValueError("No Exif/TIFF header found in image bytes")

 if tiff_start + 8 > tiff_bound:
  raise ValueError("Truncated TIFF header")

 byte_order = image_bytes[tiff_start:tiff_start + 2]
 if byte_order == b'II':
  is_le = True
 elif byte_order == b'MM':
  is_le = False
 else:
  raise ValueError("Invalid TIFF byte order: %r" % byte_order)

 fmt = '<' if is_le else '>'
 ifd0_offset = struct.unpack_from(fmt + 'I', image_bytes, tiff_start + 4)[0]

 # Parse IFD0 strictly within tiff_bound
 ifd0_entries, _ = _parse_tiff_directory(image_bytes, tiff_start, tiff_start + ifd0_offset, is_le, tiff_bound)

 # Check Make (0x010f)
 if 0x010f in ifd0_entries:
  mk_typ, mk_cnt, mk_off = ifd0_entries[0x010f]
  if tiff_start + mk_off + mk_cnt <= tiff_bound:
   make_str = image_bytes[tiff_start + mk_off:tiff_start + mk_off + mk_cnt].decode('ascii', errors='ignore').rstrip('\0').strip()
   if make_str and not make_str.upper().startswith('SONY'):
    raise ValueError("Non-Sony image make: %s" % make_str)

 # Check Model (0x0110)
 if 0x0110 in ifd0_entries:
  m_typ, m_cnt, m_off = ifd0_entries[0x0110]
  if tiff_start + m_off + m_cnt <= tiff_bound:
   parsed_model = image_bytes[tiff_start + m_off:tiff_start + m_off + m_cnt].decode('ascii', errors='ignore').rstrip('\0').strip()
   if parsed_model:
    if parsed_model not in TAG9050A_MODELS:
     raise ValueError("Camera model %s does not use Tag9050a layout (requires Tag9050b/c)" % parsed_model)
    model = parsed_model

 # Tag 0x8769 = ExifIFD
 if 0x8769 not in ifd0_entries:
  raise ValueError("ExifIFD pointer (0x8769) not found in IFD0")
 exif_ifd_offset = ifd0_entries[0x8769][2]

 # Parse ExifIFD
 exif_entries, _ = _parse_tiff_directory(image_bytes, tiff_start, tiff_start + exif_ifd_offset, is_le, tiff_bound)

 # Tag 0x927c = MakerNote
 if 0x927c not in exif_entries:
  raise ValueError("MakerNote pointer (0x927c) not found in ExifIFD")
 mn_typ, mn_count, mn_offset = exif_entries[0x927c]

 mn_start = tiff_start + mn_offset
 if mn_start >= tiff_bound:
  raise ValueError("MakerNote offset outside TIFF boundaries")

 mn_data = image_bytes[mn_start:min(mn_start + mn_count, tiff_bound)]
 if mn_data.startswith(b'SONY DSC \0\0\0') or mn_data.startswith(b'SONY CAM \0\0\0'):
  mn_ifd_offset = mn_start + 12
 else:
  mn_ifd_offset = mn_start

 mn_entries, _ = _parse_tiff_directory(image_bytes, tiff_start, mn_ifd_offset, is_le, tiff_bound)

 # Tag 0x9050 in MakerNote
 if 0x9050 not in mn_entries:
  raise ValueError("Tag 0x9050 not found in Sony MakerNote")

 tag_typ, tag_count, tag_val_offset = mn_entries[0x9050]
 tag_start = tiff_start + tag_val_offset
 if tag_start + tag_count > tiff_bound:
  raise ValueError("Tag 0x9050 payload exceeds TIFF boundary")

 tag_data = image_bytes[tag_start:tag_start + tag_count]
 if len(tag_data) < tag_count:
  raise ValueError("Truncated Tag 0x9050 payload")

 decrypted = decipher_sony_payload(tag_data)
 return parse_sony_tag9050(decrypted, model=model)


def extract_shutter_via_exiftool(file_path: str):
 """Fallback: extract shutter count via system exiftool using JSON output to prevent positional shift."""
 if not os.path.isfile(file_path):
  return None
 exiftool_bin = shutil.which('exiftool') or ('/usr/local/bin/exiftool' if os.path.exists('/usr/local/bin/exiftool') else None)
 if not exiftool_bin:
  return None
 try:
  cmd = [exiftool_bin, '-j', '-n', '-ShutterCount2', '-ShutterCount', '-FlashStatus', '-DateTimeOriginal', file_path]
  out = subprocess.check_output(cmd, timeout=5).decode('utf-8', errors='ignore')
  items = json.loads(out)
  if not items:
   return None
  data = items[0]
  sc2 = data.get('ShutterCount2')
  sc = data.get('ShutterCount')
  flash_status = data.get('FlashStatus', 0)
  date = data.get('DateTimeOriginal')
  flash_fired = bool(int(flash_status) & 1) if flash_status is not None else False

  if not flash_fired and sc2 is not None:
   count = int(sc2)
   modulo_sc = None
   ambiguous = False
   warning = None
  elif sc is not None:
   count = None
   modulo_sc = int(sc) % 65536
   ambiguous = True
   warning = "Image captured with flash; ShutterCount2 suppressed. 16-bit counter shows %d (modulo 65,536 on ILCE-7)" % modulo_sc
  else:
   return None

  return {
   'shutter_count': count,
   'shutter_count2': int(sc2) if sc2 is not None else None,
   'shutter_count_raw': int(sc) if sc is not None else None,
   'shutter_count_modulo': modulo_sc,
   'flash_status': int(flash_status) if flash_status is not None else 0,
   'flash_fired': flash_fired,
   'ambiguous': ambiguous,
   'warning': warning,
   'date': date,
  }
 except Exception:
  pass
 return None


def query_mtp_camera_shutter_count(mtp_device):
 """Query genuine mechanical shutter count from camera over read-only MTP header extraction.
 Verifies PTP capabilities and inspects a bounded ObjectInfo sample by capture date,
 and prioritizes non-flash images to avoid modulo 65,536 ambiguity.
 """
 try:
  dev_info = mtp_device.getDeviceInfo()
  ops = getattr(dev_info, 'operationsSupported', set())
  if 0x1007 not in ops:
   return {
    'available': False,
    'value': None,
    'reason': 'Camera does not support PTP GetObjectHandles (0x1007).',
   }
  if 0x1008 not in ops:
   return {
    'available': False,
    'value': None,
    'reason': 'Camera does not support PTP GetObjectInfo (0x1008).',
   }
  if 0x101b not in ops:
   return {
    'available': False,
    'value': None,
    'reason': 'Camera does not support bounded PTP GetPartialObject (0x101b).',
   }

  handles = []
  for fmt in [0x3801, 0xb881, 0x0000]:
   try:
    handles = mtp_device.getObjectHandles(formatCode=fmt, parentHandle=0x00000000)
    if handles:
     break
   except MtpException as e:
    # Explicit MTP transport or malformed response error
    return {
     'available': False,
     'value': None,
     'reason': 'MTP communication error querying object handles: %s' % str(e),
    }
   except Exception:
    pass

  if not handles:
   return {
    'available': False,
    'value': None,
    'reason': 'No captured image found on camera storage. Take at least one photo on SD card to read shutter count.',
   }

  # Build chronology from ObjectInfo (PTP 0x1008) across recent candidate handles (budget: up to 10)
  candidates = []
  for h in handles[-10:]:
   try:
    obj_info = mtp_device.getObjectInfo(h)
    capture_date = getattr(obj_info, 'captureDate', '') or ''
    filename = getattr(obj_info, 'filename', '') or ''
    candidates.append((capture_date, filename, h))
   except Exception:
    candidates.append(('', '', h))

  # Sort chronologically by captureDate and filename
  candidates.sort(key=lambda x: (x[0], x[1], x[2]))

  fallback_flash_info = None
  fallback_handle = None
  fallback_date = None
  fallback_filename = None
  coverage_limited = len(handles) > len(candidates)

  # Inspect candidate headers in reverse chronological order
  for cap_date, fname, handle in reversed(candidates):
   try:
    header_bytes = mtp_device.getPartialObject(handle, offset=0, maxBytes=65536)
    if not header_bytes:
     continue
    info = extract_tag9050_from_image_bytes(header_bytes, model=getattr(dev_info, 'model', 'ILCE-7'))
    effective_date = info.get('date') or (cap_date if len(cap_date) >= 15 else None)

    if not info.get('flash_fired'):
     # The decoded count is as of this examined non-flash photo, not a live counter.
     return {
      'available': True,
      'value': info['shutter_count'],
      'shutter_count2': info['shutter_count2'],
      'shutter_count_raw': info['shutter_count_raw'],
      'ambiguous': False,
      'flash_fired': False,
      'warning': None,
      'date': effective_date,
      'source': fname or 'Camera image handle %d' % handle,
      'examined_count': len(candidates),
      'coverage_limited': coverage_limited,
      'provenance': 'Examined image %s (handle %d%s; metadata sample %d of %d images)' % (
       fname or 'on camera storage', handle,
       (', captured ' + effective_date) if effective_date else '', len(candidates), len(handles)),
      'reason': None,
     }
    elif fallback_flash_info is None:
     fallback_flash_info = info
     fallback_handle = handle
     fallback_date = effective_date
     fallback_filename = fname
   except Exception:
    pass

  if fallback_flash_info is not None:
   # All recent candidates used flash: ShutterCount2 is suppressed
   return {
    'available': False,
    'value': None,
    'shutter_count_modulo': fallback_flash_info.get('shutter_count_modulo'),
    'shutter_count2': None,
    'shutter_count_raw': fallback_flash_info.get('shutter_count_raw'),
    'ambiguous': True,
    'flash_fired': True,
    'warning': fallback_flash_info.get('warning'),
    'date': fallback_date,
    'source': fallback_filename or 'Camera image handle %d' % fallback_handle,
    'examined_count': len(candidates),
    'coverage_limited': coverage_limited,
    'provenance': 'Examined image %s (handle %d, captured with flash; metadata sample %d of %d images)' % (
     fallback_filename or 'on camera storage', fallback_handle, len(candidates), len(handles)),
    'reason': 'Examined photos used flash; ShutterCount2 is suppressed. Modulo 16-bit counter shows %d (wrapped modulo 65,536). Take one non-flash photo to read exact lifetime count.' % (fallback_flash_info.get('shutter_count_modulo') or 0),
   }

  return {
   'available': False,
   'value': None,
   'reason': 'Could not extract valid Exif MakerNote header from recent images on storage.',
  }

 except MtpException as e:
  return {
   'available': False,
   'value': None,
   'reason': 'MTP communication error: %s' % str(e),
  }
 except Exception as e:
  return {
   'available': False,
   'value': None,
   'reason': 'Shutter count query error: %s' % str(e),
  }
