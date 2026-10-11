import sys
from pathlib import Path
repo_root = str(Path(__file__).resolve().parents[1])
if repo_root not in sys.path:
 sys.path.insert(0, repo_root)

"""Unit tests for catalog caching, metadata synchronization, and APK download validation."""
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, MagicMock, patch
from urllib.error import HTTPError, URLError

from pmca.appstore.catalog import (
    loadCatalog,
    saveCatalog,
    getCacheMetadata,
    syncCatalogMetadata,
    downloadCatalogApp,
    SEED_APPS,
    SyncResult,
)


class CatalogSyncTest(unittest.TestCase):
 def setUp(self):
  self.temp_dir = TemporaryDirectory()
  self.addCleanup(self.temp_dir.cleanup)
  self.cache_path = os.path.join(self.temp_dir.name, 'catalog-test.json')

 def test_sync_result_two_tuple_unpacking_compatibility(self):
  """Verify SyncResult can be unpacked as (catalog, updated) while exposing structured fields."""
  catalog_data = {'test.pkg': {'name': 'Test'}}
  res = SyncResult(catalog_data, updated=True, success=True, partial=False, errors=[], last_success='2026-10-10T00:00:00Z', updated_count=1)

  cat, upd = res
  self.assertEqual(cat, catalog_data)
  self.assertTrue(upd)
  self.assertTrue(res.success)
  self.assertFalse(res.partial)
  self.assertEqual(res.errors, [])
  self.assertEqual(res.last_success, '2026-10-10T00:00:00Z')
  self.assertEqual(res.updated_count, 1)

 def test_hourly_cache_skips_network_when_fresh(self):
  """Verify that fresh cache (<1 hour old) does not make network calls unless force=True."""
  catalog = loadCatalog(self.cache_path)
  now_iso = datetime.now(timezone.utc).isoformat()
  saveCatalog(catalog, self.cache_path, last_success=now_iso)

  with patch('urllib.request.OpenerDirector.open') as mock_open:
   res = syncCatalogMetadata(cachePath=self.cache_path, force=False)
   self.assertFalse(res.updated)
   self.assertTrue(res.success)
   mock_open.assert_not_called()

 def test_failed_sync_does_not_advance_last_successful_sync(self):
  """Verify offline or failed sync preserves previous last_successful_sync and reports success=False."""
  catalog = loadCatalog(self.cache_path)
  old_success = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
  saveCatalog(catalog, self.cache_path, last_success=old_success)

  # Mock network failure for all GitHub requests
  with patch('urllib.request.OpenerDirector.open', side_effect=URLError('Network offline')), \
       patch('pmca.commands.usb.listApps', side_effect=URLError('Offline')):
   res = syncCatalogMetadata(cachePath=self.cache_path, force=True)
   self.assertFalse(res.success)
   self.assertGreater(len(res.errors), 0)
   # Must NOT advance last_success timestamp
   self.assertEqual(res.last_success, old_success)

  # Verify on-disk cache also preserves old timestamp
  saveCatalog(res.catalog, self.cache_path, last_success=res.last_success)
  meta = getCacheMetadata(self.cache_path)
  self.assertEqual(meta['last_successful_sync'], old_success)

 def test_github_rate_limit_handled_gracefully(self):
  """Verify HTTP 403 rate limit halts subsequent requests and marks rate_limited error."""
  catalog = loadCatalog(self.cache_path)
  import io
  mock_403 = HTTPError('https://api.github.com', 403, 'rate limit exceeded', {}, io.BytesIO(b''))

  with patch('urllib.request.OpenerDirector.open', side_effect=mock_403), \
       patch('pmca.commands.usb.listApps', side_effect=URLError('Offline')):
   res = syncCatalogMetadata(cachePath=self.cache_path, force=True)
   self.assertFalse(res.success)
   self.assertTrue(any('rate limit' in err.lower() for err in res.errors))
  mock_403.close()

 def test_download_catalog_app_rejects_insecure_url(self):
  """Verify downloadCatalogApp strictly rejects non-HTTPS URLs."""
  app = {'name': 'InsecureApp', 'package': 'com.insecure', 'url': 'http://example.com/app.apk'}
  dst = os.path.join(self.temp_dir.name, 'out.apk')
  with self.assertRaises(ValueError) as ctx:
   downloadCatalogApp(app, dst)
  self.assertIn('HTTPS', str(ctx.exception))

 def test_download_catalog_app_rejects_package_mismatch(self):
  """Verify downloadCatalogApp validates APK package name against expected package."""
  from tests.apk_fixture import apkFixture
  apk_bytes = apkFixture(package='com.actual.package', signed=True)
  app = {'name': 'WrongApp', 'package': 'com.wrong.expected', 'url': 'https://github.com/test/app.apk'}
  dst = os.path.join(self.temp_dir.name, 'out.apk')

  mock_resp = MagicMock()
  mock_resp.headers = {'Content-Length': str(len(apk_bytes))}
  mock_resp.read = Mock(side_effect=[apk_bytes, b''])
  mock_resp.__enter__.return_value = mock_resp

  with patch('urllib.request.OpenerDirector.open', return_value=mock_resp):
   with self.assertRaises(ValueError) as ctx:
    downloadCatalogApp(app, dst)
   self.assertIn('Package mismatch', str(ctx.exception))
   self.assertFalse(os.path.exists(dst))

 def test_download_catalog_app_validates_real_apk_fixtures(self):
  """Optional real APK fixture validation using PMCA_TEST_APK_DIR environment variable."""
  fixture_dir = os.environ.get('PMCA_TEST_APK_DIR')
  if not fixture_dir:
   self.skipTest("Optional real APK fixture test requires PMCA_TEST_APK_DIR environment variable")

  fixtures = [
   ('OpenMemories-Tweak.apk', 'com.github.ma1co.openmemories.tweak', '0.11', 707),
   ('BetterManual.apk', 'com.obsidium.bettermanual', '1.5', 699),
   ('FocusBracket.apk', 'com.obsidium.focusbracket', '1.5', 699),
  ]

  for fname, pkg, ver, cert_len in fixtures:
   fpath = Path(fixture_dir) / fname
   if not fpath.exists():
    continue
   with self.subTest(package=pkg):
    apk_bytes = fpath.read_bytes()
    app = {'name': pkg, 'package': pkg, 'url': f'https://github.com/test/{pkg}.apk', 'version': ver}
    dst = os.path.join(self.temp_dir.name, f'{pkg}.apk')

    mock_resp = MagicMock()
    mock_resp.headers = {'Content-Length': str(len(apk_bytes))}
    mock_resp.read = Mock(side_effect=[apk_bytes, b''])
    mock_resp.__enter__.return_value = mock_resp

    with patch('urllib.request.OpenerDirector.open', return_value=mock_resp):
     result = downloadCatalogApp(app, dst)
     self.assertEqual(result['package'], pkg)
     self.assertEqual(result['version'], ver)
     self.assertEqual(result['cert_len'], cert_len)
     self.assertTrue(os.path.exists(dst))


if __name__ == '__main__':
 unittest.main()


class CatalogBrandingTest(unittest.TestCase):
 def test_catalog_network_requests_use_sony_a7_pmca_user_agent(self):
  """Verify that catalog metadata synchronization sets User-Agent: Sony-A7-PMCA."""
  from pmca.appstore.catalog import syncCatalogMetadata
  with patch('urllib.request.OpenerDirector.open') as mock_open:
   syncCatalogMetadata(timeout=5, force=True)
   self.assertTrue(mock_open.called)
   req = mock_open.call_args_list[0].args[0]
   self.assertEqual(req.get_header('User-agent'), 'Sony-A7-PMCA')
