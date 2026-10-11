import unittest
from xml.dom import minidom

from pmca.apk import ApkParser


class ApkSdkTest(unittest.TestCase):
 def sdk(self, body, prefix='android'):
  document = minidom.parseString(
   '<manifest xmlns:%s="http://schemas.android.com/apk/res/android" package="com.example.camera">%s</manifest>' % (prefix, body))
  parser = object.__new__(ApkParser)
  parser.getManifest = lambda: document
  return parser.getMinSdkVersion()

 def assertSdk(self, body, expected, prefix='android'):
  try:
   result = self.sdk(body, prefix)
  except (IndexError, ValueError) as error:
   result = error
  self.assertEqual(result, expected)

 def test_absent_uses_sdk_defaults_to_android_api_one(self):
  self.assertSdk('', 1)

 def test_absent_minimum_sdk_defaults_to_android_api_one(self):
  self.assertSdk('<uses-sdk android:targetSdkVersion="10"/>', 1)

 def test_sdk_uses_namespace_instead_of_fixed_prefix(self):
  self.assertSdk('<uses-sdk a:minSdkVersion="30"/>', 30, prefix='a')

 def test_empty_or_malformed_sdk_is_not_an_absent_declaration(self):
  for value in ['', 'invalid']:
   with self.subTest(value=value), self.assertRaises(ValueError):
    self.sdk('<uses-sdk android:minSdkVersion="%s"/>' % value)



 def test_utf8_binary_manifest_parsing(self):
  from tests.apk_fixture import apkFixture
  import io
  data = apkFixture(package='com.github.ma1co.openmemories.tweak', minSdk=10, utf8=True)
  parser = ApkParser(io.BytesIO(data))
  self.assertEqual(parser.getPackageName(), 'com.github.ma1co.openmemories.tweak')
  self.assertEqual(parser.getMinSdkVersion(), 10)

 def test_utf16_binary_manifest_parsing(self):
  from tests.apk_fixture import apkFixture
  import io
  data = apkFixture(package='com.voxivoid.recipelab', minSdk=9, utf8=False)
  parser = ApkParser(io.BytesIO(data))
  self.assertEqual(parser.getPackageName(), 'com.voxivoid.recipelab')
  self.assertEqual(parser.getMinSdkVersion(), 9)

 def test_real_openmemories_tweak_binary_apk(self):
  """Optional real APK fixture test using PMCA_TEST_APK_DIR environment variable."""
  import os
  from pathlib import Path
  fixture_dir = os.environ.get('PMCA_TEST_APK_DIR')
  if not fixture_dir:
   self.skipTest("Optional real APK fixture test requires PMCA_TEST_APK_DIR environment variable")
  apk_path = Path(fixture_dir) / 'OpenMemories-Tweak.apk'
  if not apk_path.exists():
   self.skipTest("Fixture OpenMemories-Tweak.apk not found in PMCA_TEST_APK_DIR (%s)" % fixture_dir)
  with open(apk_path, 'rb') as f:
   parser = ApkParser(f)
   self.assertEqual(parser.getPackageName(), 'com.github.ma1co.openmemories.tweak')
   self.assertEqual(parser.getVersionName(), '0.11')
   self.assertEqual(parser.getMinSdkVersion(), 10)
   self.assertEqual(len(parser.getCert()), 707)

if __name__ == '__main__':
 unittest.main()
