import contextlib
import inspect
import io
import os
from pathlib import Path
import plistlib
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

repo_root = str(Path(__file__).resolve().parents[1])
if repo_root not in sys.path:
 sys.path.insert(0, repo_root)

from pmca.commands import usb
from tests.apk_fixture import apkFixture


class CameraResultTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.valid_apk_bytes = apkFixture(package='com.voxivoid.recipelab', minSdk=10, signed=True)

 def test_info_returns_real_properties_without_changing_console_output(self):
  device = object.__new__(usb.SonyMscExtCmdDevice)
  camera = Mock()
  import plistlib
  plist_sample = plistlib.dumps({'FirmwareVersion': '3.20'})
  camera.getCameraInfo.return_value = SimpleNamespace(modelName='ILCE-7', modelCode='test-code', serial='test-serial', plist=plist_sample)
  camera.getLensInfo.side_effect = usb.InvalidCommandException()
  camera.getGpsData.side_effect = usb.InvalidCommandException()
  updater = Mock()
  updater.getFirmwareVersion.return_value = ('3.20', '9.99')
  output = io.StringIO()
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(None)), \
       patch.object(usb, 'getDevice', return_value=device), \
       patch.object(usb, 'SonyExtCmdCamera', return_value=camera), \
       patch.object(usb, 'SonyUpdaterCamera', return_value=updater), \
       contextlib.redirect_stdout(output):
   result = usb.infoCommand('libusb')
  self.assertEqual(result, {'Model': 'ILCE-7', 'USB mode': 'Mass Storage', 'Product code': 'test-code', 'Serial number': 'test-serial', 'Firmware version': '3.20'})
  self.assertIn('ILCE-7', output.getvalue())

 def test_install_preflights_valid_apk_and_returns_server_result(self):
  """Verify that valid signed APK passes checkApk preflight and returns install result."""
  device = object.__new__(usb.SonyMtpAppInstallDevice)
  result = {'deviceinfo': {'name': 'ILCE-7'}}
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(None)), \
       patch.object(usb, 'getDevice', return_value=device), \
       patch.object(usb, 'installApp', return_value=result) as mock_install:
   self.assertEqual(usb.installCommand('libusb', io.BytesIO(self.valid_apk_bytes)), result)
   self.assertTrue(mock_install.called)

 def test_install_preflight_rejects_corrupted_apk_before_mode_switch(self):
  """P0 Regression: Invalid APK must raise ValueError before touching camera or switching modes."""
  device = object.__new__(usb.SonyMtpExtCmdDevice)
  mock_camera = Mock()
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(None)), \
       patch.object(usb, 'getDevice', return_value=device), \
       patch.object(usb, 'SonyExtCmdCamera', return_value=mock_camera):
   with self.assertRaises(ValueError) as ctx:
    usb.installCommand('libusb', io.BytesIO(b'corrupted_invalid_apk_data'))
   self.assertIn('Invalid APK file', str(ctx.exception))
   mock_camera.switchToAppInstaller.assert_not_called()

 def test_install_preflight_rejects_unsupported_min_sdk_before_mode_switch(self):
  """P0 Regression: APK with API > 10 must raise ValueError before camera mode switch."""
  device = object.__new__(usb.SonyMtpExtCmdDevice)
  mock_camera = Mock()
  high_sdk_apk = apkFixture(minSdk=14, signed=True)
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(None)), \
       patch.object(usb, 'getDevice', return_value=device), \
       patch.object(usb, 'SonyExtCmdCamera', return_value=mock_camera):
   with self.assertRaises(ValueError) as ctx:
    usb.installCommand('libusb', io.BytesIO(high_sdk_apk))
   self.assertIn('Incompatible Android minSdkVersion', str(ctx.exception))
   mock_camera.switchToAppInstaller.assert_not_called()

 def test_install_preflight_rejects_unsigned_apk_before_mode_switch(self):
  """P0 Regression: Unsigned APK must raise ValueError before camera mode switch."""
  device = object.__new__(usb.SonyMtpExtCmdDevice)
  mock_camera = Mock()
  unsigned_apk = apkFixture(signed=False)
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(None)), \
       patch.object(usb, 'getDevice', return_value=device), \
       patch.object(usb, 'SonyExtCmdCamera', return_value=mock_camera):
   with self.assertRaises(ValueError) as ctx:
    usb.installCommand('libusb', io.BytesIO(unsigned_apk))
   self.assertIn('certificate missing', str(ctx.exception).lower())
   mock_camera.switchToAppInstaller.assert_not_called()

 def test_check_apk_strict_negative_tests(self):
  """Negative tests verifying checkApk enforces package, minSdk (1..10), and signature."""
  # 1. Unsigned APK
  unsigned = apkFixture(signed=False)
  with self.assertRaises(ValueError) as ctx:
   usb.checkApk(io.BytesIO(unsigned))
  self.assertIn('certificate missing or invalid', str(ctx.exception).lower())

  # 2. Too high SDK (>10)
  high_sdk = apkFixture(minSdk=11, signed=True)
  with self.assertRaises(ValueError) as ctx:
   usb.checkApk(io.BytesIO(high_sdk))
  self.assertIn('Incompatible Android minSdkVersion: 11', str(ctx.exception))

  # 3. Too low SDK (<1)
  zero_sdk = apkFixture(minSdk=0, signed=True)
  with self.assertRaises(ValueError) as ctx:
   usb.checkApk(io.BytesIO(zero_sdk))
  self.assertIn('Incompatible Android minSdkVersion: 0', str(ctx.exception))

  # 4. Empty package
  empty_pkg = apkFixture(package='', signed=True)
  with self.assertRaises(ValueError) as ctx:
   usb.checkApk(io.BytesIO(empty_pkg))
  self.assertIn('no package identifier', str(ctx.exception).lower())

 def test_install_forwards_optional_progress_callback(self):
  self.assertIn('statusFunc', inspect.signature(usb.installCommand).parameters)
  device = object.__new__(usb.SonyMtpAppInstallDevice)
  progress = Mock()
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(None)), \
       patch.object(usb, 'getDevice', return_value=device), \
       patch.object(usb, 'installApp') as install:
   usb.installCommand('libusb', io.BytesIO(self.valid_apk_bytes), statusFunc=progress)
  self.assertIs(install.call_args.kwargs['statusFunc'], progress)

 def test_check_apk_validator_on_real_recipelab_package(self):
  """Verify checkApk validator parses package name, version, minSdk, and cert cleanly."""
  output = io.StringIO()
  with contextlib.redirect_stdout(output):
   apk = usb.checkApk(io.BytesIO(self.valid_apk_bytes))
  self.assertEqual(apk.getPackageName(), 'com.voxivoid.recipelab')
  self.assertEqual(apk.getMinSdkVersion(), 10)
  self.assertIn('Package: com.voxivoid.recipelab', output.getvalue())

 def test_check_apk_real_downloaded_recipelab_if_present(self):
  """Optional real downloaded RecipeLab APK check using PMCA_TEST_APK_DIR environment variable."""
  fixture_dir = os.environ.get('PMCA_TEST_APK_DIR')
  if not fixture_dir:
   self.skipTest("Optional real APK fixture test requires PMCA_TEST_APK_DIR environment variable")
  path = Path(fixture_dir) / 'RecipeLab.apk'
  if not path.exists():
   self.skipTest("RecipeLab.apk not found in PMCA_TEST_APK_DIR (%s)" % fixture_dir)
  apk_data = path.read_bytes()
  apk = usb.checkApk(io.BytesIO(apk_data))
  self.assertEqual(apk.getPackageName(), 'com.voxivoid.recipelab')
  self.assertEqual(apk.getVersionName(), '1.6.2')
  self.assertEqual(apk.getMinSdkVersion(), 10)

 def test_get_read_only_camera_info_on_mtp_does_not_call_updater_init(self):
  device = object.__new__(usb.SonyMtpExtCmdDevice)
  device.getDeviceInfo = Mock(return_value=SimpleNamespace(version='3.20'))
  camera = Mock()
  plist_sample = plistlib.dumps({'FirmwareVersion': '3.20'})
  camera.getCameraInfo.return_value = SimpleNamespace(modelName='ILCE-7', modelCode='test-code', serial='test-serial', plist=plist_sample)
  camera.getLensInfo.return_value = SimpleNamespace(model=0x1234, version='1.00')
  camera.getGpsData.side_effect = usb.InvalidCommandException()

  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(None)), \
       patch.object(usb, 'getDevice', return_value=device), \
       patch.object(usb, 'SonyExtCmdCamera', return_value=camera), \
       patch.object(usb, 'SonyUpdaterCamera') as updater_cls:
   result = usb.getReadOnlyCameraInfo('libusb-mtp')
   updater_cls.assert_not_called()
   self.assertEqual(result['Model'], 'ILCE-7')
   self.assertEqual(result['USB mode'], 'MTP')
   self.assertEqual(result['Firmware version'], '3.20')
   self.assertIn('Lens', result)


if __name__ == '__main__':
 unittest.main()


class ConsoleBrandingTest(unittest.TestCase):
 def test_console_cli_branding_uses_sony_a7_pmca(self):
  """Verify pmca-console.py uses Sony A7 PMCA program name and description."""
  import subprocess
  cmd = [sys.executable, str(Path(repo_root) / 'pmca-console.py'), '--help']
  out = subprocess.check_output(cmd).decode('utf-8')
  self.assertIn('Sony A7 PMCA', out)
