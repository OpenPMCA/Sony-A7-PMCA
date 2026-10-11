"""Exercise real cache persistence and visible GUI synchronization outcomes."""
import copy
import json
from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pmca.appstore.catalog import SEED_APPS, SyncResult, getCacheMetadata, saveCatalog

ROOT = Path(__file__).resolve().parents[1]


class GuiCatalogSyncContractTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.gui = runpy.run_path(str(ROOT / 'pmca-gui.py'))['main'].__globals__

 def run_worker_with_cache(self, result, cache):
  frame = SimpleNamespace(catalog=result.catalog, master=SimpleNamespace(abortSync=None),
    _runSafely=lambda callback: callback(), onCatalogSynced=lambda res: None)
  with patch.dict(self.gui, {
    'syncCatalogMetadata': lambda catalog, abort_event=None: result,
    'saveCatalog': lambda value: saveCatalog(value, cachePath=str(cache)),
  }):
   self.gui['InstallerFrame']._syncWorker(frame)

 def test_successful_worker_persists_real_success_timestamp(self):
  with TemporaryDirectory() as directory:
   cache = Path(directory) / 'catalog.json'
   result = SyncResult(copy.deepcopy(SEED_APPS), success=True,
    updated_count=1, last_success='2026-10-11T01:02:03+00:00')
   self.run_worker_with_cache(result, cache)
   self.assertEqual(getCacheMetadata(str(cache))['last_successful_sync'], '2026-10-11T01:02:03+00:00')

 def test_partial_worker_keeps_last_success_and_persists_updated_metadata(self):
  with TemporaryDirectory() as directory:
   cache = Path(directory) / 'catalog.json'
   saveCatalog(SEED_APPS, cachePath=str(cache), last_success='2026-10-10T01:02:03+00:00')
   catalog = copy.deepcopy(SEED_APPS)
   catalog['com.voxivoid.recipelab']['version'] = 'future release metadata'
   result = SyncResult(catalog, success=False, partial=True,
    errors=['rate limit'], updated_count=1, last_success='2026-10-10T01:02:03+00:00')
   self.run_worker_with_cache(result, cache)
   self.assertEqual(getCacheMetadata(str(cache))['last_successful_sync'], '2026-10-10T01:02:03+00:00')
   self.assertEqual(json.loads(cache.read_text())['apps']['com.voxivoid.recipelab']['version'], 'future release metadata')

 def native_ui(self):
  original_streams = sys.stdout, sys.stderr
  with patch.object(self.gui['MainUi'], 'startCameraMonitor'), \
       patch.object(self.gui['InstallerFrame'], 'startBackgroundSync'), \
       patch.dict(self.gui, {'loadCatalog': lambda: copy.deepcopy(SEED_APPS)}):
   root = self.gui['MainUi']('Catalog metadata contract', installerOnly=True)
   root.update()
  def cleanup():
   for callback in root.tk.splitlist(root.tk.call('after', 'info')):
    root.after_cancel(callback)
   root.close()
   sys.stdout, sys.stderr = original_streams
  self.addCleanup(cleanup)
  return root

 def test_visible_sync_outcome_uses_actual_updated_count(self):
  root = self.native_ui()
  result = SyncResult(root.installerFrame.catalog, success=True, updated_count=2)
  root.installerFrame.onCatalogSynced(result)
  root.update()
  self.assertIn('2', root.installerFrame.storeStatusVar.get())
  self.assertIn('updated', root.installerFrame.storeStatusVar.get().lower())

 def test_row_rebuild_keeps_failed_sync_outcome_visible(self):
  root = self.native_ui()
  frame = root.installerFrame
  frame.onCatalogSynced(SyncResult(frame.catalog, success=False, errors=['offline']))
  before = frame.storeStatusVar.get()
  frame.renderAppCards()
  root.update()
  self.assertEqual(frame.storeStatusVar.get(), before)
  self.assertNotIn('synced', frame.storeStatusVar.get().lower())


if __name__ == '__main__':
 unittest.main()
