import contextlib
import inspect
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

repo_root = str(Path(__file__).resolve().parents[1])
if repo_root not in sys.path:
 sys.path.insert(0, repo_root)

from pmca.commands import usb
from tests.apk_fixture import apkFixture


class InstallCallbackTest(unittest.TestCase):
 def setUp(self):
  self.real_apk_bytes = apkFixture(package='com.voxivoid.recipelab', minSdk=10, signed=True)

 def test_local_install_uses_the_supplied_progress_callback(self):
  self.assertIn('statusFunc', inspect.signature(usb.installApp).parameters)
  server = Mock()
  server.server_address = ('127.0.0.1', 4443)
  server.getXpd.return_value = b'fixture xpd'
  server.getResult.return_value = {'deviceinfo': {'name': 'ILCE-7'}}
  progress = Mock()
  install = Mock(return_value=SimpleNamespace(code=0, message='ok'))
  with patch.object(usb, 'LocalMarketServer', return_value=server), \
       patch.object(usb, 'ServerContext', return_value=contextlib.nullcontext(server)), \
       patch.object(usb, 'SonyAppInstallCamera', return_value=Mock()), \
       patch.object(usb.installer, 'install', install), \
       contextlib.redirect_stdout(io.StringIO()):
   usb.installApp(Mock(), statusFunc=progress)
  self.assertIs(install.call_args.args[-1], progress)

 def test_install_app_executes_real_check_apk_validator_on_signed_apk(self):
  """Verify installApp runs the real checkApk validator without mocks and returns camera response."""
  server = Mock()
  server.server_address = ('127.0.0.1', 4443)
  server.getXpd.return_value = b'fixture xpd'
  server.getResult.return_value = {
   'deviceinfo': {'name': 'ILCE-7'},
   'applications': [{'name': 'RecipeLab', 'version': '1.6.2'}],
  }
  progress = Mock()
  install = Mock(return_value=SimpleNamespace(code=0, message='ok'))

  output = io.StringIO()
  with patch.object(usb, 'LocalMarketServer', return_value=server), \
       patch.object(usb, 'ServerContext', return_value=contextlib.nullcontext(server)), \
       patch.object(usb, 'SonyAppInstallCamera', return_value=Mock()), \
       patch.object(usb.installer, 'install', install), \
       contextlib.redirect_stdout(output):
   res = usb.installApp(Mock(), apkFile=io.BytesIO(self.real_apk_bytes), statusFunc=progress)

  self.assertEqual(res['deviceinfo']['name'], 'ILCE-7')
  self.assertEqual(res['applications'][0]['name'], 'RecipeLab')
  self.assertEqual(res['applications'][0]['version'], '1.6.2')
  # Verify checkApk output was generated
  self.assertIn('Package: com.voxivoid.recipelab', output.getvalue())
  # Verify server was given the exact validated APK bytes
  server.setApk.assert_called_once_with(self.real_apk_bytes)

 def test_install_app_rejects_corrupted_apk_before_server_or_installer(self):
  """Verify installApp rejects corrupt APK at checkApk boundary before starting task."""
  server = Mock()
  install = Mock()
  with patch.object(usb, 'LocalMarketServer', return_value=server), \
       patch.object(usb, 'ServerContext', return_value=contextlib.nullcontext(server)), \
       patch.object(usb.installer, 'install', install):
   with self.assertRaises(ValueError) as ctx:
    usb.installApp(Mock(), apkFile=io.BytesIO(b'invalid_not_a_zip'))
   self.assertIn('Invalid APK file', str(ctx.exception))
   server.setApk.assert_not_called()
   install.assert_not_called()


if __name__ == '__main__':
 unittest.main()
