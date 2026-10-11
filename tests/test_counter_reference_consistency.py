"""Independent model-B field selection fixtures and optional primary-reference checks."""
import json
from pathlib import Path
import shutil
import struct
import subprocess
from tempfile import TemporaryDirectory
import unittest

from pmca.util.shutter import extract_tag9050_from_image_bytes, parse_sony_tag9050


MODELS_B = ('ILCE-7RM2', 'ILCE-7SM2', 'ILCE-6300', 'ILCE-6500')


def model_b_payload(flash=False):
 data = bytearray(160)
 data[0x31] = 129  # Deliberate conflicting generation-A flash flag.
 data[0x32:0x35] = (1234).to_bytes(3, 'little')
 data[0x4c:0x4f] = (4321).to_bytes(3, 'little')
 data[0x39] = 129 if flash else 128
 data[0x3a:0x3d] = (70000).to_bytes(3, 'little')
 data[0x58:0x5b] = (69997).to_bytes(3, 'little')
 data[0x61:0x63] = bytes((12, 34))
 return bytes(data)


def sony_tiff(model, flash=False):
 # TIFF pointers are calculated independently, not through parser helpers.
 make = b'SONY\0'
 name = model.encode('ascii') + b'\0'
 make_offset = 50
 model_offset = make_offset + len(make)
 exif_offset = model_offset + len(name)
 maker_offset = exif_offset + 18
 payload_offset = maker_offset + 30
 payload = model_b_payload(flash)
 encrypted = bytes((value ** 3) % 249 if value < 249 else value for value in payload)
 result = bytearray(b'II*\0' + struct.pack('<I', 8))
 result += struct.pack('<H', 3)
 result += struct.pack('<HHII', 0x010f, 2, len(make), make_offset)
 result += struct.pack('<HHII', 0x0110, 2, len(name), model_offset)
 result += struct.pack('<HHII', 0x8769, 4, 1, exif_offset)
 result += struct.pack('<I', 0)
 result += make + name
 result += struct.pack('<H', 1) + struct.pack('<HHII', 0x927c, 7, 30 + len(payload), maker_offset) + struct.pack('<I', 0)
 result += b'SONY DSC \0\0\0' + struct.pack('<H', 1)
 result += struct.pack('<HHII', 0x9050, 7, len(payload), payload_offset) + struct.pack('<I', 0)
 result += encrypted
 return bytes(result)


class CounterReferenceConsistencyTest(unittest.TestCase):
 def test_primary_b_counter_does_not_silently_use_secondary_or_a_offsets(self):
  for model in MODELS_B:
   for flash in (False, True):
    with self.subTest(model=model, flash=flash):
     result = parse_sony_tag9050(model_b_payload(flash), model=model)
     self.assertEqual(result['shutter_count'], 70000)
     self.assertEqual(result['shutter_count_raw'], 70000)
     self.assertEqual(result['shutter_count2'], None if flash else 69997)
     self.assertEqual(result['layout'], 'b')
     self.assertEqual(result['flash_fired'], flash)
     self.assertIsNone(result['shutter_count_modulo'])
     self.assertIsNone(result['date'])

 def test_public_image_extractor_preserves_independent_b_fixture_fields(self):
  for model in MODELS_B:
   with self.subTest(model=model):
    result = extract_tag9050_from_image_bytes(sony_tiff(model))
    self.assertEqual(result['model'], model)
    self.assertEqual(result['shutter_count'], 70000)
    self.assertEqual(result['shutter_count2'], 69997)

 def test_direct_exiftool_json_matches_independent_fields_without_production_fallback(self):
  exiftool = shutil.which('exiftool')
  if not exiftool:
   self.skipTest('Optional independent ExifTool reference is not installed')
  with TemporaryDirectory() as directory:
   for model in MODELS_B:
    for flash in (False, True):
     with self.subTest(model=model, flash=flash):
      path = Path(directory) / ('%s-%s.tif' % (model, flash))
      path.write_bytes(sony_tiff(model, flash))
      reference = json.loads(subprocess.check_output([
       exiftool, '-j', '-n', '-Model', '-FlashStatus', '-ShutterCount', '-ShutterCount2', str(path)
      ], timeout=10))[0]
      self.assertEqual(reference['Model'], model)
      self.assertEqual(reference['ShutterCount'], 70000)
      self.assertEqual(reference.get('ShutterCount2'), None if flash else 69997)
      self.assertEqual(bool(reference['FlashStatus'] & 1), flash)


if __name__ == '__main__':
 unittest.main()
