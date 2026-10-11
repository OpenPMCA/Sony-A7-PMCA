"""Unit tests for model-routed Sony shutter count extraction across PMCA Alpha families (Tag9050a and Tag9050b)."""
import json
import shutil
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

repo_root = str(Path(__file__).resolve().parents[1])
if repo_root not in sys.path:
 sys.path.insert(0, repo_root)

from pmca.util.shutter import (
    decipher_sony_payload,
    parse_sony_tag9050,
    extract_tag9050_from_image_bytes,
    extract_shutter_via_exiftool,
    query_mtp_camera_shutter_count,
    TAG9050A_MODELS,
    TAG9050B_MODELS,
    SUPPORTED_MODELS,
)
from tests.test_shutter_counter import make_synthetic_sony_tiff


def encipher(data: bytes) -> bytes:
 """Encipher helper matching Sony $c = b^3 (mod 249) rule."""
 return bytes(pow(b, 3, 249) if b < 249 else b for b in data)


def make_synthetic_tag9050b_payload(sc_3a: int, sc_58: int, flash_fired: bool = False, decoy_a: bool = True) -> bytes:
 """Construct synthetic decrypted Tag9050b payload.
 Offsets:
   0x39: FlashStatus (bit 0 = flash fired)
   0x3a..0x3c: ShutterCount (24-bit LE)
   0x58..0x5a: ShutterCount2 (24-bit LE)
   0x61..0x62: SonyTimeMinSec (minute, second)
 If decoy_a is True, puts distinct decoy bytes in Tag9050a positions (0x32, 0x4c)
 to prove Tag9050b parsing does not read Tag9050a offsets.
 """
 payload = bytearray(944)
 if decoy_a:
  payload[0x31] = 0xee
  payload[0x32] = 0x11
  payload[0x33] = 0x22
  payload[0x34] = 0x33
  payload[0x4c] = 0x44
  payload[0x4d] = 0x55
  payload[0x4e] = 0x66

 payload[0x39] = 1 if flash_fired else 0
 payload[0x3a] = sc_3a & 0xff
 payload[0x3b] = (sc_3a >> 8) & 0xff
 payload[0x3c] = (sc_3a >> 16) & 0xff

 payload[0x58] = sc_58 & 0xff
 payload[0x59] = (sc_58 >> 8) & 0xff
 payload[0x5a] = (sc_58 >> 16) & 0xff

 payload[0x61] = 25 # minute
 payload[0x62] = 42 # second

 return bytes(payload)


def make_synthetic_sony_b_tiff(model: str, sc_3a: int, sc_58: int, flash_fired: bool = False) -> bytes:
 """Construct a synthetic Sony TIFF with Make='SONY', Model=model, and Tag9050b payload."""
 plain_payload = make_synthetic_tag9050b_payload(sc_3a, sc_58, flash_fired, decoy_a=True)
 enc_payload = encipher(plain_payload)

 sony_header = b'SONY DSC \0\0\0' # 12 bytes
 tiff_header = b'II\x2a\x00\x08\x00\x00\x00' # 8 bytes
 make_str = b'SONY\0\0\0\0'
 model_bytes = (model + '\0').encode('ascii')
 if len(model_bytes) % 2 != 0:
  model_bytes += b'\0'
 make_offset = 50
 model_offset = make_offset + len(make_str)
 exif_ifd_offset = model_offset + len(model_bytes)
 makernote_offset = exif_ifd_offset + 24
 ifd_in_mn = makernote_offset + 12
 payload_offset = ifd_in_mn + 18

 ifd0 = struct.pack('<H', 3) + \
        struct.pack('<HHII', 0x010f, 2, len(b'SONY\0'), make_offset) + \
        struct.pack('<HHII', 0x0110, 2, len(model_bytes), model_offset) + \
        struct.pack('<HHII', 0x8769, 4, 1, exif_ifd_offset) + \
        struct.pack('<I', 0)
 ifd0 = ifd0.ljust(make_offset - 8, b'\0')

 exif_ifd = struct.pack('<H', 1) + \
            struct.pack('<HHII', 0x927c, 7, 12 + 18 + len(enc_payload), makernote_offset) + \
            struct.pack('<I', 0)
 exif_ifd = exif_ifd.ljust(makernote_offset - exif_ifd_offset, b'\0')

 makernote_ifd = struct.pack('<H', 1) + \
                 struct.pack('<HHII', 0x9050, 7, len(enc_payload), payload_offset) + \
                 struct.pack('<I', 0)

 return tiff_header + ifd0 + make_str + model_bytes + exif_ifd + sony_header + makernote_ifd + enc_payload


class ShutterModelRoutingTest(unittest.TestCase):
 def test_supported_models_definitions(self):
  """Verify model sets contain exactly the PMCA Alpha families and no modern non-PMCA models."""
  expected_a = {'ILCE-7', 'ILCE-7R', 'ILCE-7S', 'ILCE-7M2', 'ILCE-6000', 'ILCE-5000', 'ILCE-5100', 'ILCE-QX1'}
  expected_b = {'ILCE-7RM2', 'ILCE-7SM2', 'ILCE-6300', 'ILCE-6500'}

  self.assertEqual(TAG9050A_MODELS, expected_a)
  self.assertEqual(TAG9050B_MODELS, expected_b)
  self.assertEqual(SUPPORTED_MODELS, expected_a | expected_b)

  unsupported_modern = ['ILCE-7M3', 'ILCE-7RM3', 'ILCE-7M4', 'ILCE-7RM4', 'ILCE-7SM3', 'ILCE-1', 'ILCE-9', 'ILCE-6400', 'ILCE-6600', 'ILCE-7C', 'ZV-E10']
  for m in unsupported_modern:
   self.assertNotIn(m, SUPPORTED_MODELS)

 def test_parse_sony_tag9050b_distinct_primary_and_secondary_values(self):
  """Verify Tag9050b selects primary 0x3a counter over secondary 0x58 when different values are provided."""
  for m in ['ILCE-7RM2', 'ILCE-7SM2', 'ILCE-6300', 'ILCE-6500']:
   with self.subTest(model=m):
    # Primary = 111111, Secondary = 222222
    payload = make_synthetic_tag9050b_payload(sc_3a=111111, sc_58=222222, flash_fired=False, decoy_a=True)
    res = parse_sony_tag9050(payload, model=m)
    self.assertEqual(res['layout'], 'b')
    self.assertEqual(res['model'], m)
    self.assertEqual(res['shutter_count'], 111111) # Primary 0x3a selected!
    self.assertEqual(res['shutter_count2'], 222222) # Secondary exposed separately
    self.assertEqual(res['shutter_count_raw'], 111111)
    self.assertIsNone(res['shutter_count_modulo'])
    self.assertFalse(res['flash_fired'])
    self.assertFalse(res['ambiguous'])
    self.assertIsNone(res['date'])

 def test_parse_sony_tag9050b_flash_fired_primary_valid_no_rollover(self):
  """Verify Tag9050b flash parsing: primary 0x3a is 24-bit valid (not wrapped at 65536); 0x58 is suppressed."""
  payload = make_synthetic_tag9050b_payload(sc_3a=70000, sc_58=70000, flash_fired=True, decoy_a=True)
  res = parse_sony_tag9050(payload, model='ILCE-6500')

  self.assertEqual(res['layout'], 'b')
  self.assertEqual(res['model'], 'ILCE-6500')
  self.assertEqual(res['shutter_count'], 70000)
  self.assertIsNone(res['shutter_count2'])
  self.assertEqual(res['shutter_count_raw'], 70000)
  self.assertIsNone(res['shutter_count_modulo'])
  self.assertTrue(res['flash_fired'])
  self.assertFalse(res['ambiguous'])
  self.assertIsNotNone(res['warning'])

 def test_parse_sony_tag9050b_payload_too_short(self):
  """Verify payload shorter than required offsets raises ValueError."""
  short_payload = b'\x00' * 80
  with self.assertRaises(ValueError) as ctx:
   parse_sony_tag9050(short_payload, model='ILCE-6300')
  self.assertIn("too short", str(ctx.exception).lower())

 def test_parse_sony_tag9050_unsupported_model_rejected(self):
  """Verify modern non-PMCA bodies, DSC, and NEX are rejected with clear ValueError."""
  payload = make_synthetic_tag9050b_payload(sc_3a=5000, sc_58=5000)
  unsupported = ['ILCE-7M3', 'ILCE-7M4', 'ILCE-1', 'DSC-RX100', 'NEX-5', 'UnknownModel']
  for m in unsupported:
   with self.subTest(model=m):
    with self.assertRaises(ValueError) as ctx:
     parse_sony_tag9050(payload, model=m)
    self.assertIn("not supported", str(ctx.exception).lower())

 def test_extract_tag9050_rejects_photo_camera_model_mismatch(self):
  """Verify extract_tag9050_from_image_bytes rejects photo captured by another camera model."""
  # 1. ILCE-7 photo passed to ILCE-7RM2 query
  tiff_a = make_synthetic_sony_tiff(count=30000, model='ILCE-7')
  with self.assertRaises(ValueError) as ctx:
   extract_tag9050_from_image_bytes(tiff_a, model='ILCE-7RM2')
  self.assertIn("does not match requested camera model", str(ctx.exception))

  # 2. ILCE-7RM2 photo passed to ILCE-7 query
  tiff_b = make_synthetic_sony_b_tiff(model='ILCE-7RM2', sc_3a=40000, sc_58=40000)
  with self.assertRaises(ValueError) as ctx:
   extract_tag9050_from_image_bytes(tiff_b, model='ILCE-7')
  self.assertIn("does not match requested camera model", str(ctx.exception))

 def test_extract_tag9050_from_synthetic_b_tiff_all_four_models(self):
  """Verify pure Python extraction on synthetic TIFF for all 4 Tag9050b models."""
  for m in ['ILCE-7RM2', 'ILCE-7SM2', 'ILCE-6300', 'ILCE-6500']:
   with self.subTest(model=m):
    tiff_data = make_synthetic_sony_b_tiff(model=m, sc_3a=65432, sc_58=65432, flash_fired=False)
    res = extract_tag9050_from_image_bytes(tiff_data)
    self.assertEqual(res['layout'], 'b')
    self.assertEqual(res['model'], m)
    self.assertEqual(res['shutter_count'], 65432)
    self.assertEqual(res['shutter_count2'], 65432)

 def test_exiftool_reference_json_parity_all_four_models(self):
  """Dedicated reference-parity test against external ExifTool binary using shutil.which."""
  exiftool_bin = shutil.which('exiftool') or ('/usr/local/bin/exiftool' if os.path.exists('/usr/local/bin/exiftool') else None)
  if not exiftool_bin:
   self.skipTest("ExifTool reference binary not found in environment for parity assertion")

  for m in ['ILCE-7RM2', 'ILCE-7SM2', 'ILCE-6300', 'ILCE-6500']:
   with self.subTest(model=m):
    tiff_data = make_synthetic_sony_b_tiff(model=m, sc_3a=65432, sc_58=65432, flash_fired=False)
    with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as f:
     f.write(tiff_data)
     tmp_path = f.name
    try:
     cmd = [exiftool_bin, '-j', '-n', '-Model', '-ShutterCount', '-ShutterCount2', '-FlashStatus', tmp_path]
     et_json = json.loads(subprocess.check_output(cmd, timeout=5).decode('utf-8'))[0]
     self.assertEqual(et_json['Model'], m)
     self.assertEqual(et_json['ShutterCount'], 65432)
     self.assertEqual(et_json['ShutterCount2'], 65432)
     self.assertEqual(et_json['FlashStatus'], 0)
    finally:
     os.unlink(tmp_path)

 def test_query_mtp_camera_shutter_count_missing_model_returns_early(self):
  """Verify query_mtp_camera_shutter_count rejects missing/non-string model BEFORE object queries."""
  for invalid_model in [None, '', 12345]:
   with self.subTest(model=invalid_model):
    mock_mtp = Mock()
    mock_info = Mock()
    mock_info.operationsSupported = {0x1007, 0x1008, 0x101b}
    mock_info.model = invalid_model
    mock_mtp.getDeviceInfo.return_value = mock_info

    res = query_mtp_camera_shutter_count(mock_mtp)
    self.assertFalse(res['available'])
    self.assertIn("unavailable or unverified", res['reason'].lower())
    mock_mtp.getObjectHandles.assert_not_called()

 def test_query_mtp_camera_shutter_count_unsupported_model_returns_early(self):
  """Verify query_mtp_camera_shutter_count checks supported models BEFORE issuing object reads."""
  mock_mtp = Mock()
  mock_info = Mock()
  mock_info.operationsSupported = {0x1007, 0x1008, 0x101b}
  mock_info.model = 'ILCE-7M3'
  mock_mtp.getDeviceInfo.return_value = mock_info

  res = query_mtp_camera_shutter_count(mock_mtp)
  self.assertFalse(res['available'])
  self.assertIn("not support", res['reason'].lower())
  mock_mtp.getObjectHandles.assert_not_called()

 def test_query_mtp_camera_shutter_count_skips_mismatched_model_photo(self):
  """Verify query_mtp_camera_shutter_count skips candidate photos taken by another camera model."""
  from pmca.usb import PtpObjectInfo
  mock_mtp = Mock()
  mock_info = Mock()
  mock_info.operationsSupported = {0x1007, 0x1008, 0x101b}
  mock_info.model = 'ILCE-7RM2'
  mock_mtp.getDeviceInfo.return_value = mock_info
  mock_mtp.getObjectHandles.return_value = [0x2001, 0x2002]

  # Handle 2001 is from ILCE-7RM2 (matches connected camera)
  # Handle 2002 (newer) is from ILCE-7 (mismatched!)
  tiff_match = make_synthetic_sony_b_tiff('ILCE-7RM2', sc_3a=154321, sc_58=154321, flash_fired=False)
  tiff_mismatch = make_synthetic_sony_tiff(count=20000, model='ILCE-7')

  def mock_partial(handle, offset=0, maxBytes=65536):
   if handle == 0x2002:
    return tiff_mismatch[:65536]
   return tiff_match[:65536]

  mock_mtp.getObjectInfo.return_value = PtpObjectInfo(1, 0x3801, 5000, 'DSC00042.JPG', '20261011T090000', '20261011T090000')
  mock_mtp.getPartialObject.side_effect = mock_partial

  res = query_mtp_camera_shutter_count(mock_mtp)
  self.assertTrue(res['available'])
  # Should have skipped handle 2002 and selected matching handle 2001!
  self.assertEqual(res['value'], 154321)
  self.assertEqual(res['model'], 'ILCE-7RM2')
  self.assertIn('handle 8193', res['provenance'])

 def test_query_mtp_camera_shutter_count_all_photos_mismatched_model(self):
  """Verify query_mtp_camera_shutter_count reports honest reason when all candidate photos are from another model."""
  from pmca.usb import PtpObjectInfo
  mock_mtp = Mock()
  mock_info = Mock()
  mock_info.operationsSupported = {0x1007, 0x1008, 0x101b}
  mock_info.model = 'ILCE-7RM2'
  mock_mtp.getDeviceInfo.return_value = mock_info
  mock_mtp.getObjectHandles.return_value = [0x2001]

  # Only photo on storage is from ILCE-7
  tiff_mismatch = make_synthetic_sony_tiff(count=20000, model='ILCE-7')
  mock_mtp.getObjectInfo.return_value = PtpObjectInfo(1, 0x3801, 5000, 'DSC00001.JPG', '20261011T090000', '20261011T090000')
  mock_mtp.getPartialObject.return_value = tiff_mismatch[:65536]

  res = query_mtp_camera_shutter_count(mock_mtp)
  self.assertFalse(res['available'])
  self.assertIn("different camera model than connected ILCE-7RM2", res['reason'])

 def test_extract_tag9050_truncation_safety(self):
  """Verify extract_tag9050_from_image_bytes handles truncated payloads safely with clean ValueError."""
  # 1. Under 64 bytes
  with self.assertRaises(ValueError):
   extract_tag9050_from_image_bytes(b'II*\x00\x08\x00\x00\x00\x01\x00')

  # 2. Truncated TIFF header
  with self.assertRaises(ValueError):
   extract_tag9050_from_image_bytes(b'II*\x00' + b'\x00' * 30)

  # 3. Truncated payload exceeding boundary
  valid_tiff = make_synthetic_sony_b_tiff('ILCE-6300', sc_3a=1234, sc_58=1234)
  truncated_tiff = valid_tiff[:len(valid_tiff) - 100]
  with self.assertRaises(ValueError):
   extract_tag9050_from_image_bytes(truncated_tiff)

  # 4. Truncated JPEG stream
  corrupt_jpeg = b'\xff\xd8\xff\xe1\x00\x01' # length < 2 invalid
  with self.assertRaises(ValueError):
   extract_tag9050_from_image_bytes(corrupt_jpeg + b'\x00' * 60)

 def test_extract_tag9050b_date_provenance_and_exif_fallback(self):
  """Verify date provenance correctly identifies MakerNote timestamp vs ExifIFD DateTimeOriginal."""
  # Tag9050a synthetic tiff has MakerNote date
  tiff_a = make_synthetic_sony_tiff(12345, flash_fired=False, model='ILCE-7')
  res_a = extract_tag9050_from_image_bytes(tiff_a)
  self.assertEqual(res_a['date'], "2026:10:11 08:30:00")
  self.assertEqual(res_a['date_source'], 'MakerNote Tag 0x9050 (SonyDateTime2)')

  # Tag9050b synthetic tiff has no MakerNote date; without Exif date it should be None
  tiff_b = make_synthetic_sony_b_tiff('ILCE-7RM2', sc_3a=50000, sc_58=50000)
  res_b = extract_tag9050_from_image_bytes(tiff_b)
  self.assertIsNone(res_b['date'])
  self.assertIsNone(res_b['date_source'])

 def test_extract_shutter_via_exiftool_b_models_flash_and_non_flash(self):
  """Verify extract_shutter_via_exiftool helper parses Tag9050b models under both flash and non-flash."""
  exiftool_bin = shutil.which('exiftool') or ('/usr/local/bin/exiftool' if os.path.exists('/usr/local/bin/exiftool') else None)
  if not exiftool_bin:
   self.skipTest("ExifTool reference binary not found in environment")

  for flash in [False, True]:
   with self.subTest(flash=flash):
    tiff_data = make_synthetic_sony_b_tiff('ILCE-7RM2', sc_3a=88888, sc_58=88888, flash_fired=flash)
    with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as f:
     f.write(tiff_data)
     tmp_path = f.name
    try:
     et_res = extract_shutter_via_exiftool(tmp_path)
     self.assertIsNotNone(et_res)
     self.assertEqual(et_res['layout'], 'b')
     self.assertEqual(et_res['model'], 'ILCE-7RM2')
     self.assertEqual(et_res['shutter_count'], 88888) # 24-bit valid regardless of flash!
     self.assertEqual(et_res['flash_fired'], flash)
     self.assertFalse(et_res['ambiguous'])
     if flash:
      self.assertIsNone(et_res['shutter_count2'])
     else:
      self.assertEqual(et_res['shutter_count2'], 88888)
    finally:
     os.unlink(tmp_path)


if __name__ == '__main__':
 unittest.main()
