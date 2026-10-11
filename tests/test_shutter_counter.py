"""Unit tests for Sony Alpha shutter counter extraction, deciphering, and MTP integration."""
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
    _DECIPHER_TABLE,
)


def encipher(data: bytes) -> bytes:
 """Encipher helper matching Sony $c = b^3 (mod 249) rule."""
 return bytes(pow(b, 3, 249) if b < 249 else b for b in data)


def make_synthetic_tag9050(count: int, flash_fired: bool = False, date_tuple=(26, 10, 11, 8, 30, 0)) -> bytes:
 payload = bytearray(944)
 payload[0x31] = 1 if flash_fired else 0
 sc_raw = count % 65536 if flash_fired else count
 payload[0x32] = sc_raw & 0xff
 payload[0x33] = (sc_raw >> 8) & 0xff
 payload[0x34] = (sc_raw >> 16) & 0xff

 payload[0x4c] = count & 0xff
 payload[0x4d] = (count >> 8) & 0xff
 payload[0x4e] = (count >> 16) & 0xff

 if date_tuple:
  payload[0x51:0x57] = bytes(date_tuple)
 return bytes(payload)


def make_synthetic_sony_tiff(count: int, flash_fired: bool = False, model='ILCE-7') -> bytes:
 plain_payload = make_synthetic_tag9050(count, flash_fired)
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


class ShutterCounterTest(unittest.TestCase):
 def test_decipher_formula_correctness(self):
  """Verify decipher table b = c^55 (mod 249) inverts c = b^3 (mod 249) for all byte values."""
  for b in range(249):
   c = pow(b, 3, 249)
   recovered = pow(c, 55, 249)
   self.assertEqual(recovered, b)
  for b in range(249, 256):
   self.assertEqual(_DECIPHER_TABLE[b], b)

 def test_parse_sony_tag9050_non_flash(self):
  """Verify non-flash image returns ShutterCount2 as exact lifetime mechanical actuations."""
  payload = make_synthetic_tag9050(43210, flash_fired=False)
  res = parse_sony_tag9050(payload)
  self.assertEqual(res['shutter_count'], 43210)
  self.assertEqual(res['shutter_count2'], 43210)
  self.assertFalse(res['ambiguous'])
  self.assertFalse(res['flash_fired'])
  self.assertIsNone(res['warning'])
  self.assertEqual(res['date'], "2026:10:11 08:30:00")

 def test_parse_sony_tag9050_count_over_65536_without_flash(self):
  """Verify rollover beyond 16-bit: count=70000 correctly parsed from 24-bit ShutterCount2."""
  payload = make_synthetic_tag9050(70000, flash_fired=False)
  res = parse_sony_tag9050(payload)
  self.assertEqual(res['shutter_count'], 70000)
  self.assertEqual(res['shutter_count2'], 70000)
  self.assertFalse(res['ambiguous'])

 def test_parse_sony_tag9050_flash_fired_reports_ambiguous_and_no_exact_value(self):
  """Verify flash image flags ambiguity, suppresses exact value, and warns of modulo 65,536 wrapping."""
  payload = make_synthetic_tag9050(70000, flash_fired=True)
  res = parse_sony_tag9050(payload)
  self.assertIsNone(res['shutter_count'])
  self.assertEqual(res['shutter_count_modulo'], 4464)
  self.assertTrue(res['ambiguous'])
  self.assertTrue(res['flash_fired'])
  self.assertIn("modulo 65,536", res['warning'])

 def test_parse_sony_tag9050_rejects_unsupported_models(self):
  """Verify parse_sony_tag9050 rejects models requiring Tag9050b/c layouts."""
  payload = make_synthetic_tag9050(43210, flash_fired=False)
  with self.assertRaises(ValueError) as ctx:
   parse_sony_tag9050(payload, model='ILCE-7M3')
  self.assertIn('Tag9050b/c', str(ctx.exception))

 def test_parse_sony_tag9050_validates_date_bounds(self):
  """Verify invalid date bytes are rejected without emitting malformed calendar strings."""
  # year = 216 (>99), month = 20 (>12)
  payload = make_synthetic_tag9050(43210, flash_fired=False, date_tuple=(216, 20, 196, 40, 70, 90))
  res = parse_sony_tag9050(payload)
  self.assertIsNone(res['date'])

 def test_extract_tag9050_from_synthetic_tiff(self):
  """Verify pure Python extraction matches ExifTool 13.45 on synthetic TIFF fixture."""
  tiff_data = make_synthetic_sony_tiff(43210, flash_fired=False)
  res = extract_tag9050_from_image_bytes(tiff_data, model='ILCE-7')
  self.assertEqual(res['shutter_count'], 43210)
  self.assertEqual(res['date'], "2026:10:11 08:30:00")

  if os.path.exists('/usr/local/bin/exiftool'):
   with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as f:
    f.write(tiff_data)
    tmp_path = f.name
   try:
    et_info = extract_shutter_via_exiftool(tmp_path)
    self.assertIsNotNone(et_info)
    self.assertEqual(et_info['shutter_count'], 43210)
    self.assertFalse(et_info['flash_fired'])
   finally:
    os.unlink(tmp_path)

 def test_extract_shutter_via_exiftool_flash_handling(self):
  """Verify ExifTool JSON parser correctly marks flash fired and ambiguous without positional shift."""
  if not os.path.exists('/usr/local/bin/exiftool'):
   return
  tiff_data = make_synthetic_sony_tiff(70000, flash_fired=True)
  with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as f:
   f.write(tiff_data)
   tmp_path = f.name
  try:
   et_info = extract_shutter_via_exiftool(tmp_path)
   self.assertIsNotNone(et_info)
   self.assertIsNone(et_info['shutter_count'])
   self.assertEqual(et_info['shutter_count_modulo'], 4464)
   self.assertTrue(et_info['flash_fired'])
   self.assertTrue(et_info['ambiguous'])
  finally:
   os.unlink(tmp_path)

 def test_query_mtp_camera_shutter_count_missing_get_object_info_opcode(self):
  """Verify query when camera firmware lacks 0x1008 reports opcode limitation without bus stall."""
  mock_mtp = Mock()
  mock_info = Mock()
  mock_info.operationsSupported = {0x1007, 0x101b} # Missing 0x1008
  mock_mtp.getDeviceInfo.return_value = mock_info

  res = query_mtp_camera_shutter_count(mock_mtp)
  self.assertFalse(res['available'])
  self.assertIn("0x1008", res['reason'])

 def test_query_mtp_camera_shutter_count_no_images(self):
  """Verify query on camera storage with 0 handles returns available=False with user guidance."""
  mock_mtp = Mock()
  mock_info = Mock()
  mock_info.operationsSupported = {0x1007, 0x1008, 0x101b}
  mock_mtp.getDeviceInfo.return_value = mock_info
  mock_mtp.getObjectHandles.return_value = []

  res = query_mtp_camera_shutter_count(mock_mtp)
  self.assertFalse(res['available'])
  self.assertIsNone(res['value'])
  self.assertIn("Take at least one photo", res['reason'])

 def test_query_mtp_camera_shutter_count_prioritizes_non_flash_over_flash(self):
  """Verify MTP query scans recent handles and selects recent non-flash image over newer flash photo."""
  from pmca.usb import PtpObjectInfo
  mock_mtp = Mock()
  mock_info = Mock()
  mock_info.operationsSupported = {0x1007, 0x1008, 0x101b}
  mock_info.model = 'ILCE-7'
  mock_mtp.getDeviceInfo.return_value = mock_info
  mock_mtp.getObjectHandles.return_value = [0x1001, 0x1002]
  mock_mtp.getObjectInfo.side_effect = lambda h: PtpObjectInfo(1, 0x3801, 1000, 'DSC0%d.JPG' % h, '20261011T08%04d' % (h % 10000), '20261011T08%04d' % (h % 10000))

  # Handle 1001: non-flash count=55432
  # Handle 1002: flash count=55433
  tiff_non_flash = make_synthetic_sony_tiff(55432, flash_fired=False)
  tiff_flash = make_synthetic_sony_tiff(55433, flash_fired=True)

  def mock_partial(handle, offset=0, maxBytes=65536):
   if handle == 0x1002:
    return tiff_flash[:65536]
   return tiff_non_flash[:65536]

  mock_mtp.getPartialObject.side_effect = mock_partial

  res = query_mtp_camera_shutter_count(mock_mtp)
  self.assertTrue(res['available'])
  self.assertEqual(res['value'], 55432)
  self.assertFalse(res['flash_fired'])
  self.assertIn("handle 4097", res['provenance'])


if __name__ == '__main__':
 unittest.main()


class ShutterMtpTransportValidationTest(unittest.TestCase):
 def test_get_object_handles_truncated_packet_raises_mtp_exception(self):
  """Verify getObjectHandles raises MtpException when packet has fewer bytes than declared."""
  from pmca.usb import MtpDevice, MtpException
  mock_driver = Mock()
  # Declares 5 handles (expected 4 + 20 = 24 bytes), but only delivers 8 bytes
  mock_driver.sendReadCommand.return_value = (MtpDevice.PTP_RC_OK, b'\x05\x00\x00\x00\x01\x00\x00\x00')
  dev = object.__new__(MtpDevice)
  dev.driver = mock_driver
  with self.assertRaises(MtpException) as ctx:
   dev.getObjectHandles()
  self.assertIn("Malformed GetObjectHandles response", str(ctx.exception))
  self.assertIn("declared 5 handles (24 bytes), received 8 bytes", str(ctx.exception))

 def test_get_object_handles_under_4_bytes_raises_mtp_exception(self):
  """Verify getObjectHandles raises MtpException when packet is under 4 bytes."""
  from pmca.usb import MtpDevice, MtpException
  mock_driver = Mock()
  mock_driver.sendReadCommand.return_value = (MtpDevice.PTP_RC_OK, b'\x01\x00')
  dev = object.__new__(MtpDevice)
  dev.driver = mock_driver
  with self.assertRaises(MtpException) as ctx:
   dev.getObjectHandles()
  self.assertIn("Truncated GetObjectHandles response", str(ctx.exception))

 def test_parse_object_info_truncated_raises_mtp_exception(self):
  """Verify _parseObjectInfo raises MtpException when dataset is under 52 bytes."""
  from pmca.usb import MtpDevice, MtpException
  dev = object.__new__(MtpDevice)
  with self.assertRaises(MtpException) as ctx:
   dev._parseObjectInfo(b'\x00' * 30)
  self.assertIn("dataset shorter than 52 bytes", str(ctx.exception))

 def test_query_mtp_shutter_reports_transport_error_without_misleading_no_photo(self):
  """Verify transport error reports actual error reason rather than claiming no photo."""
  from pmca.usb import MtpException
  mock_mtp = Mock()
  mock_info = Mock()
  mock_info.operationsSupported = {0x1007, 0x1008, 0x101b}
  mock_mtp.getDeviceInfo.return_value = mock_info
  mock_mtp.getObjectHandles.side_effect = MtpException("Malformed GetObjectHandles response: declared 10 handles")

  res = query_mtp_camera_shutter_count(mock_mtp)
  self.assertFalse(res['available'])
  self.assertIn("MTP communication error", res['reason'])
  self.assertNotIn("Take at least one photo", res['reason'])
