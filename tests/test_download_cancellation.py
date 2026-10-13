"""Tests for cooperative download cancellation across RecipeLab and Catalog downloaders."""
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

repo_root = str(Path(__file__).resolve().parents[1])
if repo_root not in sys.path:
 sys.path.insert(0, repo_root)

from pmca.util.http import DownloadCancelledError
from pmca.appstore.recipelab import downloadRecipeLab
from pmca.appstore.catalog import downloadCatalogApp
from tests.apk_fixture import apkFixture


class DownloadCancellationTest(unittest.TestCase):
 def setUp(self):
  self.test_dir = tempfile.TemporaryDirectory()
  self.target_path = os.path.join(self.test_dir.name, "target.apk")

 def tearDown(self):
  self.test_dir.cleanup()

 def test_download_recipelab_pre_aborted_event_raises_and_cleans_up(self):
  abort = threading.Event()
  abort.set()
  with open(self.target_path, "wb") as f:
   f.write(b"existing-good-file")

  with self.assertRaises(DownloadCancelledError):
   downloadRecipeLab(self.target_path, abort_event=abort)

  # Existing file must NOT be modified or deleted
  self.assertTrue(os.path.exists(self.target_path))
  with open(self.target_path, "rb") as f:
   self.assertEqual(f.read(), b"existing-good-file")

  # No partial files left in directory
  files = os.listdir(self.test_dir.name)
  self.assertEqual(files, ["target.apk"])

 def test_download_recipelab_aborts_during_chunk_download(self):
  abort = threading.Event()
  release = {
   'tag_name': 'v1.6.2',
   'assets': [{'name': 'RecipeLab.apk', 'browser_download_url': 'https://github.com/voxivoid/recipe-lab-sony-pmca/releases/download/v1.6.2/RecipeLab.apk'}]
  }

  def mock_open(req, timeout=30):
   url = getattr(req, 'full_url', str(req))
   if 'api.github.com' in url:
    resp = Mock()
    resp.read.side_effect = [json.dumps(release).encode('utf-8'), b'']
    resp.__enter__ = Mock(return_value=resp)
    resp.__exit__ = Mock(return_value=False)
    return resp
   else:
    # Asset download: set abort on first chunk
    resp = Mock()
    resp.headers = {'Content-Length': '100000'}
    def chunk_read(n):
     abort.set()
     return b'chunk1'
    resp.read = Mock(side_effect=chunk_read)
    resp.__enter__ = Mock(return_value=resp)
    resp.__exit__ = Mock(return_value=False)
    return resp

  import json
  with patch('urllib.request.OpenerDirector.open', side_effect=mock_open):
   with self.assertRaises(DownloadCancelledError):
    downloadRecipeLab(self.target_path, abort_event=abort)

  # Target must not exist (was not previously there)
  self.assertFalse(os.path.exists(self.target_path))
  # No lingering partial files
  self.assertEqual(os.listdir(self.test_dir.name), [])

 def test_download_catalog_app_pre_aborted_event_raises_and_cleans_up(self):
  abort = threading.Event()
  abort.set()
  with open(self.target_path, "wb") as f:
   f.write(b"existing-catalog-file")

  app = {
   'package': 'com.voxivoid.recipelab',
   'name': 'RecipeLab',
   'url': 'https://github.com/voxivoid/recipe-lab-sony-pmca/releases/download/v1.6.2/RecipeLab.apk',
   'version': '1.6.2',
  }

  with self.assertRaises(DownloadCancelledError):
   downloadCatalogApp(app, self.target_path, abort_event=abort)

  self.assertTrue(os.path.exists(self.target_path))
  with open(self.target_path, "rb") as f:
   self.assertEqual(f.read(), b"existing-catalog-file")
  self.assertEqual(os.listdir(self.test_dir.name), ["target.apk"])

 def test_download_catalog_app_aborts_during_chunk_download(self):
  abort = threading.Event()
  app = {
   'package': 'com.voxivoid.recipelab',
   'name': 'RecipeLab',
   'url': 'https://github.com/voxivoid/recipe-lab-sony-pmca/releases/download/v1.6.2/RecipeLab.apk',
   'version': '1.6.2',
  }

  def mock_open(req, timeout=30):
   resp = Mock()
   resp.headers = {'Content-Length': '100000'}
   def chunk_read(n):
    abort.set()
    return b'partial_data'
   resp.read = Mock(side_effect=chunk_read)
   resp.__enter__ = Mock(return_value=resp)
   resp.__exit__ = Mock(return_value=False)
   return resp

  with patch('urllib.request.OpenerDirector.open', side_effect=mock_open):
   with self.assertRaises(DownloadCancelledError):
    downloadCatalogApp(app, self.target_path, abort_event=abort)

  self.assertFalse(os.path.exists(self.target_path))
  self.assertEqual(os.listdir(self.test_dir.name), [])

 def test_download_catalog_app_preserves_fourth_positional_timeout(self):
  """Verify downloadCatalogApp(app, filename, progress, timeout) keeps 4th positional as timeout."""
  app = {
   'package': 'com.voxivoid.recipelab',
   'name': 'RecipeLab',
   'url': 'https://github.com/voxivoid/recipe-lab-sony-pmca/releases/download/v1.6.2/RecipeLab.apk',
   'version': '1.6.2',
  }
  apk_bytes = apkFixture(package='com.voxivoid.recipelab', minSdk=10, signed=True)
  seen_timeouts = []

  def mock_open(req, timeout=30):
   seen_timeouts.append(timeout)
   resp = Mock()
   resp.headers = {'Content-Length': str(len(apk_bytes))}
   resp.read = Mock(side_effect=[apk_bytes, b''])
   resp.__enter__ = Mock(return_value=resp)
   resp.__exit__ = Mock(return_value=False)
   return resp

  with patch('urllib.request.OpenerDirector.open', side_effect=mock_open):
   res = downloadCatalogApp(app, self.target_path, None, 42)

  self.assertEqual(seen_timeouts, [42])
  self.assertEqual(res['package'], 'com.voxivoid.recipelab')
  self.assertTrue(os.path.exists(self.target_path))


if __name__ == '__main__':
 unittest.main()
