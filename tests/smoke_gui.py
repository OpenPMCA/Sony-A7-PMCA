"""Exercise the real Tk window without contacting a camera or the network."""
from pathlib import Path
import runpy
import sys
import time
from unittest.mock import Mock, patch


rootPath = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(rootPath))
gui = runpy.run_path(str(rootPath / 'pmca-gui.py'))['main'].__globals__
originalStreams = sys.stdout, sys.stderr
def simulatedInfo(driver):
 print('Smoke: camera query simulated')
 return {'Model': 'ILCE-7', 'Firmware version': '3.20', 'USB mode': 'MTP'}
info = Mock(side_effect=simulatedInfo)
errors = []
root = None
try:
 with patch.object(gui['MainUi'], 'startCameraMonitor'), \
      patch.object(gui['InstallerFrame'], 'startBackgroundSync'), \
      patch('pmca.commands.usb.getReadOnlyCameraInfo', Mock(return_value=None)), \
      patch.dict(gui, {
       'infoCommand': info,
       'getReadOnlyCameraInfo': Mock(return_value=None),
       'checkCameraConnection': Mock(return_value=None),
       'syncCatalogMetadata': Mock(return_value=({}, False)),
       'askyesno': Mock(return_value=True),
       'listApps': Mock(side_effect=AssertionError('Unexpected network app-list request')),
       'showerror': lambda title, message: errors.append((title, message)),
       'installCommand': Mock(side_effect=AssertionError('Unexpected camera installation')),
      }):
  root = gui['MainUi']('Sony A7 PMCA — smoke test', installerOnly=True)
  root.update()
  assert str(root.infoFrame.infoButton['state']) == 'disabled'
  assert str(root.installerFrame.installButton['state']) == 'disabled'

  # Transition to connected camera via genuine state machine
  ready_info = {
   'connected': True,
   'physicalDetected': True,
   'appConnected': True,
   'app_installation_supported': True,
   'status': 'ready',
   'mode': 'MTP',
   'name': 'ILCE-7',
   'model': 'ILCE-7',
   'vendor': 'Sony (0x054c)',
   'serial': '12345678',
   'firmware_version': '3.20',
  }
  root.onCameraStatusUpdate(ready_info)
  if hasattr(root, '_fetchInfoDone'):
   root._fetchInfoDone.wait(timeout=2.0)
  root._processQueue()
  root.update()
  assert str(root.infoFrame.infoButton['state']) == 'normal'

  notebook = next(widget for widget in root.winfo_children() if widget.winfo_class() == 'TNotebook')
  assert [notebook.tab(tab, 'text') for tab in notebook.tabs()] == ['Camera', 'Applications', 'Activity']
  assert root.installerFrame.getMode() == root.installerFrame.MODE_APK

  # Install button must remain disabled when no APK is selected (P0 contract)
  assert str(root.installerFrame.installButton['state']) == 'disabled'
  # Direct invocation of handler without APK must display error
  gui['InstallTask'](root.installerFrame).run()
  deadline = time.monotonic() + 3
  while time.monotonic() < deadline and not errors:
   root._processQueue()
   root.update()
   time.sleep(.02)
  assert errors, 'An empty APK selection should display an error'
  gui['installCommand'].assert_not_called()

  # Selecting a valid APK enables installButton
  from apk_fixture import apkFixture
  import tempfile
  temp_apk = tempfile.NamedTemporaryFile(suffix='.apk', delete=False)
  temp_apk.write(apkFixture(signed=True))
  temp_apk.close()
  root.installerFrame.setApkFile(temp_apk.name)
  assert str(root.installerFrame.installButton['state']) == 'normal'

  root.infoFrame.infoButton.invoke()
  assert str(root.installerFrame.installButton['state']) == 'disabled'
  deadline = time.monotonic() + 3
  while time.monotonic() < deadline and str(root.infoFrame.infoButton['state']) == 'disabled':
   root._processQueue()
   root.update()
   time.sleep(.02)
  expected_driver = 'libusb-mtp' if sys.platform == 'darwin' else ('libusb' if sys.platform.startswith('linux') else None)
  assert root.driverName == expected_driver
  info.assert_called_once_with(root.driverName)
  assert str(root.infoFrame.infoButton['state']) == 'normal'
  assert str(root.installerFrame.installButton['state']) == 'normal'
  assert 'Smoke: camera query simulated' in root.logText.text.get('1.0', 'end')
  assert root.infoFrame.infoVars['Model'].get() == 'ILCE-7'
  assert root.infoFrame.infoVars['Firmware version'].get() == '3.20'
  gui['listApps'].assert_not_called()

  # Transition to unsupported camera (ILCE-7M3): Info stays normal, Install disables immediately
  info_7m3 = {
   'connected': True, 'physicalDetected': True, 'appConnected': True,
   'status': 'ready', 'mode': 'MTP', 'name': 'ILCE-7M3', 'model': 'ILCE-7M3',
   'app_installation_supported': False,
   'app_installation_reason': 'This model is not listed as PMCA app-capable in the upstream device reference.',
  }
  root.onCameraStatusUpdate(info_7m3)
  root._processQueue()
  root.update()
  assert str(root.infoFrame.infoButton['state']) == 'normal'
  assert str(root.installerFrame.installButton['state']) == 'disabled'
  assert root.infoFrame.infoVars['Model'].get() == 'ILCE-7M3'
  assert root.infoFrame.infoVars['App Support'].get() == 'Not supported (No PMCA subsystem)'

  # Disconnect: fields reset to '—', both buttons disabled
  root.onCameraStatusUpdate(None)
  root._processQueue()
  root.update()
  assert str(root.infoFrame.infoButton['state']) == 'disabled'
  assert str(root.installerFrame.installButton['state']) == 'disabled'
  assert root.infoFrame.infoVars['Model'].get() == '—'
finally:
 if root is not None:
  fetch_t = getattr(root, '_fetchInfoThread', None)
  if fetch_t and fetch_t.is_alive():
   fetch_t.join(timeout=1.0)
  root._processQueue()
  root.destroy()
 sys.stdout, sys.stderr = originalStreams
print('PASS: real Tk controls, queue, worker, log, empty APK guard, and no automatic networking')
