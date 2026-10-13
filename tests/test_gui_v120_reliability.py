"""Regression and acceptance tests for Sony Open PMCA v1.2.0 GUI reliability (Packages 3 & 4)."""
import copy
import io
from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pmca.appstore.catalog import SEED_APPS, SyncResult
from pmca.commands.usb import CameraOperationError
from pmca.util.http import DownloadCancelledError
from tests.apk_fixture import apkFixture

ROOT = Path(__file__).resolve().parents[1]


class GuiV120ReliabilityTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.gui = runpy.run_path(str(ROOT / "pmca-gui.py"))["main"].__globals__

 def setUp(self):
  self.temp = TemporaryDirectory()
  self.addCleanup(self.temp.cleanup)
  self.valid_apk = Path(self.temp.name) / "valid_signed.apk"
  self.valid_apk.write_bytes(apkFixture(signed=True))

 def make_ui(self, title="Test v1.2.0 UI"):
  orig_streams = sys.stdout, sys.stderr
  fake_cat = copy.deepcopy(SEED_APPS)
  p_mon = patch.object(self.gui["MainUi"], "startCameraMonitor")
  p_sync = patch.object(self.gui["InstallerFrame"], "startBackgroundSync")
  p_ro = patch("pmca.commands.usb.getReadOnlyCameraInfo", Mock(return_value=None))
  p_ic = patch("pmca.commands.usb.infoCommand", Mock(return_value=None))
  p_chk = patch("pmca.commands.usb.checkCameraConnection", Mock(return_value=None))
  p_dict = patch.dict(self.gui, {
   "infoCommand": Mock(return_value=None),
   "getReadOnlyCameraInfo": Mock(return_value=None),
   "checkCameraConnection": Mock(return_value=None),
   "syncCatalogMetadata": Mock(return_value=(fake_cat, False)),
   "loadCatalog": Mock(return_value=copy.deepcopy(fake_cat)),
   "saveCatalog": Mock(),
   "askyesno": Mock(return_value=True),
   "showerror": Mock(),
   "askopenfilename": Mock(return_value=""),
   "asksaveasfilename": Mock(return_value=""),
  })
  p_mon.start()
  p_sync.start()
  p_ro.start()
  p_ic.start()
  p_chk.start()
  p_dict.start()
  root = self.gui["MainUi"](title, installerOnly=True)
  root.withdraw()
  root.update()

  def cleanup():
   try:
    for cb in root.tk.splitlist(root.tk.call("after", "info")):
     try:
      root.after_cancel(cb)
     except Exception:
      pass
   except Exception:
    pass
   root.cameraBusy = False
   if hasattr(root, "downloadBusy"):
    root.downloadBusy = False
   if hasattr(root, "fetchingInfo"):
    root.fetchingInfo = False
   if hasattr(root, "lastReportedBackendBusy"):
    root.lastReportedBackendBusy = False
   for t_name in ("_fetchInfoThread", "_reconnectThread"):
    t = getattr(root, t_name, None)
    if t and t.is_alive():
     t.join(timeout=1.0)
   try:
    root.destroy()
   except Exception:
    pass
   p_dict.stop()
   p_chk.stop()
   p_ic.stop()
   p_ro.stop()
   p_sync.stop()
   p_mon.stop()
   sys.stdout, sys.stderr = orig_streams
   import gc
   gc.collect()

  self.addCleanup(cleanup)
  return root

 def test_bounded_fifo_queue_drain_yields_and_is_lossless(self):
  root = self.make_ui()
  executed = []

  for i in range(100):
   if i == 25:
    def bad_cb(idx=i):
     executed.append(idx)
     raise RuntimeError("simulated callback error")
    root.run(bad_cb)
   else:
    root.run(lambda idx=i: executed.append(idx))

  with patch("traceback.print_exc") as mock_exc:
   root._processQueue()
   # First slice must be bounded to <= 40 items so the event loop can yield
   first_slice_count = len(executed)
   self.assertGreater(first_slice_count, 0)
   self.assertLessEqual(first_slice_count, 40)
   self.assertFalse(root._queue.empty())

   # Drain remaining slices
   slices = 1
   while not root._queue.empty() and slices < 20:
    root._processQueue()
    slices += 1

  self.assertEqual(executed, list(range(100)))
  mock_exc.assert_called_once()

 def test_run_safely_never_calls_tk_after_from_worker_thread(self):
  root = self.make_ui()
  frame = root.installerFrame
  called_on_main = []
  after_calls_from_worker = []

  orig_root_after = root.after
  orig_frame_after = frame.after
  main_tid = threading.get_ident()

  def guarded_root_after(*args, **kwargs):
   if threading.get_ident() != main_tid:
    after_calls_from_worker.append(("root", args))
   return orig_root_after(*args, **kwargs)

  def guarded_frame_after(*args, **kwargs):
   if threading.get_ident() != main_tid:
    after_calls_from_worker.append(("frame", args))
   return orig_frame_after(*args, **kwargs)

  with patch.object(root, "after", side_effect=guarded_root_after), \
       patch.object(frame, "after", side_effect=guarded_frame_after):
   def worker():
    root._runSafely(lambda: called_on_main.append("from_root"))
    frame._runSafely(lambda: called_on_main.append("from_frame"))

   t = threading.Thread(target=worker)
   t.start()
   t.join(timeout=2.0)

  self.assertEqual(after_calls_from_worker, [])
  root._processQueue()
  self.assertEqual(called_on_main, ["from_root", "from_frame"])

 def test_log_retention_caps_at_5000_lines_and_tracks_exact_omission_count(self):
  root = self.make_ui()
  root.clearLog()

  # Write 6,200 complete lines in chunks of 200
  for batch in range(31):
   chunk = "".join(f"Log line {batch * 200 + j}\n" for j in range(200))
   root.log(chunk, error=(batch % 5 == 0))

  self.assertEqual(len(root.rawLogEntries), 5000)
  self.assertEqual(root.omittedLogCount, 1200)
  self.assertEqual(root.rawLogEntries[0][1], "Log line 1200")
  self.assertEqual(root.rawLogEntries[-1][1], "Log line 6199")
  omission_notice = root.logOmissionVar.get()
  self.assertTrue("1,200" in omission_notice or "1200" in omission_notice)
  self.assertIn("5,000" if "5,000" in omission_notice else "5000", omission_notice)

 def test_log_batching_coalesces_multiline_and_preserves_partial_chunks_and_tags(self):
  root = self.make_ui()
  root.clearLog()

  config_calls = []
  orig_config = root.logText.text.configure
  def spy_config(*args, **kwargs):
   if "state" in kwargs:
    config_calls.append(kwargs["state"])
   return orig_config(*args, **kwargs)

  with patch.object(root.logText.text, "configure", side_effect=spy_config):
   multiline = "".join(f"Info line {i}\n" for i in range(25)) + "Partial trailing"
   root.log(multiline, error=False)

  # State should only toggle NORMAL -> DISABLED once for the entire 25-line chunk
  self.assertEqual(config_calls, ["normal", "disabled"])
  self.assertEqual(len(root.rawLogEntries), 25)
  self.assertEqual(root.logBuffers[False], "Partial trailing")

  # Finish partial line
  root.log(" completed\n", error=False)
  self.assertEqual(len(root.rawLogEntries), 26)
  self.assertEqual(root.rawLogEntries[-1][1], "Partial trailing completed")

 def test_clear_log_resets_history_buffers_omission_and_ignores_stale_render_without_dropping_tasks(self):
  root = self.make_ui()
  root.clearLog()
  root.logFilterVar.set("MatchMe")
  root.autoScroll = False

  # Add 5,100 lines so omission count is 100
  for b in range(51):
   root.log("".join(f"MatchMe line {b * 100 + i}\n" for i in range(100)))
  root.log("unfinished partial fragment")

  self.assertEqual(root.omittedLogCount, 100)
  task_completed = []
  root.run(lambda: task_completed.append(True))

  root.clearLog()
  self.assertEqual(root.rawLogEntries, [])
  self.assertEqual(root.omittedLogCount, 0)
  self.assertEqual(root.logOmissionVar.get(), "")
  self.assertEqual(root.logBuffers, {False: "", True: ""})
  self.assertEqual(root.logText.text.get("1.0", "end").strip(), "")
  # Filter and autoScroll preferences must be preserved across Clear
  self.assertEqual(root.logFilterVar.get(), "MatchMe")
  self.assertFalse(root.autoScroll)

  # Non-log task completion callback in queue must still execute
  root._processQueue()
  self.assertEqual(task_completed, [True])

 def test_debounced_and_chunked_filter_ignores_stale_generation_and_preserves_selection(self):
  root = self.make_ui()
  root.clearLog()

  chunk = "".join(
   f"Alpha event {i}\n" if i % 2 == 0 else f"Beta event {i}\n"
   for i in range(1200)
  )
  root.log(chunk)

  # Rapidly type queries; only final query "Beta" should win
  root.logFilterVar.set("Alpha")
  root.logFilterVar.set("Al")
  root.logFilterVar.set("Beta")
  if hasattr(root, "_applyLogFilterNow"):
   root._applyLogFilterNow()
  else:
   root.filterLogDisplay()
  root.update()

  rendered = root.logText.text.get("1.0", "end")
  self.assertIn("Beta event 1", rendered)
  self.assertNotIn("Alpha event 0", rendered)

 def test_copy_and_export_snapshot_current_filtered_view_and_omission_scope(self):
  root = self.make_ui()
  root.clearLog()

  for b in range(52):
   root.log("".join(f"Row {b * 100 + i} tag={'ERR' if i % 20 == 0 else 'OK'}\n" for i in range(100)))

  self.assertEqual(root.omittedLogCount, 200)
  root.logFilterVar.set("tag=ERR")

  # Even before any debounced UI text rebuild runs, copyLog and exportLog must snapshot the full filtered view
  root.clipboard_clear = Mock()
  root.clipboard_append = Mock()
  root.copyLog()
  copied = root.clipboard_append.call_args.args[0]
  self.assertIn("tag=ERR", copied)
  self.assertNotIn("tag=OK", copied)
  self.assertIn("200", copied)

  export_file = Path(self.temp.name) / "exported.log"
  with patch.dict(self.gui, {"asksaveasfilename": Mock(return_value=str(export_file))}):
   root.exportLog()
  exported = export_file.read_text(encoding="utf-8")
  self.assertEqual(exported, copied)

 def test_copy_errors_warns_when_older_lines_evicted(self):
  root = self.make_ui()
  root.clearLog()

  for b in range(51):
   root.log("".join(f"Normal line {b * 100 + i}\n" for i in range(100)))
  root.log("Error: Transfer interrupted\nTraceback detail line\n", error=True)

  self.assertEqual(root.omittedLogCount, 102)
  root.clipboard_clear = Mock()
  root.clipboard_append = Mock()
  root.copyErrors()
  copied_err = root.clipboard_append.call_args.args[0]
  self.assertIn("Error: Transfer interrupted", copied_err)
  self.assertIn("Traceback detail line", copied_err)
  self.assertTrue("102" in copied_err and ("omitted" in copied_err.lower() or "evicted" in copied_err.lower()))

 def test_camera_monitor_continues_during_http_download_and_download_completion_never_clears_camera_busy(self):
  root = self.make_ui()
  frame = root.installerFrame

  # Start a foreground download state
  root.setDownloadBusy(True)
  self.assertTrue(root.downloadBusy)
  self.assertFalse(root.cameraBusy)

  # Monitor condition must allow polling when only downloadBusy is True
  self.assertTrue(root._canPollCameraMonitor())

  # Now simulate a camera operation starting and setting cameraBusy=True
  root.setCameraBusy(True)
  frame.updateProgress(45, "Installing APK to camera")
  active_gen = getattr(frame, "_activeTaskGen", 0)

  # Stale progress or download completion from an earlier task generation must NOT overwrite install progress or clear cameraBusy
  frame.updateProgress(100, "Stale download finished", taskGen=active_gen - 1)
  self.assertIn("Installing APK to camera", frame.progressText.get())

  root.setDownloadBusy(False)
  self.assertTrue(root.cameraBusy)
  self.assertEqual(str(frame.installButton["state"]), "disabled")

 def test_local_download_cancellation_is_atomic_and_preserves_staged_apk(self):
  root = self.make_ui()
  frame = root.installerFrame
  frame.setApkFile(str(self.valid_apk))
  self.assertEqual(frame.getSelectedApk(), str(self.valid_apk))

  dest_apk = Path(self.temp.name) / "new_download.apk"

  def cancellable_download(app, filename, progress=None, timeout=30, abort_event=None):
   self.assertIsNotNone(abort_event)
   if progress:
    progress(4096, 16384)
   # Simulate user clicking Cancel Download mid-flight
   frame.cancelDownload()
   self.assertTrue(abort_event.is_set())
   raise DownloadCancelledError("Download cancelled by user")

  with patch.dict(self.gui, {
   "asksaveasfilename": Mock(return_value=str(dest_apk)),
   "downloadCatalogApp": cancellable_download,
  }):
   frame.downloadStoreApp("com.github.ma1co.openmemories.tweak")
   deadline = time.monotonic() + 2.0
   while root.downloadBusy and time.monotonic() < deadline:
    root._processQueue()
    root.update()
    time.sleep(0.01)
   root._processQueue()
   root.update()

  self.assertFalse(root.downloadBusy)
  self.assertIn("cancelled", frame.progressText.get().lower())
  # Previously staged APK must remain untouched
  self.assertEqual(frame.getSelectedApk(), str(self.valid_apk))
  self.assertFalse(dest_apk.exists())

 def test_camera_operation_error_distinguishes_outcome_unknown_from_preflight_failure(self):
  root = self.make_ui()
  frame = root.installerFrame

  frame.updateProgress(65, "Uploading APK")
  frame.showInstallResult(CameraOperationError("USB pipe stalled after push", phase="response", outcome_unknown=True))
  self.assertEqual(int(frame.progressBar["value"]), 65)
  self.assertIn("outcome unknown", frame.progressText.get().lower())

  frame.updateProgress(10, "Opening session")
  frame.showInstallResult(CameraOperationError("Device busy", phase="preflight", outcome_unknown=False))
  self.assertEqual(int(frame.progressBar["value"]), 10)
  self.assertNotIn("outcome unknown", frame.progressText.get().lower())
  self.assertIn("device busy", frame.progressText.get().lower())

 def test_missing_installation_eligibility_fails_closed(self):
  root = self.make_ui()
  frame = root.installerFrame
  frame.setApkFile(str(self.valid_apk))

  # Status dict has appConnected=True but omits app_installation_supported
  ambiguous_info = {
   "connected": True,
   "physicalDetected": True,
   "appConnected": True,
   "status": "ready",
   "mode": "MTP",
   "name": "ILCE-7",
   "model": "ILCE-7",
   "vendor": "Sony (0x054c)",
  }
  root.onCameraStatusUpdate(ambiguous_info)
  root.update()

  self.assertTrue(root.cameraConnected)
  self.assertFalse(root.cameraInstallEnabled)
  self.assertEqual(str(frame.installButton["state"]), "disabled")

 def test_close_guard_blocks_during_camera_busy_backend_busy_and_auto_info_probe(self):
  for attr in ("cameraBusy", "lastReportedBackendBusy", "fetchingInfo"):
   with self.subTest(busy_flag=attr):
    root = self.make_ui()
    setattr(root, attr, True)
    with patch.object(root, "destroy") as mock_destroy, \
         patch.dict(self.gui, {"showerror": Mock()}) as patched_gui:
     root.close()
     mock_destroy.assert_not_called()
     patched_gui["showerror"].assert_called_once()
    setattr(root, attr, False)

 def test_indeterminate_progress_continuity_does_not_restart_on_message_updates(self):
  root = self.make_ui()
  frame = root.installerFrame

  with patch.object(frame.progressBar, "start") as mock_start, \
       patch.object(frame.progressBar, "stop") as mock_stop:
   frame.updateProgress(None, "Checking release tag…")
   frame.updateProgress(None, "Resolving APK asset…")
   frame.updateProgress(None, "Validating headers…")
   # start() must be called only ONCE on transition into indeterminate mode, and stop() 0 times
   self.assertEqual(mock_start.call_count, 1)
   self.assertEqual(mock_stop.call_count, 0)
   self.assertEqual(frame.progressText.get(), "Validating headers…")

   # Transition back to determinate mode stops the indeterminate animation once
   frame.updateProgress(25, "Downloading")
   self.assertEqual(mock_stop.call_count, 1)
   self.assertEqual(int(frame.progressBar["value"]), 25)

 def test_store_offscreen_keyboard_focus_scrolls_card_into_viewport_and_rebuild_preserves_state(self):
  root = self.make_ui()
  root.deiconify()
  root.geometry("1160x760")
  root.selectTab(1)
  root.update_idletasks()
  root.update()

  frame = root.installerFrame
  frame.canvas.yview_moveto(0.0)
  root.update_idletasks()
  root.update()
  self.assertAlmostEqual(frame.canvas.yview()[0], 0.0, places=2)

  # Focus the last card's download button (off-screen at bottom)
  last_btn = frame.cardDownloadButtons[-1]
  last_btn.focus_force()
  last_btn.event_generate("<FocusIn>")
  root.update_idletasks()
  root.update()

  scrolled_y = frame.canvas.yview()[0]
  self.assertGreater(scrolled_y, 0.25, "Focusing off-screen Store button must scroll canvas viewport down")

  # Trigger catalog sync metadata update and verify viewport position is preserved
  frame.onCatalogSynced(SyncResult(frame.catalog, success=True, updated_count=1))
  root.update_idletasks()
  root.update()
  after_sync_y = frame.canvas.yview()[0]
  self.assertAlmostEqual(after_sync_y, scrolled_y, delta=0.05)
  root.withdraw()

 def test_keyboard_navigation_shortcuts_switch_tabs_without_breaking_entry_shortcuts(self):
  root = self.make_ui()
  self.assertEqual(root.notebook.index(root.notebook.select()), 1)

  root._onNavShortcut(0)
  root.update()
  self.assertEqual(root.notebook.index(root.notebook.select()), 0)

  root._onNavShortcut(2)
  root.update()
  self.assertEqual(root.notebook.index(root.notebook.select()), 2)

  root._onNavShortcut(1)
  root.update()
  self.assertEqual(root.notebook.index(root.notebook.select()), 1)

 def test_msc_mode_mismatch_vs_access_denied_diagnostic_copy(self):
  root = self.make_ui()

  msc_info = {
   "connected": False,
   "physicalDetected": True,
   "appConnected": False,
   "status": "msc_excluded",
   "mode": "Mass Storage (Class 8)",
   "name": "ILCE-7",
   "failure_reason": "Camera is in Mass Storage mode. Switch USB Connection to MTP in the camera Setup menu.",
   "app_installation_supported": False,
  }
  root.onCameraStatusUpdate(msc_info)
  root.update()
  self.assertIn("Mass Storage", root.usbStatusVar.get())
  self.assertIn("MTP", root.installerFrame.apkStatusNote.get())
  self.assertNotIn("permission", root.installerFrame.apkStatusNote.get().lower())

  denied_info = {
   "connected": False,
   "physicalDetected": True,
   "appConnected": False,
   "status": "access_denied",
   "mode": "MTP",
   "name": "ILCE-7",
   "failure_reason": "macOS ptpcamerad or another app holds exclusive USB access. Close Photos/Image Capture.",
   "app_installation_supported": False,
  }
  root.onCameraStatusUpdate(denied_info)
  root.update()
  self.assertIn("unavailable", root.usbStatusVar.get().lower())
  self.assertIn("Photos/Image Capture", root.installerFrame.apkStatusNote.get())

 def test_exact_filtered_and_unfiltered_retention_reconciliation(self):
  root = self.make_ui()
  root.clearLog()

  # 1. Unfiltered 5,001 rows: model must have 5,000 (starting row0001) and text must have exactly 5,000 (starting row0001)
  for i in range(5001):
   root.log("row%04d\n" % i)

  self.assertEqual(len(root.rawLogEntries), 5000)
  self.assertEqual(root.rawLogEntries[0][1], "row0001")
  self.assertEqual(root.rawLogEntries[-1][1], "row5000")
  self.assertEqual(root.omittedLogCount, 1)

  text_content = root.logText.text.get("1.0", "end-1c").splitlines()
  self.assertEqual(len(text_content), 5000)
  self.assertIn("row0001", text_content[0])
  self.assertNotIn("row0000", text_content[0])
  self.assertIn("row5000", text_content[-1])

  # 2. Filter MATCH: log MATCH very-old-error, then 5,000 non-matching rows
  root.clearLog()
  root.logFilterVar.set("MATCH")
  if hasattr(root, "_applyLogFilterNow"):
   root._applyLogFilterNow()
  root.log("MATCH very-old-error\n")
  for i in range(5000):
   root.log("nonmatch%04d\n" % i)

  # very-old-error was evicted from model (evicted by 5,000 newer nonmatch lines)
  model_matches = [line for _, line, _ in root.rawLogEntries if "MATCH" in line]
  self.assertEqual(model_matches, [])
  text_matches = [line for line in root.logText.text.get("1.0", "end-1c").splitlines() if "MATCH" in line]
  self.assertEqual(text_matches, [], "Evicted error must not remain visible in Text widget when evicted from model")

 def test_chunked_filter_interleaved_live_append_preserves_chronological_order(self):
  root = self.make_ui()
  root.clearLog()

  # Populate 2,500 lines
  for i in range(2500):
   root.log("row%04d\n" % i)

  # Start chunked filter rebuild (chunk 1 of 1,000 rows renders synchronously; chunks 2-3 scheduled via after)
  root.filterLogDisplay()
  self.assertIsNotNone(root._logFilterChunkAfterId)

  # While chunks 2-3 (rows 1000..2499) are still pending in after(), fragmented live log arrives
  root.log("café α")
  root.log(" done\n")

  # Wait for all chunks and deferred live appends to settle
  deadline = time.monotonic() + 2.0
  while (getattr(root, "_logFilterAfterId", None) or getattr(root, "_logFilterChunkAfterId", None)) and time.monotonic() < deadline:
   root.update()
   time.sleep(0.01)
  root.update()

  text_lines = [l for l in root.logText.text.get("1.0", "end-1c").split("\n") if l]
  self.assertEqual(len(text_lines), 2501)
  self.assertIn("café α done", text_lines[-1], "Live append during chunked filter must settle as the final line in text widget")
  self.assertIn("row2499", text_lines[-2], "Row 2499 must precede live append in text widget")

 def test_store_card_url_promotion_attaches_live_command_without_recreation(self):
  root = self.make_ui()
  frame = root.installerFrame

  # Insert custom app without URL into catalog
  custom_pkg = "org.example.dynamic-app"
  frame.catalog[custom_pkg] = {
   "package": custom_pkg,
   "name": "Dynamic App",
   "author": "tester",
   "desc": "Testing in-place URL promotion",
   "version": "1.0",
   "url": None,
  }
  frame.renderAppCards()
  root.update()

  btn = frame._renderedCards[custom_pkg]["btn"]
  self.assertEqual(str(btn.cget("text")), "No APK")
  self.assertEqual(str(btn.cget("state")), "disabled")

  # Promote app to have valid download URL via catalog sync
  download_calls = []
  with patch.object(frame, "downloadStoreApp", side_effect=lambda p: download_calls.append(p)):
   frame.catalog[custom_pkg]["url"] = "https://example.com/dynamic-app.apk"
   frame.renderAppCards()
   root.update()

   self.assertEqual(str(btn.cget("text")), "Download APK")
   self.assertEqual(str(btn.cget("state")), "normal")

   # Invoking the promoted button must trigger downloadStoreApp for custom_pkg!
   btn.invoke()
   self.assertEqual(download_calls, [custom_pkg])

   # Demote back to No APK
   frame.catalog[custom_pkg]["url"] = None
   frame.renderAppCards()
   root.update()
   self.assertEqual(str(btn.cget("text")), "No APK")
   self.assertEqual(str(btn.cget("state")), "disabled")

 def test_space_padded_filter_preserves_exact_whitespace_in_copy_and_view(self):
  root = self.make_ui()
  root.clearLog()

  root.log(" padded \n")
  root.log("unpadded\n")

  # Search with leading and trailing spaces
  root.logFilterVar.set(" padded ")
  if hasattr(root, "_applyLogFilterNow"):
   root._applyLogFilterNow()
  root.update()

  root.clipboard_clear = Mock()
  root.clipboard_append = Mock()
  root.copyLog()
  copied = root.clipboard_append.call_args.args[0]

  self.assertIn(" padded ", copied)
  self.assertNotIn("unpadded", copied)
  self.assertIn('filter=" padded "', copied)

 def test_info_task_camera_session_epoch_prevents_stale_delayed_body_overwrite(self):
  root = self.make_ui()
  info_frame = root.infoFrame

  # Session 1: Camera 1 connects
  root.onCameraStatusUpdate({
   "connected": True, "physicalDetected": True, "appConnected": True,
   "status": "ready", "mode": "MTP", "name": "ILCE-7", "model": "ILCE-7",
   "serial": "11111111", "app_installation_supported": True,
  })
  root.update()
  self.assertEqual(info_frame.infoVars["Model"].get(), "ILCE-7")
  session_1 = getattr(root, "_cameraSessionId", 0)

  # Start InfoTask for Camera 1
  delayed_data_cam1 = {"Model": "ILCE-7", "Lens": "Old Lens 50mm", "Firmware version": "1.00"}
  task = self.gui["InfoTask"](info_frame)
  with patch.dict(self.gui, {"askyesno": Mock(return_value=True)}):
   driver = task.doBefore()
  self.assertEqual(task.captured_session, session_1)

  # While Camera 1 query is in flight, camera disconnects and Camera 2 connects (Session 2)
  root.onCameraStatusUpdate(None)
  root.update()
  self.assertGreater(getattr(root, "_cameraSessionId", 0), session_1)

  root.onCameraStatusUpdate({
   "connected": True, "physicalDetected": True, "appConnected": True,
   "status": "ready", "mode": "MTP", "name": "ILCE-7RM2", "model": "ILCE-7RM2",
   "serial": "22222222", "app_installation_supported": True,
  })
  root.update()
  info_frame.showCameraInfo({"Model": "ILCE-7RM2", "Lens": "New Lens 24-70mm", "Firmware version": "2.00"})
  root.update()
  self.assertEqual(info_frame.infoVars["Model"].get(), "ILCE-7RM2")
  self.assertEqual(info_frame.infoVars["Lens"].get(), "New Lens 24-70mm")

  # Now Camera 1's delayed InfoTask worker finishes and calls doAfter
  task.doAfter((True, delayed_data_cam1))
  root.update()

  # Must NOT overwrite Camera 2's data!
  self.assertEqual(info_frame.infoVars["Model"].get(), "ILCE-7RM2")
  self.assertEqual(info_frame.infoVars["Lens"].get(), "New Lens 24-70mm")
  self.assertEqual(info_frame.infoVars["Firmware version"].get(), "2.00")

 def test_filter_selection_rebuild_retention_across_chunks(self):
  root = self.make_ui()
  root.clearLog()

  # 1,500 lines all matching "event" (crosses the 1,000-line chunk threshold)
  root.log("".join("event line %04d\n" % i for i in range(1500)))

  text = root.logText.text
  # Select a line beyond the first 1,000-line chunk (e.g. line 1200)
  text.tag_add("sel", "1200.0", "1201.0")
  self.assertTrue(bool(text.tag_ranges("sel")))

  # Trigger filterLogDisplay and settle all chunks
  root.logFilterVar.set("event")
  root.filterLogDisplay()
  deadline = time.monotonic() + 2.0
  while (getattr(root, "_logFilterAfterId", None) or getattr(root, "_logFilterChunkAfterId", None)) and time.monotonic() < deadline:
   root.update()
   time.sleep(0.01)
  root.update()

  # Selection range and paused autoScroll must be preserved across the multi-chunk filter rebuild
  sel_ranges = list(text.tag_ranges("sel"))
  self.assertEqual(len(sel_ranges), 2)
  self.assertIn("event line 1199", text.get(sel_ranges[0], sel_ranges[1]))
  self.assertFalse(root.autoScroll)


if __name__ == "__main__":
 unittest.main()
