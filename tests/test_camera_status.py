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


if __name__ == '__main__':
 unittest.main()
