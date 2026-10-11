"""Final regressions for honest bounded photo coverage and release-cache compatibility."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from pmca.appstore.catalog import loadCatalog
from pmca.util.shutter import query_mtp_camera_shutter_count
from tests.test_shutter_counter import make_synthetic_sony_tiff


class FinalBackendContractTest(unittest.TestCase):
 def test_bounded_image_sample_exposes_coverage_and_source_filename(self):
  class Device:
   def getDeviceInfo(self):
    return SimpleNamespace(model='ILCE-7', operationsSupported={0x1007, 0x1008, 0x101b})
   def getObjectHandles(self, **kwargs):
    return list(range(11))
   def getObjectInfo(self, handle):
    return SimpleNamespace(filename='DSC%05d.JPG' % handle, captureDate='20261011T080000', formatCode=0x3801)
   def getPartialObject(self, handle, **kwargs):
    return make_synthetic_sony_tiff(70000, flash_fired=False)
  result = query_mtp_camera_shutter_count(Device())
  self.assertTrue(result['available'])
  self.assertEqual(result['value'], 70000)
  self.assertTrue(result.get('coverage_limited'), 'An arbitrary subset must not be represented as the newest image on all storage')
  self.assertEqual(result.get('examined_count'), 10)
  self.assertIn('DSC00010.JPG', result['provenance'])
  self.assertNotIn('Latest image on camera storage', result['provenance'])

 def test_fileserver_cached_release_is_not_rejected_for_containing_0_2(self):
  with TemporaryDirectory() as directory:
   path = Path(directory) / 'cache.json'
   expected = 'https://github.com/schnatterer/pmcaFilesystemServer/releases/download/0.2.1/pmcaFilesystemServer-0.2.1.apk'
   path.write_text(json.dumps({'apps': {'info.schnatterer.pmcaFilesystemServer': {
    'package': 'info.schnatterer.pmcaFilesystemServer', 'version': '0.2.1', 'url': expected}}}))
   catalog = loadCatalog(cachePath=str(path))
   self.assertEqual(catalog['info.schnatterer.pmcaFilesystemServer']['url'], expected)


if __name__ == '__main__':
 unittest.main()
