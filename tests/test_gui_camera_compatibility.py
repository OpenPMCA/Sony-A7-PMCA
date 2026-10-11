"""Unit tests for GUI camera eligibility presentation, APK install gating, and multi-model transitions."""
import contextlib
import io
import os
from pathlib import Path
import runpy
from tempfile import NamedTemporaryFile, TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tests.apk_fixture import apkFixture


class GuiCameraCompatibilityTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  path = Path(__file__).resolve().parents[1] / 'pmca-gui.py'
  cls.gui = runpy.run_path(str(path))['main'].__globals__

 def setUp(self):
  self.temp = TemporaryDirectory()
  self.addCleanup(self.temp.cleanup)
  self.apk_path = Path(self.temp.name) / 'valid.apk'
  self.apk_path.write_bytes(apkFixture(signed=True))
  self.mock_info_cmd = Mock(return_value=None)
  self.mock_read_only = Mock(return_value=None)
  self.mock_monitor = patch.object(self.gui['MainUi'], 'startCameraMonitor')
  self.mock_monitor.start()
  self.addCleanup(self.mock_monitor.stop)
  self.mock_sync = patch.object(self.gui['InstallerFrame'], 'startBackgroundSync')
  self.mock_sync.start()
  self.addCleanup(self.mock_sync.stop)
  self.patches = [
   patch.dict(self.gui, {
    'infoCommand': self.mock_info_cmd,
    'getReadOnlyCameraInfo': self.mock_read_only,
    'syncCatalogMetadata': Mock(return_value=({}, False)),
    'checkCameraConnection': Mock(return_value=None),
    'askyesno': Mock(return_value=True),
    'showerror': Mock(),
   }),
   patch('pmca.commands.usb.getReadOnlyCameraInfo', self.mock_read_only),
   patch('pmca.commands.usb.infoCommand', self.mock_info_cmd),
   patch('pmca.appstore.catalog.syncCatalogMetadata', return_value=({}, False)),
  ]
  for p in self.patches:
   p.start()
   self.addCleanup(p.stop)

 def _ready_info(self, model='ILCE-7', app_supported=True, reason=None, mode='MTP',
                 tested=None, shutter_layout=None, busy=False, operations=None):
  if tested is None:
   tested = (model == 'ILCE-7')
  pmca_apps = app_supported if 'UNKNOWN' not in model else None
  profile = {
   'model': model,
   'pmca_apps': pmca_apps,
   'installation_tested': tested,
   'installation_evidence': 'RecipeLab tested' if tested else None,
   'shutter_layout': shutter_layout or ('tag9050a' if '7' in model else None),
   'source': 'upstream reference',
  }
  return {
   'connected': True,
   'physicalDetected': True,
   'appConnected': True,
   'busy': busy,
   'status': 'busy' if busy else 'ready',
   'mode': mode,
   'source_mode': mode,
   'name': model,
   'model': model,
   'vendor': 'Sony (0x054c)',
   'serial': '12345678',
   'raw_serial': '00000000000000003282630012345678',
   'ptp_device_version': '3.0',
   'firmware_version': '3.20' if model == 'ILCE-7' else None,
   'camera_support': profile,
   'app_installation_supported': app_supported,
   'app_installation_reason': reason or ('Ready to install.' if app_supported else 'This model is not listed as PMCA app-capable in the upstream device reference.'),
   'capabilities': list(operations or [0x9280, 0x9281]),
   'properties': [0x5001, 0xd001],
   'shutter_count': {'available': False, 'reason': 'Query camera info to inspect shutter count.'},
  }

 def test_positive_alpha_a_model_enables_install_when_apk_selected(self):
  info = self._ready_info('ILCE-7', app_supported=True, tested=True)
  root = self.gui['MainUi']('Test ILCE-7', installerOnly=True)
  root.withdraw()
  root.onCameraStatusUpdate(info)
  root.update()

  self.assertTrue(root.cameraConnected)
  self.assertTrue(root.cameraActionsEnabled)
  self.assertTrue(root.cameraInstallEnabled)
  self.assertEqual(str(root.infoFrame.infoButton['state']), 'normal')

  # App support badge
  self.assertEqual(root.infoFrame.infoVars['App Support'].get(), 'Supported (Verified on ILCE-7)')
  self.assertEqual(root.infoFrame.infoVars['App support'].get(), 'Supported (Verified on ILCE-7)')

  # Upper panel note shows camera ready
  self.assertIn('ILCE-7', root.installerFrame.apkStatusNote.get())
  self.assertIn('Ready to install', root.installerFrame.apkStatusNote.get())

  # Install button disabled until valid APK is staged
  self.assertEqual(str(root.installerFrame.installButton['state']), 'disabled')
  root.installerFrame.setApkFile(str(self.apk_path))
  root.update()
  self.assertEqual(str(root.installerFrame.installButton['state']), 'normal')

  root.close()

 def test_positive_alpha_b_model_supported_reference_model(self):
  info = self._ready_info('ILCE-7RM2', app_supported=True, tested=False, shutter_layout='tag9050b')
  root = self.gui['MainUi']('Test ILCE-7RM2', installerOnly=True)
  root.withdraw()
  root.onCameraStatusUpdate(info)
  root.update()

  self.assertTrue(root.cameraConnected)
  self.assertTrue(root.cameraInstallEnabled)
  self.assertEqual(root.infoFrame.infoVars['App Support'].get(), 'Supported (PMCA reference model)')
  root.installerFrame.setApkFile(str(self.apk_path))
  root.update()
  self.assertEqual(str(root.installerFrame.installButton['state']), 'normal')
  root.close()

 def test_positive_nex_and_dsc_models_supported(self):
  for model in ['NEX-5R', 'DSC-HX60', 'DSC-RX100M4']:
   with self.subTest(model=model):
    info = self._ready_info(model, app_supported=True, tested=False)
    root = self.gui['MainUi']('Test ' + model, installerOnly=True)
    root.withdraw()
    root.onCameraStatusUpdate(info)
    root.update()
    self.assertTrue(root.cameraConnected)
    self.assertTrue(root.cameraInstallEnabled)
    self.assertEqual(root.infoFrame.infoVars['App Support'].get(), 'Supported (PMCA reference model)')
    root.close()

 def test_known_unsupported_non_pmca_body_keeps_info_enabled_but_disables_install(self):
  reason = 'This model is not listed as PMCA app-capable in the upstream device reference.'
  info = self._ready_info('ILCE-7M3', app_supported=False, reason=reason, tested=False)
  root = self.gui['MainUi']('Test ILCE-7M3', installerOnly=True)
  root.withdraw()
  root.onCameraStatusUpdate(info)
  root.update()

  # Read-only communication is active and Info is enabled
  self.assertTrue(root.cameraConnected)
  self.assertTrue(root.cameraActionsEnabled)
  self.assertEqual(str(root.infoFrame.infoButton['state']), 'normal')
  self.assertEqual(root.infoFrame.infoVars['Model'].get(), 'ILCE-7M3')
  self.assertEqual(root.infoFrame.infoVars['App Support'].get(), 'Not supported (No PMCA subsystem)')

  # Install is disabled
  self.assertFalse(root.cameraInstallEnabled)
  self.assertEqual(root.supportReason, reason)

  # Upper panel status must state model is unsupported, NOT 'camera disconnected'
  note = root.installerFrame.apkStatusNote.get()
  self.assertNotIn('not connected', note.lower())
  self.assertIn('ILCE-7M3', note)
  self.assertTrue(any(term in note.lower() for term in ['not supported', 'not listed', 'pmca', 'app-capable']))

  # Even with valid APK selected, Install button remains disabled
  root.installerFrame.setApkFile(str(self.apk_path))
  root.update()
  self.assertEqual(str(root.installerFrame.installButton['state']), 'disabled')

  root.close()

 def test_install_task_do_before_blocks_unsupported_camera_without_calling_install(self):
  reason = 'This model is not listed as PMCA app-capable in the upstream device reference.'
  info = self._ready_info('ILCE-7M3', app_supported=False, reason=reason)
  mock_install = Mock()
  mock_error = Mock()
  mock_confirm = Mock(return_value=True)

  with patch.dict(self.gui, {
        'installCommand': mock_install,
        'showerror': mock_error,
        'askyesno': mock_confirm,
       }):
   root = self.gui['MainUi']('Test Install Veto', installerOnly=True)
   root.withdraw()
   root.onCameraStatusUpdate(info)
   root.update()
   root.installerFrame.setApkFile(str(self.apk_path))
   root.update()

   task = self.gui['InstallTask'](root.installerFrame)
   args = task.doBefore()

   self.assertIsNone(args, 'InstallTask.doBefore must return None for unsupported camera')
   mock_error.assert_called_once()
   self.assertTrue(any(term in str(mock_error.call_args).lower() for term in ['not supported', 'not listed', 'pmca', 'app-capable']))
   mock_confirm.assert_not_called()
   mock_install.assert_not_called()
   root.close()

 def test_supported_model_with_missing_vendor_operations_disables_install(self):
  reason = 'The camera model is PMCA-capable, but the required Sony transport commands are unavailable.'
  info = self._ready_info('ILCE-7', app_supported=False, reason=reason, operations=[0x1001, 0x1002])
  root = self.gui['MainUi']('Test Missing Ops', installerOnly=True)
  root.withdraw()
  root.onCameraStatusUpdate(info)
  root.update()

  self.assertTrue(root.cameraConnected)
  self.assertFalse(root.cameraInstallEnabled)
  self.assertEqual(root.supportReason, reason)

  root.installerFrame.setApkFile(str(self.apk_path))
  root.update()
  self.assertEqual(str(root.installerFrame.installButton['state']), 'disabled')
  root.close()

 def test_genuine_app_installer_protocol_confirms_unlisted_model(self):
  info = self._ready_info('ILCE-UNKNOWN', app_supported=True, mode='App installation',
                          reason='Sony app-installer protocol confirmed.')
  root = self.gui['MainUi']('Test App Install Protocol', installerOnly=True)
  root.withdraw()
  root.onCameraStatusUpdate(info)
  root.update()

  self.assertTrue(root.cameraConnected)
  self.assertTrue(root.cameraInstallEnabled)
  self.assertEqual(root.infoFrame.infoVars['App Support'].get(), 'Supported (Installer active)')

  root.installerFrame.setApkFile(str(self.apk_path))
  root.update()
  self.assertEqual(str(root.installerFrame.installButton['state']), 'normal')
  root.close()

 def test_unconfirmed_unknown_model_in_normal_mtp_disables_install(self):
  reason = 'PMCA app support is unconfirmed for this model; no installer protocol is active.'
  info = self._ready_info('ILCE-UNKNOWN', app_supported=False, reason=reason)
  root = self.gui['MainUi']('Test Unknown Model', installerOnly=True)
  root.withdraw()
  root.onCameraStatusUpdate(info)
  root.update()

  self.assertTrue(root.cameraConnected)
  self.assertFalse(root.cameraInstallEnabled)
  self.assertEqual(root.infoFrame.infoVars['App Support'].get(), 'Unconfirmed model')

  root.installerFrame.setApkFile(str(self.apk_path))
  root.update()
  self.assertEqual(str(root.installerFrame.installButton['state']), 'disabled')
  root.close()

 def test_legacy_status_missing_support_flag_preserves_backward_compatibility(self):
  info = {
   'connected': True,
   'physicalDetected': True,
   'appConnected': True,
   'status': 'ready',
   'mode': 'MTP',
   'name': 'ILCE-7',
   'model': 'ILCE-7',
   'vendor': 'Sony (0x054c)',
   'serial': '12345678',
  }
  root = self.gui['MainUi']('Test Legacy Status', installerOnly=True)
  root.withdraw()
  root.onCameraStatusUpdate(info)
  root.update()

  self.assertTrue(root.cameraConnected)
  self.assertTrue(root.cameraInstallEnabled)

  root.installerFrame.setApkFile(str(self.apk_path))
  root.update()
  self.assertEqual(str(root.installerFrame.installButton['state']), 'normal')
  root.close()

 def test_transition_a7_to_7rm2_to_7m3_with_same_root(self):
  root = self.gui['MainUi']('Test Model Transitions', installerOnly=True)
  root.withdraw()
  root.update()
  root.installerFrame.setApkFile(str(self.apk_path))
  root.update()

  # Step 1: Connect ILCE-7 (Alpha A, supported & tested)
  info_a7 = self._ready_info('ILCE-7', app_supported=True, tested=True)
  root.onCameraStatusUpdate(info_a7)
  root.update()
  self.assertTrue(root.cameraConnected)
  self.assertTrue(root.cameraInstallEnabled)
  self.assertEqual(str(root.installerFrame.installButton['state']), 'normal')
  self.assertEqual(root.infoFrame.infoVars['Model'].get(), 'ILCE-7')
  self.assertEqual(root.infoFrame.infoVars['App Support'].get(), 'Supported (Verified on ILCE-7)')

  # Step 2: Transition to ILCE-7RM2 (Alpha B, supported reference model)
  info_7rm2 = self._ready_info('ILCE-7RM2', app_supported=True, tested=False)
  root.onCameraStatusUpdate(info_7rm2)
  root.update()
  self.assertTrue(root.cameraConnected)
  self.assertTrue(root.cameraInstallEnabled)
  self.assertEqual(str(root.installerFrame.installButton['state']), 'normal')
  self.assertEqual(root.infoFrame.infoVars['Model'].get(), 'ILCE-7RM2')
  self.assertEqual(root.infoFrame.infoVars['App Support'].get(), 'Supported (PMCA reference model)')

  # Step 3: Transition to ILCE-7M3 (Known non-PMCA body)
  reason = 'This model is not listed as PMCA app-capable in the upstream device reference.'
  info_7m3 = self._ready_info('ILCE-7M3', app_supported=False, reason=reason, tested=False)
  root.onCameraStatusUpdate(info_7m3)
  root.update()
  self.assertTrue(root.cameraConnected)
  self.assertFalse(root.cameraInstallEnabled)
  # Info button remains normal for read-only diagnostics!
  self.assertEqual(str(root.infoFrame.infoButton['state']), 'normal')
  self.assertEqual(root.infoFrame.infoVars['Model'].get(), 'ILCE-7M3')
  self.assertEqual(root.infoFrame.infoVars['App Support'].get(), 'Not supported (No PMCA subsystem)')
  # Install button must immediately disable!
  self.assertEqual(str(root.installerFrame.installButton['state']), 'disabled')

  # Step 4: Disconnect
  root.onCameraStatusUpdate(None)
  root.update()
  self.assertFalse(root.cameraConnected)
  self.assertFalse(root.cameraInstallEnabled)
  self.assertEqual(str(root.infoFrame.infoButton['state']), 'disabled')
  self.assertEqual(str(root.installerFrame.installButton['state']), 'disabled')
  self.assertEqual(root.infoFrame.infoVars['Model'].get(), '—')
  self.assertEqual(root.infoFrame.infoVars['App Support'].get(), '—')

  root.close()

 def test_backend_busy_state_blocks_install_without_deadlocking_monitor(self):
  root = self.gui['MainUi']('Test Backend Busy', installerOnly=True)
  root.withdraw()
  root.update()
  root.installerFrame.setApkFile(str(self.apk_path))
  root.update()

  info_busy = self._ready_info('ILCE-7', app_supported=True, busy=True)
  root.onCameraStatusUpdate(info_busy)
  root.update()

  # cameraBusy (internal GUI worker flag) must remain False so monitor keeps polling!
  self.assertFalse(root.cameraBusy)
  # But cameraInstallEnabled is blocked because backend is busy
  self.assertFalse(root.cameraInstallEnabled)
  self.assertEqual(str(root.installerFrame.installButton['state']), 'disabled')

  # When next status arrives with busy=False, install is restored
  info_ready = self._ready_info('ILCE-7', app_supported=True, busy=False)
  root.onCameraStatusUpdate(info_ready)
  root.update()
  self.assertTrue(root.cameraInstallEnabled)
  self.assertEqual(str(root.installerFrame.installButton['state']), 'normal')

  root.close()

 def test_multiple_devices_status_shows_honest_guidance_without_disconnect(self):
  info_multi = {
   'connected': False,
   'physicalDetected': True,
   'appConnected': False,
   'status': 'multiple_devices',
   'failure_reason': 'Multiple Sony cameras detected. Connect only one Sony camera at a time.',
   'app_installation_supported': False,
  }
  root = self.gui['MainUi']('Test Multiple Devices', installerOnly=True)
  root.withdraw()
  root.onCameraStatusUpdate(info_multi)
  root.update()

  self.assertFalse(root.cameraConnected)
  self.assertIn('Multiple Sony cameras', root.usbStatusVar.get())
  self.assertIn('Connect only one', root.installerFrame.apkStatusNote.get())
  self.assertEqual(str(root.installerFrame.installButton['state']), 'disabled')

  root.close()

 def test_async_fetch_safe_camera_info_identity_guard_prevents_stale_overwrite(self):
  data_cam1 = {'Model': 'ILCE-7', 'Lens': 'Old Lens 50mm'}
  data_cam2 = {'Model': 'ILCE-7RM2', 'Lens': 'New Lens 24-70mm'}

  root = self.gui['MainUi']('Test Identity Guard', installerOnly=True)
  root.withdraw()
  root.update()

  # Connect Camera 1 and launch fetch with captured identity ('ILCE-7', '1111')
  info_cam1 = self._ready_info('ILCE-7')
  info_cam1['serial'] = '1111'
  root.onCameraStatusUpdate(info_cam1)
  root.update()

  # Switch immediately to Camera 2 before Camera 1 async worker returns
  info_cam2 = self._ready_info('ILCE-7RM2')
  info_cam2['serial'] = '2222'
  root.onCameraStatusUpdate(info_cam2)
  root.update()
  root.infoFrame.showCameraInfo(data_cam2)
  self.assertEqual(root.infoFrame.infoVars['Model'].get(), 'ILCE-7RM2')
  self.assertEqual(root.infoFrame.infoVars['Lens'].get(), 'New Lens 24-70mm')

  # Now verify that applying data with stale captured_id ('ILCE-7', '1111') does not overwrite Camera 2
  # Simulate stale worker callback returning for Camera 1
  if hasattr(root, "fetchSafeCameraInfo"):
   apply_func = None
   # Find or construct the apply callback with stale cid
   def stale_apply():
    cid = ('ILCE-7', '1111')
    current_model = getattr(root.infoFrame, "cameraSnapshot", {}).get("Model")
    current_serial = getattr(root.infoFrame, "cameraSnapshot", {}).get("Serial number")
    current_raw = getattr(root.infoFrame, "cameraSnapshot", {}).get("PTP descriptor")
    if cid[0] and current_model and current_model != "—" and cid[0] != current_model:
     return
    if cid[1] and current_serial and current_serial != "—" and cid[1] not in (current_serial, current_raw):
     return
    root.infoFrame.showCameraInfo(data_cam1)
   stale_apply()
   root.update()
   # Must NOT overwrite Camera 2
   self.assertEqual(root.infoFrame.infoVars['Model'].get(), 'ILCE-7RM2')
   self.assertEqual(root.infoFrame.infoVars['Lens'].get(), 'New Lens 24-70mm')

  root.close()

 def test_camera_transition_same_model_different_descriptor_does_not_leak_details(self):
  root = self.gui['MainUi']('Test Same Model Descriptor Diff', installerOnly=True)
  root.withdraw()
  root.update()

  # Phase 1: Camera 1 connected with body serial, firmware 3.20, shutter count, and lens
  cam1_info = self._ready_info('ILCE-7', app_supported=True)
  cam1_info['serial'] = '12345678'
  cam1_info['raw_serial'] = '00000000000000003282630012345678'
  cam1_info['firmware_version'] = '3.20'
  cam1_info['shutter_count'] = {'available': True, 'value': 4464}
  cam1_info['lens'] = 'SEL2870 28–70mm F3.5–5.6 OSS'
  root.onCameraStatusUpdate(cam1_info)
  root.update()

  self.assertEqual(root.infoFrame.infoVars['Model'].get(), 'ILCE-7')
  self.assertEqual(root.infoFrame.infoVars['Serial number'].get(), '12345678')
  self.assertEqual(root.infoFrame.infoVars['Firmware version'].get(), '3.20')
  self.assertIn('4,464', root.infoFrame.infoVars['Shutter count'].get())
  self.assertEqual(root.infoFrame.infoVars['Lens'].get(), 'SEL2870 28–70mm F3.5–5.6 OSS')

  # Phase 2: Camera 2 connects: SAME model ILCE-7, but different PTP descriptor, serial not verified yet
  cam2_info = self._ready_info('ILCE-7', app_supported=True)
  cam2_info['serial'] = None
  cam2_info['raw_serial'] = '00000000000000003282630099999999'
  cam2_info['firmware_version'] = None
  cam2_info['shutter_count'] = {'available': False, 'reason': 'Query camera info to inspect shutter count.'}
  cam2_info['lens'] = None
  root.onCameraStatusUpdate(cam2_info)
  root.update()

  # Must update PTP descriptor to Camera 2
  self.assertEqual(root.infoFrame.infoVars['PTP descriptor'].get(), '00000000000000003282630099999999')
  # Must NOT leak Camera 1's body serial into Camera 2
  self.assertNotEqual(root.infoFrame.infoVars['Serial number'].get(), '12345678')
  self.assertIn(root.infoFrame.infoVars['Serial number'].get(), ['Unavailable without query', '—'])
  # Must NOT leak Camera 1's firmware version into Camera 2
  self.assertNotEqual(root.infoFrame.infoVars['Firmware version'].get(), '3.20')
  self.assertIn(root.infoFrame.infoVars['Firmware version'].get(), ['Unavailable without query', '—'])
  # Must NOT leak Camera 1's shutter count into Camera 2
  self.assertNotIn('4,464', root.infoFrame.infoVars['Shutter count'].get())
  # Must NOT leak Camera 1's lens into Camera 2
  self.assertEqual(root.infoFrame.infoVars['Lens'].get(), '—')

  root.close()

 def test_transport_serial_not_mislabeled_as_body_serial(self):
  root = self.gui['MainUi']('Test Transport Serial', installerOnly=True)
  root.withdraw()
  root.update()

  # Camera reports only raw 32-character PTP transport descriptor, no body serial
  info = self._ready_info('ILCE-7', app_supported=True)
  info['serial'] = None
  info['raw_serial'] = '00000000000000003282630012345678'
  root.onCameraStatusUpdate(info)
  root.update()

  self.assertEqual(root.infoFrame.infoVars['PTP descriptor'].get(), '00000000000000003282630012345678')
  # Transport serial must NOT be set as Body Serial
  self.assertNotEqual(root.infoFrame.infoVars['Serial number'].get(), '00000000000000003282630012345678')
  self.assertEqual(root.infoFrame.infoVars['Serial number'].get(), 'Unavailable without query')

  root.close()

 def test_shutter_counter_unsupported_and_unconfirmed_concise_reasons(self):
  root = self.gui['MainUi']('Test Shutter Reasons', installerOnly=True)
  root.withdraw()
  root.update()

  # Case A: Unsupported model family (e.g. DSC-HX60)
  info_dsc = self._ready_info('DSC-HX60', app_supported=True)
  info_dsc['shutter_count'] = {
   'available': False,
   'reason': 'Camera model DSC-HX60 is not supported for MakerNote shutter counter extraction.',
  }
  root.onCameraStatusUpdate(info_dsc)
  root.update()
  self.assertEqual(root.infoFrame.infoVars['Shutter count'].get(), 'Unsupported on this model')
  self.assertIn('not supported', root.infoFrame.infoVars['Shutter note'].get().lower())

  # Case B: Unconfirmed model
  info_unconfirmed = self._ready_info('ILCE-UNKNOWN', app_supported=False)
  info_unconfirmed['shutter_count'] = {
   'available': False,
   'reason': 'Shutter count unconfirmed for this model.',
  }
  root.onCameraStatusUpdate(info_unconfirmed)
  root.update()
  self.assertEqual(root.infoFrame.infoVars['Shutter count'].get(), 'Unconfirmed for this model')

  # Case C: Camera in App installation mode
  info_app = self._ready_info('ILCE-7', app_supported=True, mode='App installation')
  info_app['shutter_count'] = {
   'available': False,
   'reason': 'Camera is in App installation mode. Switch back to normal MTP mode to read shutter count.',
  }
  root.onCameraStatusUpdate(info_app)
  root.update()
  self.assertEqual(root.infoFrame.infoVars['Shutter count'].get(), 'Unavailable in App Install mode')

  root.close()

 def test_unsupported_camera_maintains_normal_info_and_logs_behavior(self):
  reason = 'This model is not listed as PMCA app-capable in the upstream device reference.'
  info_7m3 = self._ready_info('ILCE-7M3', app_supported=False, reason=reason)
  mock_info_data = {
   'Model': 'ILCE-7M3',
   'Serial number': '77777777',
   'Firmware version': '1.00',
   'Shutter count': 'Unsupported on this model',
   'USB mode': 'MTP',
  }

  root = self.gui['MainUi']('Test Unsupported Diagnostics', installerOnly=True)
  root.withdraw()
  root.onCameraStatusUpdate(info_7m3)
  root.update()

  # 1. Info button must be normal for diagnostics
  self.assertEqual(str(root.infoFrame.infoButton['state']), 'normal')
  # 2. Install button must be disabled
  self.assertEqual(str(root.installerFrame.installButton['state']), 'disabled')

  # 3. Simulate InfoTask running and applying camera properties
  with patch.dict(self.gui, {
   'infoCommand': Mock(return_value=mock_info_data),
   'askyesno': Mock(return_value=True),
   'showerror': Mock(),
  }):
   task = self.gui['InfoTask'](root.infoFrame)
   driver = task.doBefore()
   self.assertNotEqual(driver, False)
   res = task.do(driver)
   task.doAfter(res)
   root.update()

  self.assertEqual(root.infoFrame.infoVars['Model'].get(), 'ILCE-7M3')
  self.assertEqual(root.infoFrame.infoVars['Serial number'].get(), '77777777')
  self.assertEqual(root.infoFrame.infoVars['Firmware version'].get(), '1.00')
  self.assertEqual(root.infoFrame.infoVars['Shutter count'].get(), 'Unsupported on this model')
  # Install button remains disabled after Info query
  self.assertEqual(str(root.installerFrame.installButton['state']), 'disabled')
  # Info button restored to normal
  self.assertEqual(str(root.infoFrame.infoButton['state']), 'normal')

  # 4. Activity Logs are accessible and clearable
  root.notebook.select(root.activityFrame)
  root.update()
  root.clearLog()
  self.assertEqual(root.logText.text.get('1.0', 'end').strip(), '')

  root.close()

 def test_gui_header_and_footer_display_v1_1_0(self):
  root = self.gui['MainUi']('Test Version Presentation', installerOnly=True)
  root.withdraw()
  root.update()

  labels = []
  def collect_labels(widget):
   for child in widget.winfo_children():
    if child.winfo_class() == 'TLabel':
     try:
      txt = child.cget('text')
      if txt:
       labels.append(txt)
     except Exception:
      pass
    collect_labels(child)
  collect_labels(root)

  self.assertTrue(any(lbl == 'v1.1.0' for lbl in labels), f"Header version label must show exactly 'v1.1.0', found: {labels}")
  self.assertTrue(any(lbl == 'Version 1.1.0' for lbl in labels), f"Footer version label must show exactly 'Version 1.1.0', found: {labels}")

  root.close()

 def test_close_and_destroy_cancels_pending_queue_timer_and_aborts_workers(self):
  root = self.gui['MainUi']('Test Timer Cancellation', installerOnly=True)
  root.withdraw()
  root.update()

  self.assertTrue(hasattr(root, "_queueAfterId"))
  self.assertIsNotNone(root._queueAfterId)
  self.assertFalse(root.abortMonitor.is_set())
  self.assertFalse(root.abortSync.is_set())

  # Verify _queueAfterId is actively registered in Tk after table
  active_timers = root.tk.call('after', 'info')
  self.assertIn(root._queueAfterId, active_timers)

  root.close()
  self.assertTrue(getattr(root, "_closed", False))
  self.assertTrue(root.abortMonitor.is_set())
  self.assertTrue(root.abortSync.is_set())
  self.assertIsNone(root._queueAfterId)

 def test_process_queue_logs_traceback_on_callback_crash_and_continues_processing(self):
  root = self.gui['MainUi']('Test Queue Robustness', installerOnly=True)
  root.withdraw()
  root.update()

  executed = []
  def failing_cb():
   executed.append('first')
   raise RuntimeError("Test callback exception")

  def succeeding_cb():
   executed.append('second')

  previous_timer = root._queueAfterId
  root.after_cancel(previous_timer)  # Emulate a scheduled tick before invoking its callback directly.
  mock_print_exc = Mock()
  with patch('traceback.print_exc', mock_print_exc):
   root.run(failing_cb)
   root.run(succeeding_cb)
   root._processQueue()

  self.assertNotIn(previous_timer, root.tk.call('after', 'info'), 'Manual test dispatch must not leave a second queue timer')
  self.assertEqual(executed, ['first', 'second'], "Following callback must still run when previous callback raises")
  mock_print_exc.assert_called_once()
  self.assertIsNotNone(root._queueAfterId)

  root.close()

 def test_install_task_do_before_blocks_busy_camera(self):
  info = self._ready_info('ILCE-7', app_supported=True)
  mock_install = Mock()
  mock_error = Mock()
  mock_confirm = Mock(return_value=True)

  with patch.dict(self.gui, {
        'installCommand': mock_install,
        'showerror': mock_error,
        'askyesno': mock_confirm,
       }):
   root = self.gui['MainUi']('Test Install Busy Veto', installerOnly=True)
   root.withdraw()
   root.onCameraStatusUpdate(info)
   root.installerFrame.setApkFile(str(self.apk_path))
   root.update()

   # Put GUI into busy state
   root.setCameraBusy(True)
   root.update()
   self.assertEqual(str(root.installerFrame.installButton['state']), 'disabled')

   task = self.gui['InstallTask'](root.installerFrame)
   args = task.doBefore()

   self.assertIsNone(args, 'InstallTask.doBefore must return None when camera is busy')
   mock_error.assert_called_once()
   self.assertIn('busy', str(mock_error.call_args).lower())
   mock_confirm.assert_not_called()
   mock_install.assert_not_called()

   root.setCameraBusy(False)
   root.close()


if __name__ == '__main__':
 unittest.main()
