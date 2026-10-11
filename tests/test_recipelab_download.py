import importlib
import importlib.util
import io
import json
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError
from zipfile import BadZipFile

from apk_fixture import apkFixture
from pmca.apk import ApkParser


API_URL = 'https://api.github.com/repos/voxivoid/recipe-lab-sony-pmca/releases/latest'
ASSET_URL = 'https://github.com/voxivoid/recipe-lab-sony-pmca/releases/download/v1.2.3/RecipeLab.apk'


def asset(name='RecipeLab.apk', url=ASSET_URL):
 return {'name': name, 'browser_download_url': url}


def response(body, total=None):
 stream = io.BytesIO(body)
 stream.headers = {} if total is None else {'Content-Length': str(total)}
 return stream


class BinaryApkFixtureTest(unittest.TestCase):
 def test_real_parser_reads_binary_manifest(self):
  with io.BytesIO(apkFixture()) as file:
   parser = ApkParser(file)
   self.assertEqual(parser.getPackageName(), 'com.voxivoid.recipelab')
   self.assertEqual(parser.getMinSdkVersion(), 10)


class RecipeLabDownloadTest(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(importlib.util.find_spec('pmca.appstore.recipelab'),
   'RecipeLab downloader is not implemented')
  from unittest.mock import MagicMock
  self.urlopen = MagicMock()
  from urllib import request
  real_build_opener = request.build_opener
  def fake_build_opener(*handlers):
   op = real_build_opener(*handlers)
   op.open = self.urlopen
   self.captured_handlers = handlers
   return op
  opener = patch('pmca.appstore.recipelab.request.build_opener', side_effect=fake_build_opener)
  self.opener = opener.start()
  self.addCleanup(opener.stop)
  self.download = importlib.import_module('pmca.appstore.recipelab').downloadRecipeLab
  self.assertEqual(self.urlopen.call_count, 0, 'Import must not make requests')
  directory = tempfile.TemporaryDirectory()
  self.addCleanup(directory.cleanup)
  self.directory = Path(directory.name)
  self.destination = self.directory / 'RecipeLab.apk'
  self.destination.write_bytes(b'existing APK')
  (self.directory / 'unrelated.part').write_bytes(b'keep me')

 def release(self, assets=None, **values):
  data = {'tag_name': 'v1.2.3', 'draft': False, 'prerelease': False,
   'assets': [asset()] if assets is None else assets}
  data.update(values)
  return response(json.dumps(data).encode('utf-8'))

 def assertPreserved(self):
  self.assertEqual(self.destination.read_bytes(), b'existing APK')
  self.assertEqual((self.directory / 'unrelated.part').read_bytes(), b'keep me')
  self.assertEqual(sorted(path.name for path in self.directory.iterdir()),
   ['RecipeLab.apk', 'unrelated.part'])

 def test_valid_apk_prefers_exact_name_streams_and_reports_progress(self):
  payload = apkFixture()
  stream = response(payload, len(payload))
  read = stream.read
  stream.read = Mock(side_effect=lambda size: read(min(size, 64)))
  self.urlopen.side_effect = [self.release([asset('other.apk'), asset()]), stream]
  updates = []
  result = self.download(self.destination, lambda count, total: updates.append((count, total)))
  self.assertEqual(result, {'path': str(self.destination), 'version': 'v1.2.3',
   'package': 'com.voxivoid.recipelab', 'bytes': len(payload)})
  self.assertEqual(self.destination.read_bytes(), payload)
  self.assertGreater(len(updates), 1)
  self.assertEqual(updates[-1], (len(payload), len(payload)))
  self.assertTrue(all(total == len(payload) for count, total in updates))
  self.assertEqual([count for count, total in updates],
   sorted(set(count for count, total in updates)))
  self.assertEqual(len(list(self.directory.iterdir())), 2)
  requests = self.urlopen.call_args_list
  self.assertEqual([call.args[0].full_url for call in requests], [API_URL, ASSET_URL])
  for call in requests:
   self.assertNotIn('authorization', {key.lower() for key in call.args[0].headers})
   self.assertEqual(call.args[0].get_header('User-agent'), 'Sony-A7-PMCA')
   from urllib.request import HTTPSHandler
   context = next(handler._context for handler in self.captured_handlers if isinstance(handler, HTTPSHandler))
   self.assertIsInstance(context, ssl.SSLContext)
   self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
   self.assertTrue(context.check_hostname)
   self.assertGreater(call.kwargs['timeout'], 0)

 def test_unique_apk_with_unknown_length_reports_none(self):
  payload = apkFixture(minSdk=1)
  self.urlopen.side_effect = [self.release([asset('recipe-lab-v1.apk'), asset('notes.txt')]),
   response(payload)]
  updates = []
  self.download(str(self.destination), lambda count, total: updates.append((count, total)))
  self.assertEqual(updates[-1], (len(payload), None))
  self.assertEqual(self.destination.read_bytes(), payload)

 def test_missing_sdk_declarations_use_android_default(self):
  for kwargs in [{'usesSdk': False}, {'minSdk': None}]:
   with self.subTest(kwargs=kwargs):
    payload = apkFixture(**kwargs)
    self.urlopen.side_effect = [self.release(), response(payload)]
    self.download(self.destination)
    self.assertEqual(self.destination.read_bytes(), payload)

 def test_wrong_package_preserves_destination(self):
  self.urlopen.side_effect = [self.release(), response(apkFixture(package='com.example.other'))]
  with self.assertRaisesRegex(ValueError, 'package'):
   self.download(self.destination)
  self.assertPreserved()

 def test_invalid_sdk_preserves_destination(self):
  for sdk in [0, -1, 11, '', 'invalid']:
   with self.subTest(sdk=sdk):
    self.urlopen.side_effect = [self.release(), response(apkFixture(minSdk=sdk))]
    with self.assertRaises(ValueError):
     self.download(self.destination)
    self.assertPreserved()

 def test_unsigned_recipelab_apk_is_rejected(self):
  payload = apkFixture(signed=False)
  self.urlopen.side_effect = [self.release(), response(payload)]
  with self.assertRaisesRegex(ValueError, 'certificate'):
   self.download(self.destination)
  self.assertPreserved()

 def test_ambiguous_apk_assets_are_rejected(self):
  for assets in [[asset('one.apk'), asset('two.apk')], [asset(), asset()]]:
   with self.subTest(assets=assets):
    self.urlopen.side_effect = [self.release(assets)]
    with self.assertRaisesRegex(ValueError, 'APK'):
     self.download(self.destination)
    self.assertPreserved()

 def test_missing_apk_asset_is_rejected(self):
  for assets in [[], [asset('notes.txt')]]:
   with self.subTest(assets=assets):
    self.urlopen.side_effect = [self.release(assets)]
    with self.assertRaisesRegex(ValueError, 'APK'):
     self.download(self.destination)
    self.assertPreserved()

 def test_http_redirect_is_rejected_before_it_is_requested(self):
  module = importlib.import_module('pmca.appstore.recipelab')
  cls = getattr(module, 'HttpsRedirectHandler', None)
  self.assertIsNotNone(cls)
  req = __import__('urllib.request', fromlist=['Request']).Request(ASSET_URL)
  with self.assertRaisesRegex(ValueError, 'HTTPS'):
   cls().redirect_request(req, None, 302, 'redirect', {}, 'http://example.invalid/file.apk')

 def test_redirect_rejection_preserves_existing_destination(self):
  self.urlopen.side_effect = [self.release(), ValueError('HTTPS redirect required')]
  with self.assertRaisesRegex(ValueError, 'HTTPS'):
   self.download(self.destination)
  self.assertPreserved()

 def test_asset_url_must_be_on_exact_https_repository_release_path(self):
  urls = [ASSET_URL.replace('https:', 'http:'),
   ASSET_URL.replace('github.com/', 'github.com.evil.invalid/'),
   ASSET_URL.replace('/voxivoid/', '/someone-else/'),
   ASSET_URL.replace('/releases/download/', '/archive/'),
   ASSET_URL.replace('github.com/', 'user@github.com/'), None]
  for url in urls:
   with self.subTest(url=url):
    self.urlopen.side_effect = [self.release([asset(url=url)])]
    with self.assertRaisesRegex(ValueError, 'URL'):
     self.download(self.destination)
    self.assertPreserved()

 def test_unstable_release_is_rejected(self):
  for flags in [{'prerelease': True}, {'draft': True}]:
   with self.subTest(flags=flags):
    self.urlopen.side_effect = [self.release(**flags)]
    with self.assertRaisesRegex(ValueError, 'stable'):
     self.download(self.destination)
    self.assertPreserved()

 def test_api_and_asset_open_failure_preserve_destination(self):
  for replies in [[URLError('offline')], [self.release(), URLError('offline')]]:
   with self.subTest(replies=replies):
    self.urlopen.side_effect = replies
    with self.assertRaises(URLError):
     self.download(self.destination)
    self.assertPreserved()

 def test_network_failure_after_partial_download_cleans_up(self):
  stream = response(b'')
  stream.read = Mock(side_effect=[b'partial APK', URLError('connection lost')])
  self.urlopen.side_effect = [self.release(), stream]
  with self.assertRaises(URLError):
   self.download(self.destination)
  self.assertPreserved()

 def test_incomplete_download_is_rejected(self):
  payload = apkFixture()
  self.urlopen.side_effect = [self.release(), response(payload, len(payload) + 1)]
  with self.assertRaisesRegex(ValueError, 'download'):
   self.download(self.destination)
  self.assertPreserved()

 def test_invalid_zip_preserves_destination(self):
  self.urlopen.side_effect = [self.release(), response(b'not an APK')]
  with self.assertRaises(BadZipFile):
   self.download(self.destination)
  self.assertPreserved()

 def test_progress_callback_failure_preserves_destination(self):
  self.urlopen.side_effect = [self.release(), response(apkFixture())]
  def progress(count, total):
   raise RuntimeError('callback failed')
  with self.assertRaisesRegex(RuntimeError, 'callback failed'):
   self.download(self.destination, progress)
  self.assertPreserved()


if __name__ == '__main__':
 unittest.main()
