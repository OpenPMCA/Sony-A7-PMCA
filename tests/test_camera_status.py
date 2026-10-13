"""Unit tests for camera status monitoring, capability discovery, and serialization locking."""
import contextlib
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

repo_root = str(Path(__file__).resolve().parents[1])
if repo_root not in sys.path:
 sys.path.insert(0, repo_root)

from pmca.commands import usb
from pmca.usb import MtpDeviceInfo


class CameraStatusTest(unittest.TestCase):
 def setUp(self):
  usb.set_camera_busy(False)
  usb.set_last_verified_camera_status(None)

 def test_camera_busy_state_without_prior_connection_does_not_assert_connected(self):
  """Verify that application download busy state does NOT falsely assert physical or app connection."""
  usb.set_camera_busy(True)
  try:
   with patch.object(usb, 'importDriver') as mock_driver, \
        patch.object(usb, 'getPassiveUsbDevice', return_value=None):
    status = usb.getCameraStatus()
    self.assertTrue(status['busy'])
    self.assertEqual(status['status'], 'busy')
    self.assertFalse(status['connected'], "Must NOT claim connected without prior verified camera!")
    self.assertFalse(status['appConnected'])
    self.assertFalse(status['physicalDetected'])
    mock_driver.assert_not_called()
  finally:
   usb.set_camera_busy(False)

 def test_camera_busy_state_with_prior_connection_preserves_provenance(self):
  """Verify that when a camera was previously verified, busy state preserves model/mode without re-probing."""
  prior = {
   'connected': True,
   'physicalDetected': True,
   'appConnected': True,
   'status': 'ready',
   'busy': False,
   'name': 'ILCE-7',
   'model': 'ILCE-7',
   'mode': 'MTP',
   'serial': '1234567',
  }
  usb.set_last_verified_camera_status(prior)
  usb.set_camera_busy(True)
  try:
   with patch.object(usb, 'importDriver') as mock_driver:
    status = usb.getCameraStatus()
    self.assertTrue(status['busy'])
    self.assertEqual(status['status'], 'busy')
    self.assertTrue(status['connected'])
    self.assertEqual(status['name'], 'ILCE-7')
    self.assertEqual(status['mode'], 'Busy')
    self.assertEqual(status['source_mode'], 'MTP')
    mock_driver.assert_not_called()
  finally:
   usb.set_camera_busy(False)

 def test_camera_operation_lock_serialization(self):
  """Verify that camera_operation serializes access across threads."""
  entered = threading.Event()
  release = threading.Event()
  acquired_second = []

  def worker1():
   with usb.camera_operation(blocking=True):
    entered.set()
    release.wait(timeout=2)

  def worker2():
   entered.wait(timeout=2)
   try:
    with usb.camera_operation(blocking=False):
     acquired_second.append(True)
   except usb.CameraBusyException:
    acquired_second.append(False)

  t1 = threading.Thread(target=worker1)
  t2 = threading.Thread(target=worker2)
  t1.start()
  t2.start()
  t2.join(timeout=3)
  release.set()
  t1.join(timeout=3)

  self.assertEqual(acquired_second, [False])

 def test_physical_usb_detected_with_access_denied_prevents_false_ready(self):
  """P0 Regression: PermissionError/access_denied must return appConnected=False and connected=False."""
  mock_passive = {
   'name': 'ILCE-7',
   'serial': '1234567',
   'mode': 'MTP / PTP (Class 6/1/1)',
   'vendor': 'Sony (0x054c)',
   'pid': 0x054c,
  }
  with patch.object(usb, 'getPassiveUsbDevice', return_value=mock_passive), \
       patch.object(usb, 'importDriver', side_effect=PermissionError('Camera access denied')):
   status = usb.getCameraStatus('libusb-mtp')
   self.assertFalse(status['connected'], "Must NOT report connected=True on access denied!")
   self.assertFalse(status['appConnected'])
   self.assertTrue(status['physicalDetected'])
   self.assertEqual(status['status'], 'access_denied')
   self.assertIn('access denied', status['failure_reason'].lower())
   self.assertEqual(status['name'], 'ILCE-7')

 def test_no_device_returns_disconnected(self):
  """Verify that when no Sony device is on the bus, getCameraStatus reports disconnected."""
  with patch.object(usb, 'getPassiveUsbDevice', return_value=None), \
       patch.object(usb, 'importDriver') as mock_import:
   mock_driver = Mock()
   mock_driver.listDevices.return_value = []
   mock_import.return_value = contextlib.nullcontext(mock_driver)
   status = usb.getCameraStatus('libusb-mtp')
   self.assertFalse(status['connected'])
   self.assertFalse(status['physicalDetected'])
   self.assertEqual(status['status'], 'disconnected')

 def test_mtp_mode_reports_ready_and_extended_capabilities(self):
  """Verify that successful MTP query extracts model, version, capabilities, and honest shutter status."""
  mock_passive = {'name': 'ILCE-7', 'serial': '1234567', 'mode': 'MTP'}
  mock_info = MtpDeviceInfo(
   manufacturer='Sony',
   model='ILCE-7',
   serialNumber='1234567',
   operationsSupported={0x9280, 0x9281, 0x9282},
   vendorExtension='',
   version='3.20',
   devicePropertiesSupported={0x5001, 0xd001},
   eventsSupported={0x4001},
   captureFormats={0x3001},
   imageFormats={0x3801},
  )

  mock_drv = Mock()
  mock_mtp = Mock()
  mock_mtp.getDeviceInfo.return_value = mock_info

  with patch.object(usb, 'getPassiveUsbDevice', return_value=mock_passive), \
       patch.object(usb, 'importDriver') as mock_import, \
       patch.object(usb, 'MtpDevice', return_value=mock_mtp), \
       patch.object(usb, 'isSonyMtpCamera', return_value=True), \
       patch.object(usb, 'isSonyMtpAppInstallCamera', return_value=False):
   mock_driver = Mock()
   mock_driver.listDevices.return_value = [(Mock(), usb.USB_CLASS_PTP, mock_drv)]
   mock_import.return_value = contextlib.nullcontext(mock_driver)

   status = usb.getCameraStatus('libusb-mtp')
   self.assertTrue(status['connected'])
   self.assertTrue(status['appConnected'])
   self.assertTrue(status['physicalDetected'])
   self.assertEqual(status['status'], 'ready')
   self.assertEqual(status['mode'], 'MTP')
   self.assertEqual(status['name'], 'ILCE-7')
   self.assertEqual(status['ptp_device_version'], '3.20')
   self.assertEqual(status['firmware_version'], 'Unavailable without firmware query')
   self.assertEqual(status['shutter_count']['available'], False)
   self.assertIn(0x9280, status['capabilities'])
   mock_mtp.closeSession.assert_called_once()

 def test_app_install_mode_classified_properly(self):
  """Verify that when camera is in app-install mode, it is classified as App installation, not Disconnected."""
  mock_passive = {'name': 'ILCE-7', 'serial': '1234567', 'mode': 'App Install'}
  mock_info = MtpDeviceInfo(
   manufacturer='Sony',
   model='ILCE-7',
   serialNumber='1234567',
   operationsSupported={0x9488, 0x9489},
   vendorExtension='sony.net/SEN_PRXY_MSG:1.0',
   version='3.20',
  )

  mock_drv = Mock()
  mock_mtp = Mock()
  mock_mtp.getDeviceInfo.return_value = mock_info

  with patch.object(usb, 'getPassiveUsbDevice', return_value=mock_passive), \
       patch.object(usb, 'importDriver') as mock_import, \
       patch.object(usb, 'MtpDevice', return_value=mock_mtp), \
       patch.object(usb, 'isSonyMtpCamera', return_value=False), \
       patch.object(usb, 'isSonyMtpAppInstallCamera', return_value=True):
   mock_driver = Mock()
   mock_driver.listDevices.return_value = [(Mock(), usb.USB_CLASS_PTP, mock_drv)]
   mock_import.return_value = contextlib.nullcontext(mock_driver)

   status = usb.getCameraStatus('libusb-mtp')
   self.assertTrue(status['connected'])
   self.assertTrue(status['appConnected'])
   self.assertEqual(status['mode'], 'App installation')
   self.assertEqual(status['status'], 'ready')

 def test_successful_mtp_probe_does_not_call_passive_usb_subprocess(self):
  """Verify normal MTP heartbeat does not spawn ioreg / getPassiveUsbDevice."""
  mock_info = MtpDeviceInfo(
   manufacturer='Sony',
   model='ILCE-7',
   serialNumber='1234567',
   operationsSupported={0x9280, 0x9281, 0x9282},
   vendorExtension='',
   version='3.20',
  )
  mock_drv = Mock()
  mock_mtp = Mock()
  mock_mtp.getDeviceInfo.return_value = mock_info
  mock_driver = Mock()
  mock_driver.listDevices.return_value = [(Mock(), usb.USB_CLASS_PTP, mock_drv)]

  with patch.object(usb, 'getPassiveUsbDevice', side_effect=AssertionError('getPassiveUsbDevice must not run on successful MTP probe')) as mock_passive, \
       patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(mock_driver)), \
       patch.object(usb, 'MtpDevice', return_value=mock_mtp):
   status = usb.getCameraStatus('libusb-mtp', quiet=True)
  self.assertEqual(status['status'], 'ready')
  self.assertTrue(status['appConnected'])
  mock_passive.assert_not_called()

 def test_macos_mass_storage_skipped_by_mtp_driver_is_not_reported_as_access_denied(self):
  """Verify physical MSC camera skipped by libusb-mtp gives camera-menu MTP guidance, not ptpcamerad access_denied."""
  mock_passive = {
   'name': 'ILCE-7',
   'serial': '1234567',
   'mode': 'Mass Storage (Class 8)',
   'vendor': 'Sony (0x054c)',
   'pid': 0x054c,
  }
  mock_driver = Mock()
  mock_driver.listDevices.return_value = []
  with patch.object(usb, 'getPassiveUsbDevice', return_value=mock_passive), \
       patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(mock_driver)):
   status = usb.getCameraStatus('libusb-mtp', quiet=True)
  self.assertFalse(status['connected'])
  self.assertFalse(status['appConnected'])
  self.assertTrue(status['physicalDetected'])
  self.assertIs(status['app_installation_supported'], False)
  self.assertNotEqual(status['status'], 'access_denied')
  self.assertEqual(status['status'], 'unsupported')
  self.assertIn('mass storage', status['failure_reason'].lower())
  self.assertIn('mtp', status['failure_reason'].lower())
  self.assertNotIn('ptpcamerad', status['failure_reason'].lower())

 def test_every_status_branch_includes_explicit_install_eligibility_and_reason(self):
  """Verify all non-MTP status branches fail closed with explicit boolean app_installation_supported and reason."""
  # 1. Disconnected
  mock_driver = Mock()
  mock_driver.listDevices.return_value = []
  with patch.object(usb, 'getPassiveUsbDevice', return_value=None), \
       patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(mock_driver)):
   st_disc = usb.getCameraStatus('libusb-mtp', quiet=True)
  self.assertIs(st_disc.get('app_installation_supported'), False)
  self.assertTrue(isinstance(st_disc.get('app_installation_reason'), str) and st_disc['app_installation_reason'])

  # 2. Unverified (probe_communication=False)
  with patch.object(usb, 'getPassiveUsbDevice', return_value={'name': 'ILCE-7', 'mode': 'MTP / PTP (Class 6/1/1)', 'serial': '123'}):
   st_unv = usb.getCameraStatus('libusb-mtp', probe_communication=False, quiet=True)
  self.assertIs(st_unv.get('app_installation_supported'), False)
  self.assertTrue(isinstance(st_unv.get('app_installation_reason'), str) and st_unv['app_installation_reason'])

  # 3. Access denied
  with patch.object(usb, 'getPassiveUsbDevice', return_value={'name': 'ILCE-7', 'mode': 'MTP / PTP (Class 6/1/1)', 'serial': '123'}), \
       patch.object(usb, 'importDriver', side_effect=PermissionError('denied')):
   st_den = usb.getCameraStatus('libusb-mtp', quiet=True)
  self.assertIs(st_den.get('app_installation_supported'), False)
  self.assertTrue(isinstance(st_den.get('app_installation_reason'), str) and st_den['app_installation_reason'])

  # 4. MSC generic inquiry (DSC) fails closed
  from tests.test_msc_driver_contract import StrictMscDriver
  msc_drv = StrictMscDriver()
  msc_drv.inquiry_data = b'\x00\x80\x02\x02\x1f\x00\x00\x00Sony    DSC             '
  mock_driver.listDevices.return_value = [(Mock(), usb.USB_CLASS_MSC, msc_drv)]
  with patch.object(usb, 'getPassiveUsbDevice', return_value=None), \
       patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(mock_driver)):
   st_msc = usb.getCameraStatus('libusb', quiet=True)
  self.assertEqual(st_msc['mode'], 'Mass Storage')
  self.assertIs(st_msc.get('app_installation_supported'), False)
  self.assertTrue(isinstance(st_msc.get('app_installation_reason'), str) and st_msc['app_installation_reason'])

 def test_passive_ioreg_does_not_count_child_interfaces_as_multiple_cameras(self):
  """Verify getPassiveUsbDevice ignores child interface dicts that also carry idVendor=0x054c."""
  import plistlib
  dev_tree = [{
   'IOObjectClass': 'IOUSBHostDevice',
   'idVendor': 0x054c,
   'idProduct': 0x0994,
   'USB Product Name': 'ILCE-7',
   'USB Serial Number': '12345678',
   'IORegistryEntryChildren': [{
    'IOObjectClass': 'IOUSBHostInterface',
    'idVendor': 0x054c,
    'idProduct': 0x0994,
    'bInterfaceClass': 6,
    'bInterfaceSubClass': 1,
    'bInterfaceProtocol': 1,
   }],
  }]
  proc_dev = Mock(returncode=0, stdout=plistlib.dumps(dev_tree))
  with patch('sys.platform', 'darwin'), \
       patch('subprocess.run', return_value=proc_dev) as mock_run:
   passive = usb.getPassiveUsbDevice()
  self.assertIsNotNone(passive)
  self.assertEqual(passive['name'], 'ILCE-7')
  self.assertEqual(passive['mode'], 'MTP / PTP (Class 6/1/1)')
  # Because child interface was already in dev_tree, second ioreg call is unnecessary
  self.assertEqual(mock_run.call_count, 1)

 def _make_generic_msc_driver(self, dev_obj, inquiry_reply=None):
  from types import SimpleNamespace
  from pmca.usb.driver.generic import BaseUsbBackend, MscBbbDriver, MscCommandStatusWrapper, MscCommandBlockWrapper

  class FakeUsbBackend(BaseUsbBackend):
   def __init__(self, dev):
    self.dev = dev
    self.reset_calls = 0
    self.read_calls = 0
    self.write_calls = 0
    self._pending_in = []

   def getEndpoints(self):
    return [
     SimpleNamespace(bmAttributes=2, bEndpointAddress=0x81),
     SimpleNamespace(bmAttributes=2, bEndpointAddress=0x02),
    ]

   def reset(self):
    self.reset_calls += 1
    raise AssertionError('reset() / detach_kernel_driver() must not be called when kernel ownership is active or unknown')

   def clearHalt(self, ep):
    pass

   def getId(self):
    return (0x054c, 0x0994)

   def write(self, ep, data):
    self.write_calls += 1
    cbw = MscCommandBlockWrapper.unpack(data)
    if inquiry_reply is not None:
     self._pending_in.append(inquiry_reply[:cbw.dataTransferLength])
     self._pending_in.append(MscCommandStatusWrapper.pack(
      signature=b'USBS', tag=cbw.tag, dataResidue=0, status=0
     ))

   def read(self, ep, length, timeout=None):
    self.read_calls += 1
    if self._pending_in:
     return self._pending_in.pop(0)
    raise AssertionError('Unexpected bulk read on guarded generic MSC driver')

   def classInterfaceRequestOut(self, request, value, index, data=b''):
    pass

   def vendorRequestOut(self, request, value, index, data=b''):
    pass

  backend = FakeUsbBackend(dev_obj)
  return MscBbbDriver(backend), backend

 def test_generic_msc_active_kernel_driver_skips_reset_and_detach_on_status(self):
  """Verify generic MscBbbDriver with is_kernel_driver_active(0)==True does not reset/detach or read."""
  usb.set_last_verified_camera_status({
   'model': 'ILCE-7', 'name': 'ILCE-7', 'serial': 'vendor-serial-1',
   'raw_serial': 'transport-1', 'shutter_count': {'available': True, 'value': 1234},
  })
  dev = Mock()
  dev.is_kernel_driver_active.return_value = True
  dev.detach_kernel_driver.side_effect = AssertionError('detach_kernel_driver must not be called')
  drv, backend = self._make_generic_msc_driver(dev)

  mock_driver = Mock()
  mock_driver.listDevices.return_value = [(Mock(), usb.USB_CLASS_MSC, drv)]
  with patch.object(usb, 'getPassiveUsbDevice', return_value=None), \
       patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(mock_driver)):
   status = usb.getCameraStatus('libusb', quiet=True)

  self.assertIsNone(usb.get_last_verified_camera_status())
  self.assertEqual(backend.reset_calls, 0)
  self.assertEqual(backend.read_calls, 0)
  dev.detach_kernel_driver.assert_not_called()
  self.assertFalse(status['connected'])
  self.assertFalse(status['appConnected'])
  self.assertTrue(status['physicalDetected'])
  self.assertIs(status['app_installation_supported'], False)
  self.assertEqual(status['status'], 'unsupported')
  self.assertEqual(status['mode'], 'Mass Storage')
  self.assertIn('mtp', status['failure_reason'].lower())

 def test_generic_msc_unknown_kernel_ownership_fails_closed_without_reset(self):
  """Verify generic MscBbbDriver when is_kernel_driver_active raises or is unavailable fails closed without reset."""
  for bad_dev in (
   Mock(is_kernel_driver_active=Mock(side_effect=NotImplementedError('unsupported'))),
   Mock(is_kernel_driver_active=Mock(side_effect=RuntimeError('libusb error'))),
   None,
  ):
   with self.subTest(bad_dev=bad_dev):
    usb.set_last_verified_camera_status({'model': 'ILCE-7', 'serial': 'vendor-serial-1'})
    drv, backend = self._make_generic_msc_driver(bad_dev)
    mock_driver = Mock()
    mock_driver.listDevices.return_value = [(Mock(), usb.USB_CLASS_MSC, drv)]
    with patch.object(usb, 'getPassiveUsbDevice', return_value=None), \
         patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(mock_driver)):
     status = usb.getCameraStatus('libusb', quiet=True)
    self.assertIsNone(usb.get_last_verified_camera_status())
    self.assertEqual(backend.reset_calls, 0)
    self.assertEqual(backend.read_calls, 0)
    self.assertFalse(status['connected'])
    self.assertFalse(status['appConnected'])
    self.assertTrue(status['physicalDetected'])
    self.assertIs(status['app_installation_supported'], False)
    self.assertEqual(status['status'], 'unsupported')
    self.assertIn('ownership', status['failure_reason'].lower())

 def test_generic_msc_confirmed_unbound_kernel_driver_queries_inquiry(self):
  """Verify generic MscBbbDriver with is_kernel_driver_active(0) is False proceeds with Inquiry."""
  dev = Mock()
  dev.is_kernel_driver_active.return_value = False
  inquiry_bytes = b'\x00\x80\x02\x02\x1f\x00\x00\x00Sony    DSC             '
  drv, backend = self._make_generic_msc_driver(dev, inquiry_reply=inquiry_bytes)
  # Allow reset() when unbound
  backend.reset = Mock()

  mock_driver = Mock()
  mock_driver.listDevices.return_value = [(Mock(), usb.USB_CLASS_MSC, drv)]
  with patch.object(usb, 'getPassiveUsbDevice', return_value=None), \
       patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(mock_driver)):
   status = usb.getCameraStatus('libusb', quiet=True)

  backend.reset.assert_called_once()
  self.assertTrue(status['connected'])
  self.assertTrue(status['appConnected'])
  self.assertEqual(status['mode'], 'Mass Storage')
  self.assertEqual(status['model'], 'DSC')
  self.assertIs(status['app_installation_supported'], False)


if __name__ == '__main__':
 unittest.main()
