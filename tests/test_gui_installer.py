import contextlib
import io
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class GuiInstallerTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  path = Path(__file__).resolve().parents[1] / 'pmca-gui.py'
  cls.gui = runpy.run_path(str(path))['main'].__globals__

 def setUp(self):
  self.output = contextlib.redirect_stdout(io.StringIO())
  self.output.__enter__()
  self.addCleanup(self.output.__exit__, None, None, None)
  self.temp = TemporaryDirectory()
  self.addCleanup(self.temp.cleanup)
  self.apk = Path(self.temp.name) / 'selected.apk'
  self.apk.write_bytes(b'not an APK')
  self.ui = SimpleNamespace(
   master=SimpleNamespace(driverName='libusb', setCameraBusy=Mock()),
   MODE_APP=0, MODE_APK=1, installButton=Mock(), infoButton=Mock(),
   getMode=Mock(return_value=1),
   getSelectedApk=Mock(return_value=str(self.apk)),
   getSelectedApp=Mock(return_value=None),
   showCameraInfo=Mock(), updateProgress=Mock(), showInstallResult=Mock(), setApkFile=Mock(),
   downloadButton=Mock(),
   run=lambda func: func(),
  )
  self.install = Mock()
  self.confirm = Mock(return_value=True)
  self.error = Mock()
  self.parser = Mock()
  self.parser.return_value.getMinSdkVersion.return_value = 10
  self.parser.return_value.getPackageName.return_value = 'com.example.camera'
  self.patches = patch.dict(self.gui, {
   'installCommand': self.install, 'askyesno': self.confirm,
   'showerror': self.error,
  })
  self.patches.__enter__()
  self.addCleanup(self.patches.__exit__, None, None, None)
  self.mock_bg_sync = patch.object(self.gui['InstallerFrame'], 'startBackgroundSync', Mock())
  self.mock_bg_sync.start()
  self.addCleanup(self.mock_bg_sync.stop)

 def test_empty_apk_selection_does_not_start_installation(self):
  self.ui.getSelectedApk.return_value = ''
  task = self.gui['InstallTask'](self.ui)
  args = task.doBefore()
  self.assertIsNone(args)
  task.do(args)
  self.install.assert_not_called()

 def test_invalid_apk_does_not_start_installation(self):
  task = self.gui['InstallTask'](self.ui)
  args = task.doBefore()
  self.assertIsNone(args)
  task.do(args)
  self.install.assert_not_called()

 def test_missing_package_identifier_is_rejected_before_confirmation(self):
  self.parser.return_value.getPackageName.return_value = ''
  with patch.dict(self.gui, {'ApkParser': self.parser}):
   task = self.gui['InstallTask'](self.ui)
   args = task.doBefore()
  self.assertIsNone(args)
  task.do(args)
  self.install.assert_not_called()
  self.confirm.assert_not_called()

 def test_installed_bytes_are_the_validated_snapshot(self):
  uploaded = []
  self.install.side_effect = lambda **kwargs: uploaded.append(kwargs['apkFile'].read())
  with patch.dict(self.gui, {'ApkParser': self.parser}):
   task = self.gui['InstallTask'](self.ui)
   args = task.doBefore()
  self.apk.write_bytes(b'different APK after confirmation')
  task.do(args)
  self.assertEqual(uploaded, [b'not an APK'])

 def test_canceled_confirmation_does_not_start_installation(self):
  self.confirm.return_value = False
  with patch.dict(self.gui, {'ApkParser': self.parser}):
   task = self.gui['InstallTask'](self.ui)
   args = task.doBefore()
  self.assertIsNone(args)
  task.do(args)
  self.install.assert_not_called()

 def test_newer_android_sdk_is_rejected_before_camera_access(self):
  for sdk in [0, -1, 30]:
   with self.subTest(sdk=sdk):
    self.parser.return_value.getMinSdkVersion.return_value = sdk
    with patch.dict(self.gui, {'ApkParser': self.parser}):
     task = self.gui['InstallTask'](self.ui)
     args = task.doBefore()
    self.assertIsNone(args)
    task.do(args)
    self.install.assert_not_called()

 def test_confirmed_apk_uses_selected_usb_backend(self):
  with patch.dict(self.gui, {'ApkParser': self.parser}):
   task = self.gui['InstallTask'](self.ui)
   task.do(task.doBefore())
  self.install.assert_called_once()
  kwargs = self.install.call_args.kwargs
  self.assertEqual(kwargs.get('driverName'), 'libusb')
  self.assertEqual(kwargs['apkFile'].read(), b'not an APK')

 def test_finished_install_restores_camera_controls(self):
  with patch.dict(self.gui, {'ApkParser': self.parser}):
   task = self.gui['InstallTask'](self.ui)
   result = task.do(task.doBefore())
   task.doAfter(result)
  self.ui.master.setCameraBusy.assert_called_with(False)

 def test_canceled_mac_capture_confirmation_does_not_query_camera(self):
  info = Mock()
  self.confirm.return_value = False
  with patch('sys.platform', 'darwin'), patch('sys.frozen', True, create=True), \
       patch.dict(self.gui, {'infoCommand': info}):
   task = self.gui['InfoTask'](self.ui)
   task.doAfter(task.do(task.doBefore()))
  info.assert_not_called()
  self.ui.master.setCameraBusy.assert_not_called()

 def test_camera_info_uses_selected_usb_backend(self):
  info = Mock()
  with patch.dict(self.gui, {'infoCommand': info}):
   task = self.gui['InfoTask'](self.ui)
   task.do(task.doBefore())
  info.assert_called_once_with('libusb')

 def test_download_cancel_does_not_request_network(self):
  cls = self.gui.get('RecipeDownloadTask')
  self.assertIsNotNone(cls)
  download = Mock()
  with patch.dict(self.gui, {'asksaveasfilename': Mock(return_value=''), 'downloadRecipeLab': download}):
   task = cls(self.ui)
   task.doAfter(task.do(task.doBefore()))
  download.assert_not_called()
  self.ui.master.setCameraBusy.assert_not_called()

 def test_download_selects_validated_file_but_does_not_install(self):
  cls = self.gui.get('RecipeDownloadTask')
  self.assertIsNotNone(cls)
  result = {'path': str(self.apk), 'version': 'v1.6.2', 'bytes': 322372, 'package': 'com.voxivoid.recipelab'}
  download = Mock(return_value=result)
  with patch.dict(self.gui, {'asksaveasfilename': Mock(return_value=str(self.apk)), 'downloadRecipeLab': download}):
   task = cls(self.ui)
   task.doAfter(task.do(task.doBefore()))
  self.ui.setApkFile.assert_called_once_with(str(self.apk))
  self.install.assert_not_called()
  self.ui.master.setCameraBusy.assert_called_with(False)

 def test_install_failure_does_not_show_completed_status(self):
  self.install.return_value = None
  with patch.dict(self.gui, {'ApkParser': self.parser}):
   task = self.gui['InstallTask'](self.ui)
   task.doAfter(task.do(task.doBefore()))
  self.ui.showInstallResult.assert_called_once_with(False)

 def test_camera_info_result_updates_summary_after_worker(self):
  data = {'Model': 'ILCE-7', 'Firmware version': '3.20'}
  with patch.dict(self.gui, {'infoCommand': Mock(return_value=data)}):
   task = self.gui['InfoTask'](self.ui)
   task.doAfter(task.do(task.doBefore()))
  self.ui.showCameraInfo.assert_called_once_with(data)

 def test_failed_camera_info_does_not_display_success(self):
  with patch.dict(self.gui, {'infoCommand': Mock(return_value=None)}):
   task = self.gui['InfoTask'](self.ui)
   task.doAfter(task.do(task.doBefore()))
  self.ui.showCameraInfo.assert_called_once_with(None)

 def test_partial_log_writes_are_buffered_until_newline(self):
  text = Mock()
  root = SimpleNamespace(logText=SimpleNamespace(text=text), logBuffers={False: '', True: ''})
  self.gui['MainUi'].log(root, 'partial')
  text.insert.assert_not_called()
  self.gui['MainUi'].log(root, ' line\n')
  self.assertEqual(text.insert.call_count, 1)
  self.assertIn('partial line\n', text.insert.call_args.args[1])
  import re
  self.assertRegex(text.insert.call_args.args[1], r'^\[\d\d:\d\d:\d\d\] ')

 def test_log_errors_have_error_tag(self):
  import inspect
  method = self.gui['MainUi'].log
  self.assertIn('error', inspect.signature(method).parameters)
  text = Mock()
  root = SimpleNamespace(logText=SimpleNamespace(text=text), logBuffers={False: '', True: ''})
  method(root, 'traceback details\n', error=True)
  self.assertEqual(text.insert.call_args.args[2], 'error')

 def test_camera_actions_disable_both_usb_controls(self):
  method = getattr(self.gui['MainUi'], 'setCameraBusy', None)
  self.assertIsNotNone(method)
  info = Mock()
  install = Mock()
  root = SimpleNamespace(
   infoFrame=SimpleNamespace(infoButton=info),
   installerFrame=SimpleNamespace(installButton=install),
  )
  method(root, True)
  info.config.assert_called_with(state='disabled')
  install.config.assert_called_with(state='disabled')
  method(root, False)
  info.config.assert_called_with(state='normal')
  install.config.assert_called_with(state='normal')

 def test_preview_does_not_enable_unverified_camera_actions_after_download(self):
  info, install, download, choose = Mock(), Mock(), Mock(), Mock()
  root = SimpleNamespace(cameraActionsEnabled=False,
   infoFrame=SimpleNamespace(infoButton=info),
   installerFrame=SimpleNamespace(installButton=install, downloadButton=download, apkSelectButton=choose))
  self.gui['MainUi'].setCameraBusy(root, False)
  info.config.assert_called_with(state='disabled')
  install.config.assert_called_with(state='disabled')
  download.config.assert_called_with(state='normal')
  choose.config.assert_called_with(state='normal')

 def test_close_does_not_destroy_window_during_usb_operation(self):
  close = getattr(self.gui['MainUi'], 'close', None)
  self.assertIsNotNone(close)
  root = SimpleNamespace(cameraBusy=True, destroy=Mock())
  close(root)
  root.destroy.assert_not_called()

 def test_close_destroys_idle_window(self):
  close = getattr(self.gui['MainUi'], 'close', None)
  self.assertIsNotNone(close)
  root = SimpleNamespace(cameraBusy=False, destroy=Mock())
  close(root)
  root.destroy.assert_called_once()

 def test_windowed_log_stream_flush_without_console(self):
  writes = []
  stream = self.gui['PrintRedirector'](writes.append, None)
  stream.write('Camera log')
  error = None
  try:
   stream.flush()
  except AttributeError as e:
   error = e
  self.assertIsNone(error)
  self.assertEqual(writes, ['Camera log'])

 def test_runtime_check_writes_report_without_opening_window(self):
  report = Path(self.temp.name) / 'runtime.json'
  window = Mock()
  with patch('sys.argv', ['Sony Open PMCA', '--check-runtime', str(report)]), \
       patch.dict(self.gui, {'MainUi': window}):
   self.gui['main']()
  window.assert_not_called()
  self.assertTrue(report.exists())
  import json
  result = json.loads(report.read_text())
  self.assertTrue(result['spk_roundtrip'])
  self.assertTrue(result['libusb_loads'])
  self.assertTrue(result['certificate_key_parses'])
  self.assertTrue(result['tcl_version'])

 def test_runtime_report_identifies_library_used_by_pyusb(self):
  import usb.backend.libusb1
  report = Path(self.temp.name) / 'runtime.json'
  library = SimpleNamespace(_name='/test-bundle/libusb-1.0.0.dylib', libusb_get_version=Mock())
  with patch.object(usb.backend.libusb1, '_load_library', return_value=library):
   self.gui['checkRuntime'](str(report))
  import json
  result = json.loads(report.read_text())
  self.assertEqual(result.get('libusb_path'), '/test-bundle/libusb-1.0.0.dylib')

 def test_mac_launch_uses_installer_only_window(self):
  window = Mock()
  with patch('sys.platform', 'darwin'), patch.dict(self.gui, {'MainUi': window}):
   self.gui['main']()
  self.assertTrue(window.call_args.kwargs.get('installerOnly'))
  self.assertTrue(window.call_args.args[0].startswith('Sony Open PMCA'))
  window.return_value.mainloop.assert_called_once()


 def test_catalog_download_no_selection_shows_error(self):
  cls = self.gui.get('CatalogAppDownloadTask')
  self.assertIsNotNone(cls)
  self.ui.getSelectedApp.return_value = None
  task = cls(self.ui)
  args = task.doBefore()
  self.assertIsNone(args)
  self.error.assert_called_once()
  self.ui.master.setCameraBusy.assert_not_called()

 def test_catalog_download_cancel_does_not_call_network(self):
  cls = self.gui.get('CatalogAppDownloadTask')
  app = SimpleNamespace(name='Tweak', package='com.github.ma1co.openmemories.tweak', release=Mock())
  self.ui.getSelectedApp.return_value = app
  with patch.dict(self.gui, {'asksaveasfilename': Mock(return_value='')}):
   task = cls(self.ui)
   args = task.doBefore()
  self.assertIsNone(args)
  app.release.assert_not_called()
  self.ui.master.setCameraBusy.assert_not_called()

 def test_catalog_download_valid_apk_sets_apk_and_progress(self):
  cls = self.gui.get('CatalogAppDownloadTask')
  out_path = Path(self.temp.name) / 'downloaded.apk'
  release = SimpleNamespace(version='v1.0', url='https://github.com/example/app/releases/download/v1.0/app.apk')
  app = SimpleNamespace(name='OpenMemories Tweak', package='com.github.ma1co.openmemories.tweak', release=release)
  self.ui.getSelectedApp.return_value = app
  mock_result = {'path': str(out_path), 'package': app.package, 'version': 'v1.0', 'bytes': 12345, 'name': app.name}
  with patch.dict(self.gui, {
   'asksaveasfilename': Mock(return_value=str(out_path)),
   'downloadCatalogApp': Mock(return_value=mock_result),
  }):
   task = cls(self.ui)
   args = task.doBefore()
   self.assertIsNotNone(args)
   result = task.do(args)
   task.doAfter(result)
  self.ui.setApkFile.assert_called_once_with(str(out_path))
  self.ui.master.setCameraBusy.assert_called_with(False)
  self.ui.updateProgress.assert_called_with(100, 'OpenMemories Tweak downloaded and validated; not installed')

 def test_catalog_download_invalid_apk_does_not_set_apk_file(self):
  cls = self.gui.get('CatalogAppDownloadTask')
  out_path = Path(self.temp.name) / 'corrupt.apk'
  release = SimpleNamespace(version='v1.0', url='https://github.com/example/bad/releases/download/v1.0/bad.apk')
  app = SimpleNamespace(name='Bad App', package='com.example.bad', release=release)
  self.ui.getSelectedApp.return_value = app
  with patch.dict(self.gui, {
   'asksaveasfilename': Mock(return_value=str(out_path)),
   'downloadCatalogApp': Mock(side_effect=ValueError('Invalid APK')),
  }):
   task = cls(self.ui)
   args = task.doBefore()
   result = task.do(args)
   task.doAfter(result)
  self.ui.setApkFile.assert_not_called()
  self.ui.master.setCameraBusy.assert_called_with(False)
  self.ui.updateProgress.assert_called_with(0, 'Download failed; check Activity log')

 def test_download_catalog_app_insecure_url_rejected(self):
  fn = self.gui.get('downloadCatalogApp')
  self.assertIsNotNone(fn)
  release = SimpleNamespace(version='1.0', url='http://insecure.example.com/app.apk')
  app = SimpleNamespace(name='App', package='com.example.app', release=release)
  with self.assertRaises(ValueError) as ctx:
   fn(app, str(Path(self.temp.name) / 'out.apk'))
  self.assertIn('insecure', str(ctx.exception).lower())

 def test_download_catalog_app_package_mismatch_rejected(self):
  fn = self.gui.get('downloadCatalogApp')
  self.assertIsNotNone(fn)
  out_path = Path(self.temp.name) / 'out.apk'
  out_path.write_bytes(b'original bytes')
  release = SimpleNamespace(version='1.0', url='https://github.com/example/app/download/app.apk')
  app = SimpleNamespace(name='App', package='com.expected.package', release=release)
  bad_parser = Mock()
  bad_parser.return_value.getPackageName.return_value = 'com.different.package'
  bad_parser.return_value.getMinSdkVersion.return_value = 9
  
  class MockResponse:
   def __init__(self):
    self.headers = {'Content-Length': '10'}
    self.read_count = 0
   def read(self, size):
    if self.read_count == 0:
     self.read_count += 1
     return b'0123456789'
    return b''
   def __enter__(self): return self
   def __exit__(self, *args): pass

  with patch('urllib.request.OpenerDirector.open', return_value=MockResponse()), \
       patch('pmca.appstore.catalog.ApkParser', bad_parser), \
       patch.dict(self.gui, {'ApkParser': bad_parser}):
   with self.assertRaises(ValueError) as ctx:
    fn(app, str(out_path))
   self.assertIn('mismatch', str(ctx.exception).lower())
  # Original destination file is preserved untouched
  self.assertEqual(out_path.read_bytes(), b'original bytes')

 def test_show_passive_usb_updates_and_clears_fields(self):
  variables = {'Model': Mock(), 'USB mode': Mock(), 'Serial number': Mock()}
  status = Mock()
  frame = SimpleNamespace(infoVars=variables, infoStatus=status)
  dev = {'name': 'ILCE-7', 'vendor': 'Sony (0x054c)', 'serial': '0123456789AB', 'mode': 'MTP / PTP (Class 6/1/1)'}
  self.gui['InfoFrame'].showPassiveUsb(frame, dev)
  variables['Model'].set.assert_called_with('ILCE-7')
  variables['USB mode'].set.assert_called_with('MTP / PTP (Class 6/1/1)')
  variables['Serial number'].set.assert_called_with('0123456789AB')
  self.assertIn('ILCE-7', status.set.call_args.args[0])

  # Clearing when None
  self.gui['InfoFrame'].showPassiveUsb(frame, None)
  variables['Model'].set.assert_called_with('—')
  variables['USB mode'].set.assert_called_with('—')
  variables['Serial number'].set.assert_called_with('—')
  self.assertIn('No Sony camera detected', status.set.call_args.args[0])

 def test_copy_errors_captures_tagged_error_ranges(self):
  import tkinter as tk
  try:
   root = tk.Tk()
   root.withdraw()
  except Exception:
   return
  try:
   text_widget = tk.Text(root)
   text_widget.insert('1.0', '[12:00:00] Normal info line\n')
   text_widget.insert('end', '[12:00:01] Error: failed connecting\nTraceback line 1\n', 'error')
   text_widget.insert('end', '[12:00:02] Another info line\n')
   root_obj = SimpleNamespace(
    logText=SimpleNamespace(text=text_widget),
    rawLogEntries=[
     ('12:00:00', 'Normal info line', 'info'),
     ('12:00:01', 'Error: failed connecting', 'error'),
     ('12:00:01', 'Traceback line 1', 'error'),
     ('12:00:02', 'Another info line', 'info'),
    ],
    clipboard_clear=Mock(),
    clipboard_append=Mock(),
   )
   self.gui['MainUi'].copyErrors(root_obj)
   root_obj.clipboard_clear.assert_called_once()
   copied = root_obj.clipboard_append.call_args.args[0]
   self.assertIn('failed connecting', copied)
   self.assertIn('Traceback line 1', copied)
   self.assertNotIn('Normal info line', copied)
  finally:
   root.destroy()

 def test_busy_guards_disable_and_restore_all_catalog_buttons(self):
  method = getattr(self.gui['MainUi'], 'setCameraBusy', None)
  self.assertIsNotNone(method)
  info = Mock()
  install = Mock()
  download = Mock()
  choose = Mock()
  load_btn = Mock()
  app_dl_btn = Mock()
  combo = Mock()
  installer = SimpleNamespace(
   installButton=install,
   downloadButton=download,
   apkSelectButton=choose,
   appLoadButton=load_btn,
   appDownloadButton=app_dl_btn,
   appCombo=combo,
   getSelectedApp=Mock(return_value=None),
  )
  root = SimpleNamespace(
   cameraActionsEnabled=True,
   infoFrame=SimpleNamespace(infoButton=info),
   installerFrame=installer,
  )
  method(root, True)
  info.config.assert_called_with(state='disabled')
  install.config.assert_called_with(state='disabled')
  download.config.assert_called_with(state='disabled')
  choose.config.assert_called_with(state='disabled')
  load_btn.config.assert_called_with(state='disabled')
  app_dl_btn.config.assert_called_with(state='disabled')
  combo.config.assert_called_with(state='disabled')

  method(root, False)
  info.config.assert_called_with(state='normal')
  install.config.assert_called_with(state='normal')
  download.config.assert_called_with(state='normal')
  choose.config.assert_called_with(state='normal')
  load_btn.config.assert_called_with(state='normal')
  app_dl_btn.config.assert_called_with(state='disabled')

  combo.config.assert_called_with(state='readonly')
  installer.getSelectedApp.return_value = SimpleNamespace(name='App')
  method(root, False)
  app_dl_btn.config.assert_called_with(state='normal')
  combo.config.assert_called_with(state='readonly')

 def test_installer_frame_catalog_load_and_select(self):
  import tkinter as tk
  try:
   root = tk.Tk()
   root.withdraw()
  except Exception:
   return
  try:
   root.installerOnly = True
   root.cameraActionsEnabled = False
   frame = self.gui['InstallerFrame'](root)
   self.assertIsNotNone(frame.apkPanel)
   self.assertIsNotNone(frame.catalogPanel)
   self.assertIsNotNone(frame.appCombo)
   self.assertIsNotNone(frame.appLoadButton)
   self.assertIsNotNone(frame.appDownloadButton)
   self.assertEqual(str(frame.appDownloadButton['state']), 'disabled')

   app1 = SimpleNamespace(name='App One', author='Dev A', package='com.app.one', desc='First app')
   app2 = SimpleNamespace(name='App Two', author='Dev B', package='com.app.two', desc='Second app')
   frame.setAppList([app1, app2])
   self.assertIn('App One', frame.appCombo['values'])
   self.assertIn('App Two', frame.appCombo['values'])
   self.assertIsNone(frame.getSelectedApp())

   frame.appCombo.current(1)
   frame.onAppSelected()
   self.assertEqual(frame.getSelectedApp(), app1)
   self.assertEqual(str(frame.appDownloadButton['state']), 'normal')
   self.assertIn('App One by Dev A', frame.appDetailVar.get())

   frame.setAppList([])
   self.assertIsNone(frame.getSelectedApp())
   self.assertEqual(str(frame.appDownloadButton['state']), 'disabled')
  finally:
   root.destroy()


 def test_catalog_cache_atomic_save_and_load(self):
  from pmca.appstore.catalog import loadCatalog, saveCatalog
  cache_file = Path(self.temp.name) / 'cache.json'
  cat = {'test.pkg': {'name': 'Test', 'package': 'test.pkg', 'version': '1.0'}}
  saveCatalog(cat, cachePath=str(cache_file))
  self.assertTrue(cache_file.exists())
  loaded = loadCatalog(cachePath=str(cache_file))
  self.assertEqual(loaded['test.pkg']['version'], '1.0')

 def test_sync_catalog_metadata_abort_event(self):
  import threading
  from pmca.appstore.catalog import syncCatalogMetadata
  abort = threading.Event()
  abort.set()
  cat, updated = syncCatalogMetadata(abort_event=abort)
  self.assertFalse(updated)

 def test_camera_monitor_lifecycle(self):
  main_ui = SimpleNamespace(
   cameraConnected=False,
   cameraActionsEnabled=False,
   cameraBusy=False,
   installerOnly=True,
   usbStatusVar=Mock(),
   setCameraBusy=Mock(),
   infoFrame=SimpleNamespace(showConnectedCamera=Mock()),
  )
  # When connected info arrives with verified app connection:
  info = {'name': 'ILCE-7', 'mode': 'MTP', 'vendor': 'Sony (0x054c)', 'connected': True, 'appConnected': True}
  self.gui['MainUi'].onCameraStatusUpdate(main_ui, info)
  self.assertTrue(main_ui.cameraConnected)
  self.assertTrue(main_ui.cameraActionsEnabled)
  main_ui.infoFrame.showConnectedCamera.assert_called_with(info)
  self.assertIn('ILCE-7', main_ui.usbStatusVar.set.call_args.args[0])

  # When USB present but app MTP connection unavailable (status-denied counterexample):
  denied_info = {'name': 'ILCE-7', 'mode': 'MTP', 'vendor': 'Sony (0x054c)', 'connected': False, 'appConnected': False, 'status': 'USB detected, app connection unavailable'}
  self.gui['MainUi'].onCameraStatusUpdate(main_ui, denied_info)
  self.assertFalse(main_ui.cameraConnected)
  self.assertFalse(main_ui.cameraActionsEnabled)
  self.assertIn('unavailable', main_ui.usbStatusVar.set.call_args.args[0])

  # When fully disconnected:
  self.gui['MainUi'].onCameraStatusUpdate(main_ui, None)
  self.assertFalse(main_ui.cameraConnected)
  self.assertFalse(main_ui.cameraActionsEnabled)
  main_ui.infoFrame.showConnectedCamera.assert_called_with(None)
  self.assertIn('Disconnected', main_ui.usbStatusVar.set.call_args.args[0])

 def test_download_store_app_guard_against_missing_url(self):
  frame = SimpleNamespace(
   catalog={'com.app.no_url': {'name': 'No URL App', 'url': None}},
   master=SimpleNamespace(),
  )
  with patch.dict(self.gui, {'showerror': self.error, 'asksaveasfilename': Mock()}):
   self.gui['InstallerFrame'].downloadStoreApp(frame, 'com.app.no_url')
  self.error.assert_called_once()
  self.assertIn('unavailable', self.error.call_args.args[0].lower())


 def test_runtime_check_tls_handshake_failure_reports_false(self):
  report = Path(self.temp.name) / 'runtime_fail.json'
  with patch('pmca.marketserver.server.verify_tls_handshake', return_value={'success': False, 'error': 'simulated failure'}):
   self.gui['checkRuntime'](str(report))
  import json
  res = json.loads(report.read_text())
  self.assertFalse(res['tls_handshake_verified'])
  self.assertEqual(res.get('tls_error'), 'simulated failure')

 def test_runtime_check_tls_handshake_success_reports_true_and_telemetry(self):
  report = Path(self.temp.name) / 'runtime_success.json'
  with patch('pmca.marketserver.server.verify_tls_handshake', return_value={'success': True, 'cipher': 'AES256-SHA', 'version': 'TLSv1.2'}):
   self.gui['checkRuntime'](str(report))
  import json
  res = json.loads(report.read_text())
  self.assertTrue(res['tls_handshake_verified'])
  self.assertEqual(res.get('tls_cipher'), 'AES256-SHA')
  self.assertEqual(res.get('tls_version'), 'TLSv1.2')


 def test_main_ui_camera_monitor_publication_on_main_thread(self):
  import time
  ready_info = {
   'connected': True,
   'physicalDetected': True,
   'appConnected': True,
   'status': 'ready',
   'mode': 'MTP',
   'name': 'ILCE-7',
   'model': 'ILCE-7',
   'vendor': 'Sony (0x054c)',
   'serial': '12345678',
   'firmware_version': '3.20',
  }
  with patch('pmca.appstore.catalog.syncCatalogMetadata', return_value=({}, False)),        patch.dict(self.gui, {
        'checkCameraConnection': Mock(return_value=ready_info),
        'syncCatalogMetadata': Mock(return_value=({}, False)),
       }):
   root = self.gui['MainUi']('Test Startup', installerOnly=True)
   root.withdraw()
   start = time.time()
   while not root.cameraConnected and time.time() - start < 2.0:
    root.update()
    time.sleep(0.05)
   self.assertTrue(root.cameraConnected)
   self.assertIn('Connected: ILCE-7', root.usbStatusVar.get())
   self.assertEqual(root.infoFrame.infoVars['Model'].get(), 'ILCE-7')
   # P0 regression verification: Panel status must match header and installButton disabled without APK
   self.assertIn('ILCE-7', root.installerFrame.apkStatusNote.get())
   self.assertEqual(str(root.installerFrame.installButton['state']), 'disabled')
   # Staging a valid signed APK enables installButton
   valid_apk = Path(self.temp.name) / 'valid_signed.apk'
   from tests.apk_fixture import apkFixture
   valid_apk.write_bytes(apkFixture(signed=True))
   root.installerFrame.setApkFile(str(valid_apk))
   self.assertEqual(str(root.installerFrame.installButton['state']), 'normal')
   root.close()

 def test_reconnect_button_transition_disconnected_to_ready(self):
  import time
  ready_info = {
   'connected': True,
   'physicalDetected': True,
   'appConnected': True,
   'status': 'ready',
   'mode': 'MTP',
   'name': 'ILCE-7',
   'model': 'ILCE-7',
   'vendor': 'Sony (0x054c)',
   'serial': '12345678',
   'firmware_version': '3.20',
  }
  check_mock = Mock(return_value=None)
  with patch('pmca.appstore.catalog.syncCatalogMetadata', return_value=({}, False)),        patch.dict(self.gui, {
        'checkCameraConnection': check_mock,
        'syncCatalogMetadata': Mock(return_value=({}, False)),
       }):
   root = self.gui['MainUi']('Test Reconnect', installerOnly=True)
   root.withdraw()
   root.update()
   self.assertFalse(root.cameraConnected)
   self.assertIn('Disconnected', root.usbStatusVar.get())
   
   check_mock.return_value = ready_info
   root.reconnectButton.invoke()
   start = time.time()
   while not root.cameraConnected and time.time() - start < 2.0:
    root.update()
    time.sleep(0.05)
   self.assertTrue(root.cameraConnected)
   self.assertIn('Connected: ILCE-7', root.usbStatusVar.get())
   self.assertEqual(root.infoFrame.infoVars['Model'].get(), 'ILCE-7')
   root.close()


 def test_camera_snapshot_merge_across_heartbeat_detail_and_disconnect(self):
  root = self.gui['MainUi']('Test Snapshot Merge', installerOnly=True)
  root.withdraw()
  info_frame = root.infoFrame

  # Phase 1: Heartbeat full status arrives
  heartbeat_full = {
   'name': 'ILCE-7',
   'model': 'ILCE-7',
   'vendor': 'Sony (0x054c)',
   'mode': 'MTP',
   'serial': '12345678',
   'raw_serial': '00000000000000003282630012345678',
   'ptp_device_version': '3.0',
   'appConnected': True,
   'physicalDetected': True,
   'status': 'ready',
   'shutter_count': {'available': False, 'reason': 'Direct counter not exposed over read-only MTP'},
   'capabilities': [0x9280, 0x9281],
   'properties': [0x5001, 0xd001],
  }
  info_frame.showConnectedCamera(heartbeat_full)
  root.update()

  self.assertEqual(info_frame.infoVars['Model'].get(), 'ILCE-7')
  self.assertEqual(info_frame.infoVars['Vendor'].get(), 'Sony (0x054c)')
  self.assertEqual(info_frame.infoVars['USB mode'].get(), 'MTP')
  self.assertEqual(info_frame.infoVars['Serial number'].get(), '12345678')
  self.assertEqual(info_frame.infoVars['PTP version'].get(), 'PTP v3.0')
  self.assertEqual(info_frame.infoVars['Firmware version'].get(), 'Unavailable without query')
  self.assertEqual(info_frame.infoVars['PTP descriptor'].get(), '00000000000000003282630012345678')
  self.assertIn('not exposed', info_frame.infoVars['Shutter count'].get())
  self.assertIn('not exposed', info_frame.infoVars['Shutter note'].get())
  self.assertIn('2 operations', info_frame.infoVars['PTP Capabilities'].get())

  # Phase 2: User triggers 'Get camera info', returning partial detail data (e.g. Lens, Product code)
  detail_partial = {
   'Model': 'ILCE-7',
   'Product code': '0032826300',
   'Serial number': '12345678',
   'Firmware version': 'Unavailable (read-only MTP)',
   'Lens': 'Model 0x10a08011 (Firmware 1.04)',
   'USB mode': 'MTP',
  }
  info_frame.showCameraInfo(detail_partial)
  root.update()

  # Assert fields from heartbeat were NOT wiped by detail_partial
  self.assertEqual(info_frame.infoVars['Vendor'].get(), 'Sony (0x054c)')
  self.assertIn('not exposed', info_frame.infoVars['Shutter count'].get())
  self.assertIn('2 operations', info_frame.infoVars['PTP Capabilities'].get())
  self.assertEqual(info_frame.infoVars['Product code'].get(), '0032826300')
  self.assertEqual(info_frame.infoVars['Lens'].get(), 'Model 0x10a08011 (Firmware 1.04)')

  # Phase 3: Next heartbeat runs with partial heartbeat data (no lens or product code)
  heartbeat_partial = {
   'name': 'ILCE-7',
   'vendor': 'Sony (0x054c)',
   'mode': 'MTP',
   'serial': '12345678',
   'appConnected': True,
  }
  info_frame.showConnectedCamera(heartbeat_partial)
  root.update()

  # Assert Lens and Product code from Phase 2 are preserved
  self.assertEqual(info_frame.infoVars['Product code'].get(), '0032826300')
  self.assertEqual(info_frame.infoVars['Lens'].get(), 'Model 0x10a08011 (Firmware 1.04)')
  self.assertEqual(info_frame.infoVars['Vendor'].get(), 'Sony (0x054c)')

  # Phase 4: Disconnect happens
  info_frame.showConnectedCamera(None)
  root.update()

  # Assert all fields are reset to '—'
  for key, var in info_frame.infoVars.items():
   self.assertEqual(var.get(), '—', f"Field {key} was not reset on disconnect")

  root.close()


 def test_show_install_result_with_device_and_application_acknowledgment(self):
  frame = SimpleNamespace(progressBar=Mock(), progressText=Mock())
  result = {
   'deviceinfo': {'name': 'ILCE-7'},
   'applications': [{'name': 'RecipeLab', 'version': '1.6.2'}],
  }
  self.gui['InstallerFrame'].showInstallResult(frame, result)
  frame.progressText.set.assert_called_once_with('Successfully installed RecipeLab 1.6.2 on ILCE-7!')


 def test_store_searchbar_removed_logs_search_preserved_and_scroll_reaches_all_apps(self):
  with patch('pmca.appstore.catalog.syncCatalogMetadata', return_value=({}, False)), \
       patch.dict(self.gui, {'checkCameraConnection': Mock(return_value=None)}):
   root = self.gui['MainUi']('Test Scroll and Headings', installerOnly=True)
   root.update()
   frame = root.installerFrame
   frame.update_idletasks()

   # 1. Verify Application Store has NO search entry
   self.assertFalse(hasattr(frame, "searchEntry"))

   # 2. Verify Activity Logs HAS search filter var and entry widget
   self.assertTrue(hasattr(root, "logFilterEntry"))
   root.notebook.select(root.activityFrame)
   root.update()
   self.assertTrue(root.logFilterEntry.winfo_ismapped())

   # 3. Test scrolling via _onMouseWheel with Darwin delta -1 and +1
   root.notebook.select(frame)
   root.update()
   initial_yview = frame.canvas.yview()
   from types import SimpleNamespace
   frame._onMouseWheel(SimpleNamespace(delta=-1))
   root.update()
   down_yview = frame.canvas.yview()
   self.assertGreater(down_yview[0], initial_yview[0])

   frame._onMouseWheel(SimpleNamespace(delta=1))
   root.update()
   up_yview = frame.canvas.yview()
   self.assertLessEqual(up_yview[0], down_yview[0])

   # 4. Verify all 12 apps have rendered rows
   from pmca.appstore.catalog import loadCatalog
   self.assertEqual(len(frame.cardDownloadButtons), len(loadCatalog()))
   root.close()


 def test_identity_change_clears_previous_details_and_960x640_button_geometry(self):
  with patch('pmca.appstore.catalog.syncCatalogMetadata', return_value=({}, False)), \
       patch.dict(self.gui, {'checkCameraConnection': Mock(return_value=None)}):
   root = self.gui['MainUi']('Test 960x640 Buttons & Identity Change', installerOnly=True)
   root.geometry("960x640")
   root.update()

   info_frame = root.infoFrame
   root.notebook.select(info_frame)
   root.update()

   # Phase 1: Camera 1 connected with long lens, raw descriptor, flash warning
   cam1_full = {
    'name': 'ILCE-7',
    'model': 'ILCE-7',
    'vendor': 'Sony (0x054c)',
    'mode': 'MTP',
    'serial': '12345678',
    'raw_serial': '00000000000000003282630012345678',
    'lens': 'SEL2870 28–70mm F3.5–5.6 OSS, firmware 1.04',
    'ptp_device_version': '3.0',
    'appConnected': True,
    'physicalDetected': True,
    'status': 'ready',
    'shutter_count': {
     'available': True,
     'value': 4464,
     'ambiguous': True,
     'provenance': 'DSC00042.JPG Tag 0x9050',
     'date': '2026:10:11',
     'warning': 'Flash image (modulo 65,536)',
    },
    'capabilities': [0x9280, 0x9281],
    'properties': [0x5001, 0xd001],
   }
   info_frame.showConnectedCamera(cam1_full)
   root.update()

   self.assertEqual(info_frame.infoVars['Model'].get(), 'ILCE-7')
   self.assertEqual(info_frame.infoVars['Serial number'].get(), '12345678')
   self.assertEqual(info_frame.infoVars['PTP descriptor'].get(), '00000000000000003282630012345678')
   self.assertEqual(info_frame.infoVars['Lens'].get(), 'SEL2870 28–70mm F3.5–5.6 OSS, firmware 1.04')
   self.assertIn('4,464', info_frame.infoVars['Shutter count'].get())
   self.assertIn('modulo 65,536', info_frame.infoVars['Shutter count'].get())
   self.assertIn('flash', info_frame.infoVars['Shutter note'].get().lower())

   # Assert bottom buttons are fully mapped and within 960x640 window bounds
   btn = info_frame.infoButton
   self.assertTrue(btn.winfo_ismapped())
   btn_y = btn.winfo_rooty() - root.winfo_rooty()
   btn_h = btn.winfo_height()
   self.assertLess(btn_y + btn_h, root.winfo_height())

   # Phase 2: Same camera partial heartbeat preserves lens and shutter count
   cam1_partial = {
    'name': 'ILCE-7',
    'serial': '12345678',
    'appConnected': True,
   }
   info_frame.showConnectedCamera(cam1_partial)
   root.update()
   self.assertEqual(info_frame.infoVars['Lens'].get(), 'SEL2870 28–70mm F3.5–5.6 OSS, firmware 1.04')
   self.assertIn('4,464', info_frame.infoVars['Shutter count'].get())

   # Phase 3: Camera 2 with SAME model ILCE-7 but DIFFERENT serial is plugged in
   cam2_full = {
    'name': 'ILCE-7',
    'model': 'ILCE-7',
    'vendor': 'Sony (0x054c)',
    'mode': 'MTP',
    'serial': '99999999',
    'raw_serial': '00000000000000003282630099999999',
    'appConnected': True,
    'physicalDetected': True,
    'status': 'ready',
   }
   info_frame.showConnectedCamera(cam2_full)
   root.update()
   # Serial changed on same model -> Previous camera's lens and shutter count MUST BE CLEARED!
   self.assertEqual(info_frame.infoVars['Serial number'].get(), '99999999')
   self.assertEqual(info_frame.infoVars['Lens'].get(), '—')
   self.assertEqual(info_frame.infoVars['Shutter count'].get(), '—')

   root.close()


 def test_touchpad_scroll_packed_deltas_horizontal_and_tag_routing(self):
  with patch('pmca.appstore.catalog.syncCatalogMetadata', return_value=({}, False)), \
       patch.dict(self.gui, {'checkCameraConnection': Mock(return_value=None)}):
   root = self.gui['MainUi']('Test Native TouchpadScroll', installerOnly=True)
   root.update()

   frame = root.installerFrame
   frame.update_idletasks()

   # 1. Verify StoreScrollable tag presence on child elements
   first_btn = frame.cardDownloadButtons[0]
   self_tags = first_btn.bindtags()
   self.assertIn("StoreScrollable", self_tags)

   # 2. Test initial position
   initial_y = frame.canvas.yview()[0]

   # 3. Fire TouchpadScroll with 65523 (dy = -13, scrolling down)
   try:
    first_btn.event_generate("<TouchpadScroll>", delta=65523, when='tail')
   except Exception:
    # Older Tk versions (e.g. Tk 8.6 on Linux/Windows CI) do not support TouchpadScroll
    root.close()
    return
   root.update()
   y1 = frame.canvas.yview()[0]
   self.assertGreater(y1, initial_y)

   # 4. Fire TouchpadScroll with 65503 (dy = -33, scrolling down further)
   first_lbl = frame.descLabels[0]
   first_lbl.event_generate("<TouchpadScroll>", delta=65503, when='tail')
   root.update()
   y2 = frame.canvas.yview()[0]
   self.assertGreater(y2, y1)

   # 5. Fire horizontal-only TouchpadScroll (dy = 0, dx = 30 -> delta = 30 << 16 = 1966080)
   first_lbl.event_generate("<TouchpadScroll>", delta=1966080, when='tail')
   root.update()
   y3 = frame.canvas.yview()[0]
   self.assertEqual(y3, y2)

   # 6. Fire positive TouchpadScroll (dy = +46, scrolling back up)
   first_lbl.event_generate("<TouchpadScroll>", delta=46, when='tail')
   root.update()
   y4 = frame.canvas.yview()[0]
   self.assertLess(y4, y3)

   # 7. Fire legacy MouseWheel (delta = -1)
   first_btn.event_generate("<MouseWheel>", delta=-1, when='tail')
   root.update()
   y5 = frame.canvas.yview()[0]
   self.assertGreater(y5, y4)

   # 8. Test extreme deltas decoding
   dx1, dy1 = root._decodeTouchpadScroll(32767)
   self.assertEqual(dy1, 32767)
   dx2, dy2 = root._decodeTouchpadScroll(32768)
   self.assertEqual(dy2, -32768)

   root.close()


 def test_coalesced_scroll_burst_batching_direction_reversal_and_edge_clamping(self):
  with patch('pmca.appstore.catalog.syncCatalogMetadata', return_value=({}, False)), \
       patch.dict(self.gui, {'checkCameraConnection': Mock(return_value=None)}):
   root = self.gui['MainUi']('Test Coalescing', installerOnly=True)
   root.update()
   frame = root.installerFrame
   frame.update_idletasks()

   init_y = frame.canvas.yview()[0]

   # 1. High frequency burst
   for _ in range(40):
    frame._queueScrollUnits(10)
   root.update()
   import time
   time.sleep(0.04)
   root.update()
   after_burst_y = frame.canvas.yview()[0]
   self.assertGreater(after_burst_y, init_y)

   # 2. Direction reversal flush
   frame._queueScrollUnits(20)
   self.assertEqual(frame._pendingScrollUnits, 20)
   frame._queueScrollUnits(-30)
   self.assertEqual(frame._pendingScrollUnits, -30)

   # 3. Top boundary edge clamp
   frame.canvas.yview_moveto(0.0)
   frame._flushPendingScroll()
   root.update()
   frame._queueScrollUnits(-20)
   self.assertEqual(frame._pendingScrollUnits, 0)

   # 4. Timer clean teardown
   frame._queueScrollUnits(15)
   self.assertIsNotNone(frame._scrollTimerId)
   root.close()


if __name__ == '__main__':
 unittest.main()
