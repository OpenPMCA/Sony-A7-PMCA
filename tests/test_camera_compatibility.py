"""Camera eligibility is not physical verification or a successful USB handshake."""
import contextlib
import importlib
import importlib.util
import io
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pmca.commands import usb
from pmca.usb import MtpDeviceInfo
from tests.apk_fixture import apkFixture


STILL_MODELS = (
 'ILCE-7', 'ILCE-7R', 'ILCE-7S', 'ILCE-7M2', 'ILCE-7RM2', 'ILCE-7SM2',
 'ILCE-5000', 'ILCE-5100', 'ILCE-6000', 'ILCE-6300', 'ILCE-6500', 'ILCE-QX1',
 'NEX-5R', 'NEX-5T', 'NEX-6', 'DSC-HX60', 'DSC-HX90', 'DSC-HX400',
 'DSC-RX1RM2', 'DSC-RX10M2', 'DSC-RX10M3', 'DSC-RX100M3',
 'DSC-RX100M4', 'DSC-RX100M5', 'DSC-WX500',
)
NORMAL_OPERATIONS = {0x1001, 0x1002, 0x1003, 0x9280, 0x9281, 0x9282}
INSTALL_OPERATIONS = {0x1001, 0x9488, 0x9489, 0x948c, 0x948d}


def device_info(model, serial='transport-one', operations=None, install=False):
 return MtpDeviceInfo(
  'Sony Corporation', model, serial,
  operations if operations is not None else INSTALL_OPERATIONS if install else NORMAL_OPERATIONS,
  'sony.net/SEN_PRXY_MSG:1.0' if install else '', 'protocol-version',
 )


class CameraEligibilityTest(unittest.TestCase):
 def compatibility(self):
  self.assertIsNotNone(importlib.util.find_spec('pmca.compatibility'), 'Shared camera eligibility must be evidence-based')
  return importlib.import_module('pmca.compatibility')

 def test_all_reference_still_models_are_pmca_eligible_not_all_hardware_verified(self):
  compatibility = self.compatibility()
  for model in STILL_MODELS:
   with self.subTest(model=model):
    support = compatibility.get_camera_support(model)
    self.assertIs(support['pmca_apps'], True)
    self.assertEqual(support['model'], model)
    self.assertEqual(support['installation_tested'], model == 'ILCE-7')

 def test_known_non_pmca_models_are_not_invented_as_app_capable(self):
  compatibility = self.compatibility()
  for model in ['ILCE-7M3', 'ILCE-7RM3', 'ILCE-9', 'ILCE-6400', 'ILCE-6600', 'ILCA-77M2']:
   with self.subTest(model=model):
    self.assertIs(compatibility.get_camera_support(model)['pmca_apps'], False)

 def test_unknown_model_remains_unknown_instead_of_supported(self):
  support = self.compatibility().get_camera_support('ILCE-UNKNOWN')
  self.assertIsNone(support['pmca_apps'])
  self.assertFalse(support['installation_tested'])

 def test_v_suffix_alias_uses_primary_cybershot_profile(self):
  compatibility = self.compatibility()
  for alias, canonical in [('DSC-HX60V', 'DSC-HX60'), ('DSC-HX90V', 'DSC-HX90'), ('DSC-HX400V', 'DSC-HX400')]:
   with self.subTest(alias=alias):
    support = compatibility.get_camera_support(alias)
    self.assertEqual(support['model'], canonical)
    self.assertTrue(support['pmca_apps'])

 def test_counter_generation_is_separate_from_app_eligibility(self):
  compatibility = self.compatibility()
  self.assertEqual(compatibility.get_camera_support('ILCE-7')['shutter_layout'], 'tag9050a')
  self.assertEqual(compatibility.get_camera_support('ILCE-7RM2')['shutter_layout'], 'tag9050b')
  for model in ['NEX-5R', 'DSC-RX100M4']:
   with self.subTest(model=model):
    support = compatibility.get_camera_support(model)
    self.assertTrue(support['pmca_apps'])
    self.assertIsNone(support['shutter_layout'])


class CameraStatusCompatibilityTest(unittest.TestCase):
 def setUp(self):
  usb.set_camera_busy(False)
  usb.set_last_verified_camera_status(None)
  self.addCleanup(usb.set_camera_busy, False)
  self.addCleanup(usb.set_last_verified_camera_status, None)

 def status(self, info):
  driver = Mock()
  driver.listDevices.return_value = [(SimpleNamespace(idVendor=0x054c), usb.USB_CLASS_PTP, Mock())]
  mtp = Mock()
  mtp.getDeviceInfo.return_value = info
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(driver)), \
       patch.object(usb, 'getPassiveUsbDevice', return_value=None), \
       patch.object(usb, 'MtpDevice', return_value=mtp):
   result = usb.getCameraStatus('libusb-mtp', quiet=True)
  return result

 def test_vendor_mtp_connection_does_not_enable_install_on_non_pmca_body(self):
  result = self.status(device_info('ILCE-7M3'))
  self.assertTrue(result['appConnected'], 'Read-only communication can work without camera apps')
  self.assertIs(result.get('app_installation_supported'), False)
  self.assertIn('PMCA', result.get('app_installation_reason', ''))

 def test_installable_protocol_is_preserved_across_both_alpha_generations(self):
  for model in ['ILCE-7', 'ILCE-7RM2', 'ILCE-6300', 'NEX-5R', 'DSC-RX100M4']:
   with self.subTest(model=model):
    result = self.status(device_info(model))
    self.assertTrue(result['appConnected'])
    self.assertIs(result.get('app_installation_supported'), True)

 def test_missing_vendor_operations_never_enable_install_from_model_name_alone(self):
  result = self.status(device_info('ILCE-7', operations={0x1001, 0x1002}))
  self.assertIs(result.get('app_installation_supported'), False)

 def test_genuine_app_installer_protocol_confirms_an_unlisted_model(self):
  result = self.status(device_info('ILCE-UNKNOWN', install=True))
  self.assertEqual(result['mode'], 'App installation')
  self.assertIs(result.get('app_installation_supported'), True)

 def test_different_camera_does_not_inherit_serial_firmware_or_counter(self):
  usb.set_last_verified_camera_status({
   'model': 'ILCE-7', 'name': 'ILCE-7', 'raw_serial': 'transport-one',
   'serial': 'vendor-body-one', 'firmware_version': 'body-firmware-one',
   'shutter_count': {'available': True, 'value': 70000, 'source': 'old-photo'},
  })
  result = self.status(device_info('ILCE-7RM2', serial='transport-two'))
  self.assertNotEqual(result['serial'], 'vendor-body-one')
  self.assertNotEqual(result['firmware_version'], 'body-firmware-one')
  self.assertIsNone(result['shutter_count']['value'])

 def test_same_model_different_transport_identity_does_not_inherit_counter(self):
  usb.set_last_verified_camera_status({
   'model': 'ILCE-7', 'raw_serial': 'transport-one', 'serial': 'vendor-body-one',
   'shutter_count': {'available': True, 'value': 70000},
  })
  result = self.status(device_info('ILCE-7', serial='transport-two'))
  self.assertIsNone(result['shutter_count']['value'])

 def test_transport_token_is_not_guessed_to_be_a_vendor_body_serial(self):
  token = '00000000000000003282630012345678'
  result = self.status(device_info('ILCE-7', serial=token))
  self.assertEqual(result['raw_serial'], token)
  self.assertIsNone(result['serial'], 'Only a vendor query should populate body serial')

 def test_known_ineligible_body_is_rejected_before_installer_mode_switch(self):
  device = object.__new__(usb.SonyMtpExtCmdDevice)
  device.getDeviceInfo = Mock(return_value=device_info('ILCE-7M3'))
  app_device = object.__new__(usb.SonyMtpAppInstallDevice)
  camera = Mock()
  output = io.StringIO()
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(Mock())), \
       patch.object(usb, 'getDevice', return_value=device), \
       patch.object(usb, 'SonyExtCmdCamera', return_value=camera), \
       patch.object(usb, 'listDevices', return_value=iter([app_device])), \
       patch.object(usb, 'installApp', return_value=None), \
       patch.object(usb.time, 'sleep'), contextlib.redirect_stdout(output):
   with self.assertRaises(usb.CameraOperationError) as ctx:
    usb.installCommand('libusb-mtp', apkFile=io.BytesIO(apkFixture()))
  self.assertFalse(ctx.exception.outcome_unknown)
  camera.switchToAppInstaller.assert_not_called()
  self.assertIn('PMCA', output.getvalue())


 def test_short_sony_manufacturer_retains_actual_vendor_protocol_support(self):
  info = device_info('ILCE-7RM2')._replace(manufacturer='Sony')
  result = self.status(info)
  self.assertIs(result['app_installation_supported'], True)

 def test_every_reference_family_preserves_selected_device_through_installer_switch(self):
  for model in STILL_MODELS:
   with self.subTest(model=model):
    device = object.__new__(usb.SonyMtpExtCmdDevice)
    device.getDeviceInfo = Mock(return_value=device_info(model))
    app_device = object.__new__(usb.SonyMtpAppInstallDevice)
    app_device.getDeviceInfo = Mock(return_value=device_info(model, install=True))
    camera = Mock()
    expected = {'deviceinfo': {'name': model}}
    with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(Mock())), \
         patch.object(usb, 'getDevice', return_value=device), \
         patch.object(usb, 'SonyExtCmdCamera', return_value=camera), \
         patch.object(usb, 'listDevices', return_value=[app_device]), \
         patch.object(usb, 'installApp', return_value=expected) as install, \
         patch.object(usb.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
     result = usb.installCommand('libusb-mtp', apkFile=io.BytesIO(apkFixture()))
    self.assertEqual(result, expected)
    camera.switchToAppInstaller.assert_called_once()
    self.assertIs(install.call_args.args[0], app_device)

 def test_same_verified_camera_keeps_vendor_metadata_without_guessed_identity(self):
  usb.set_last_verified_camera_status({
   'model': 'ILCE-7RM2', 'raw_serial': 'transport-one', 'serial': 'vendor-body-one',
   'firmware_version': 'known-body-firmware', 'shutter_count': {'available': True, 'value': 70000},
  })
  result = self.status(device_info('ILCE-7RM2'))
  self.assertEqual(result['serial'], 'vendor-body-one')
  self.assertEqual(result['firmware_version'], 'known-body-firmware')
  self.assertEqual(result['shutter_count']['value'], 70000)


 def test_multiple_attached_cameras_are_not_arbitrarily_reported_as_install_ready(self):
  driver = Mock()
  driver.listDevices.return_value = [
   (SimpleNamespace(idVendor=0x054c), usb.USB_CLASS_PTP, Mock()),
   (SimpleNamespace(idVendor=0x054c), usb.USB_CLASS_PTP, Mock()),
  ]
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(driver)), \
       patch.object(usb, 'getPassiveUsbDevice', return_value=None), \
       patch.object(usb, 'MtpDevice') as mtp:
   result = usb.getCameraStatus('libusb-mtp', quiet=True)
  self.assertFalse(result['appConnected'])
  self.assertFalse(result.get('app_installation_supported'))
  self.assertTrue(result['physicalDetected'])
  self.assertIn('one camera', result['failure_reason'].lower())
  mtp.assert_not_called()


 def test_contended_probe_keeps_prior_model_and_support_without_inventing_camera(self):
  usb.set_last_verified_camera_status({
   'model': 'ILCE-7RM2', 'name': 'ILCE-7RM2', 'mode': 'MTP', 'source_mode': 'MTP',
   'connected': True, 'appConnected': True, 'physicalDetected': True,
   'serial': 'vendor-body-one', 'app_installation_supported': True,
  })
  with patch.object(usb, 'getPassiveUsbDevice', return_value=None), \
       patch.object(usb, 'camera_operation', side_effect=usb.CameraBusyException):
   result = usb.getCameraStatus('libusb-mtp')
  self.assertEqual(result['model'], 'ILCE-7RM2')
  self.assertTrue(result['busy'])
  self.assertTrue(result['app_installation_supported'])

 def test_contended_first_probe_cannot_invent_a_verified_connection(self):
  with patch.object(usb, 'getPassiveUsbDevice', return_value=None), \
       patch.object(usb, 'camera_operation', side_effect=usb.CameraBusyException):
   result = usb.getCameraStatus('libusb-mtp')
  self.assertFalse(result['connected'])
  self.assertFalse(result['appConnected'])
  self.assertTrue(result['busy'])


 def test_disconnection_clears_cached_identity_before_a_later_busy_operation(self):
  usb.set_last_verified_camera_status({
   'model': 'ILCE-7', 'name': 'ILCE-7', 'connected': True, 'appConnected': True,
   'raw_serial': 'transport-one', 'serial': 'vendor-body-one',
   'shutter_count': {'available': True, 'value': 70000},
  })
  driver = Mock()
  driver.listDevices.return_value = []
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(driver)), \
       patch.object(usb, 'getPassiveUsbDevice', return_value=None):
   disconnected = usb.getCameraStatus('libusb-mtp', quiet=True)
  self.assertFalse(disconnected['connected'])
  self.assertIsNone(usb.get_last_verified_camera_status())
  usb.set_camera_busy(True)
  try:
   with patch.object(usb, 'getPassiveUsbDevice', return_value=None):
    busy = usb.getCameraStatus('libusb-mtp', quiet=True)
   self.assertFalse(busy['appConnected'])
  finally:
   usb.set_camera_busy(False)

 def test_all_zero_transport_serial_cannot_link_two_same_model_bodies(self):
  usb.set_last_verified_camera_status({
   'model': 'ILCE-7RM2', 'raw_serial': '0' * 32, 'serial': 'vendor-body-one',
   'firmware_version': 'old-body-firmware', 'shutter_count': {'available': True, 'value': 70000},
  })
  result = self.status(device_info('ILCE-7RM2', serial='0' * 32))
  self.assertIsNone(result['serial'])
  self.assertIsNone(result['shutter_count']['value'])

 def test_incomplete_proxy_protocol_cannot_be_accepted_by_installer_class_alone(self):
  device = object.__new__(usb.SonyMtpAppInstallDevice)
  device.getDeviceInfo = Mock(return_value=device_info('ILCE-7M3', operations={0x1001}, install=False))
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(Mock())), \
       patch.object(usb, 'getDevice', return_value=device), \
       patch.object(usb, 'installApp', return_value={}) as install, \
       contextlib.redirect_stdout(io.StringIO()) as output:
   with self.assertRaises(usb.CameraOperationError) as ctx:
    usb.installCommand('libusb-mtp', apkFile=io.BytesIO(apkFixture()))
  self.assertFalse(ctx.exception.outcome_unknown)
  install.assert_not_called()
  self.assertIn('PMCA', output.getvalue())

 def test_complete_unlisted_proxy_protocol_can_continue_without_a_model_whitelist(self):
  device = object.__new__(usb.SonyMtpAppInstallDevice)
  device.getDeviceInfo = Mock(return_value=device_info('ILCE-UNKNOWN', install=True))
  expected = {'deviceinfo': {'name': 'ILCE-UNKNOWN'}}
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(Mock())), \
       patch.object(usb, 'getDevice', return_value=device), \
       patch.object(usb, 'installApp', return_value=expected) as install, \
       contextlib.redirect_stdout(io.StringIO()):
   result = usb.installCommand('libusb-mtp', apkFile=io.BytesIO(apkFixture()))
  self.assertEqual(result, expected)
  self.assertIs(install.call_args.args[0], device)


 def test_app_install_readonly_info_reuses_current_session_and_flat_gui_fields(self):
  device = object.__new__(usb.SonyMtpAppInstallDevice)
  device.getDeviceInfo = Mock(return_value=device_info('ILCE-7RM2', install=True))
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(Mock())) as driver_import, \
       patch.object(usb, 'getDevice', return_value=device), \
       patch.object(usb, 'getCameraStatus', side_effect=AssertionError('Do not reopen a competing camera session')):
   try:
    result = usb.getReadOnlyCameraInfo('libusb-mtp')
   except AssertionError:
    result = {}
  self.assertEqual(result.get('Model'), 'ILCE-7RM2')
  self.assertEqual(result.get('USB mode'), 'App installation')
  self.assertEqual(result.get('PTP version'), 'protocol-version')
  self.assertIn('App installation', result.get('Shutter note', ''))
  self.assertEqual(driver_import.call_count, 1)


 def test_unverified_probe_invalidates_previous_body_identity(self):
  for passive in [None, {'name': 'ILCE-7RM2', 'serial': 'transport-two', 'mode': 'MTP'}]:
   with self.subTest(passive=passive):
    usb.set_last_verified_camera_status({
     'model': 'ILCE-7', 'raw_serial': 'transport-one', 'serial': 'vendor-body-one',
     'firmware_version': 'old-body-firmware', 'shutter_count': {'available': True, 'value': 70000},
    })
    with patch.object(usb, 'getPassiveUsbDevice', return_value=passive), \
         patch.object(usb, 'importDriver') as driver:
     result = usb.getCameraStatus('libusb-mtp', probe_communication=False)
    self.assertFalse(result['appConnected'])
    self.assertIsNone(usb.get_last_verified_camera_status())
    driver.assert_not_called()

 def test_failed_probe_invalidates_previous_body_identity(self):
  for error in [PermissionError('access denied'), RuntimeError('USB read failed')]:
   with self.subTest(error=error):
    usb.set_last_verified_camera_status({
     'model': 'ILCE-7', 'raw_serial': 'transport-one', 'serial': 'vendor-body-one',
     'shutter_count': {'available': True, 'value': 70000},
    })
    passive = {'name': 'ILCE-7RM2', 'serial': 'transport-two', 'mode': 'MTP'}
    with patch.object(usb, 'getPassiveUsbDevice', return_value=passive), \
         patch.object(usb, 'importDriver', side_effect=error):
     result = usb.getCameraStatus('libusb-mtp', quiet=True)
    self.assertFalse(result['appConnected'])
    self.assertIsNone(usb.get_last_verified_camera_status())

 def test_inaccessible_or_non_mtp_device_drops_previous_mtp_body_cache(self):
  for device_class in [None, usb.USB_CLASS_VENDOR_SPECIFIC, usb.USB_CLASS_MSC]:
   with self.subTest(device_class=device_class):
    usb.set_last_verified_camera_status({
     'model': 'ILCE-7', 'raw_serial': 'transport-one', 'serial': 'vendor-body-one',
     'shutter_count': {'available': True, 'value': 70000},
    })
    driver = Mock()
    driver.listDevices.return_value = [] if device_class is None else [(Mock(), device_class, Mock())]
    msc = Mock()
    msc.getDeviceInfo.return_value = SimpleNamespace(model='DSC', manufacturer='Sony')
    passive = {'name': 'Sony Camera', 'serial': 'transport-two', 'mode': 'Unknown'}
    with patch.object(usb, 'getPassiveUsbDevice', return_value=passive), \
         patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(driver)), \
         patch.object(usb, 'MscDevice', return_value=msc):
     usb.getCameraStatus('libusb-mtp', quiet=True)
    self.assertIsNone(usb.get_last_verified_camera_status())

 def test_passive_serial_is_never_labeled_as_verified_body_serial(self):
  token = '00000000000000003282630012345678'
  passive = {'name': 'ILCE-7', 'serial': token, 'mode': 'MTP'}
  for state in ['busy', 'unverified', 'inaccessible', 'permission', 'unsupported', 'mass_storage']:
   with self.subTest(state=state):
    usb.set_camera_busy(state == 'busy')
    driver = Mock()
    driver.listDevices.return_value = []
    if state in ['unsupported', 'mass_storage']:
     device_class = usb.USB_CLASS_MSC if state == 'mass_storage' else usb.USB_CLASS_VENDOR_SPECIFIC
     driver.listDevices.return_value = [(Mock(), device_class, Mock())]
    msc = Mock()
    msc.getDeviceInfo.return_value = SimpleNamespace(model='DSC', manufacturer='Sony')
    with patch.object(usb, 'getPassiveUsbDevice', return_value=passive), \
         patch.object(usb, 'importDriver', side_effect=PermissionError('access denied') if state == 'permission' else None,
                      return_value=contextlib.nullcontext(driver)), \
         patch.object(usb, 'MscDevice', return_value=msc):
     result = usb.getCameraStatus('libusb-mtp', probe_communication=state != 'unverified', quiet=True)
    self.assertIsNone(result['serial'])
    self.assertEqual(result.get('raw_serial'), token)
  usb.set_camera_busy(False)

 def test_cli_info_cannot_borrow_firmware_from_a_different_body(self):
  usb.set_last_verified_camera_status({
   'model': 'ILCE-7', 'raw_serial': 'transport-one', 'serial': 'vendor-body-one',
   'firmware_version': 'old-body-firmware',
  })
  device = object.__new__(usb.SonyMtpExtCmdDevice)
  device.getDeviceInfo = Mock(return_value=device_info('ILCE-7RM2', serial='transport-two'))
  camera = Mock()
  camera.getCameraInfo.return_value = SimpleNamespace(modelName='ILCE-7RM2', modelCode='fixture', serial='vendor-body-two')
  camera.getLensInfo.return_value = SimpleNamespace(model=0)
  camera.getGpsData.side_effect = usb.InvalidCommandException()
  updater = Mock()
  updater.init.side_effect = usb.InvalidCommandException()
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(Mock())), \
       patch.object(usb, 'getDevice', return_value=device), \
       patch.object(usb, 'SonyExtCmdCamera', return_value=camera), \
       patch.object(usb, 'SonyUpdaterCamera', return_value=updater), \
       contextlib.redirect_stdout(io.StringIO()):
   result = usb.infoCommand('libusb-mtp')
  self.assertEqual(result['Model'], 'ILCE-7RM2')
  self.assertNotEqual(result['Firmware version'], 'old-body-firmware')

 def test_cli_firmware_query_cannot_write_to_a_different_body_cache(self):
  usb.set_last_verified_camera_status({
   'model': 'ILCE-7', 'raw_serial': 'transport-one', 'serial': 'vendor-body-one',
   'firmware_version': 'old-body-firmware',
  })
  device = object.__new__(usb.SonyMtpExtCmdDevice)
  device.getDeviceInfo = Mock(return_value=device_info('ILCE-7RM2', serial='transport-two'))
  camera = Mock()
  camera.getCameraInfo.return_value = SimpleNamespace(modelName='ILCE-7RM2', modelCode='fixture', serial='vendor-body-two')
  camera.getLensInfo.return_value = SimpleNamespace(model=0)
  camera.getGpsData.side_effect = usb.InvalidCommandException()
  updater = Mock()
  updater.getFirmwareVersion.return_value = ('new-body-firmware', None)
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(Mock())), \
       patch.object(usb, 'getDevice', return_value=device), \
       patch.object(usb, 'SonyExtCmdCamera', return_value=camera), \
       patch.object(usb, 'SonyUpdaterCamera', return_value=updater), \
       contextlib.redirect_stdout(io.StringIO()):
   result = usb.infoCommand('libusb-mtp')
  self.assertEqual(result['Firmware version'], 'new-body-firmware')
  cached = usb.get_last_verified_camera_status()
  self.assertTrue(cached is None or cached.get('model') != 'ILCE-7' or cached.get('firmware_version') == 'old-body-firmware')

 def test_readonly_first_query_populates_install_eligibility_for_busy_status(self):
  device = object.__new__(usb.SonyMtpExtCmdDevice)
  device.getDeviceInfo = Mock(return_value=device_info('ILCE-7RM2'))
  camera = Mock()
  camera.getCameraInfo.return_value = SimpleNamespace(modelName='ILCE-7RM2', modelCode='fixture', serial='vendor-body-one', plist=b'')
  camera.getLensInfo.return_value = SimpleNamespace(model=0)
  camera.getGpsData.side_effect = usb.InvalidCommandException()
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(Mock())), \
       patch.object(usb, 'getDevice', return_value=device), \
       patch.object(usb, 'SonyExtCmdCamera', return_value=camera), \
       patch('pmca.util.shutter.query_mtp_camera_shutter_count', return_value={'available': False, 'value': None, 'reason': 'No image'}):
   usb.getReadOnlyCameraInfo('libusb-mtp')
  usb.set_camera_busy(True)
  try:
   result = usb.getCameraStatus('libusb-mtp')
  finally:
   usb.set_camera_busy(False)
  self.assertEqual(result['model'], 'ILCE-7RM2')
  self.assertIs(result.get('app_installation_supported'), True)
  self.assertEqual(result['camera_support']['shutter_layout'], 'tag9050b')


 def test_readonly_query_invalidates_cache_when_the_camera_disappears(self):
  usb.set_last_verified_camera_status({
   'model': 'ILCE-7', 'serial': 'vendor-body-one', 'raw_serial': 'transport-one',
   'firmware_version': 'old-body-firmware',
  })
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(Mock())), \
       patch.object(usb, 'getDevice', return_value=None):
   result = usb.getReadOnlyCameraInfo('libusb-mtp')
  self.assertIsNone(result)
  self.assertIsNone(usb.get_last_verified_camera_status())

 def test_readonly_failed_mtp_identity_cannot_leave_a_different_body_cached(self):
  usb.set_last_verified_camera_status({
   'model': 'ILCE-7', 'serial': 'vendor-body-one', 'raw_serial': 'transport-one',
   'firmware_version': 'old-body-firmware',
  })
  device = object.__new__(usb.SonyMtpExtCmdDevice)
  device.getDeviceInfo = Mock(side_effect=RuntimeError('DeviceInfo unavailable'))
  camera = Mock()
  camera.getCameraInfo.return_value = SimpleNamespace(modelName='ILCE-7RM2', modelCode='fixture', serial='vendor-body-two', plist=b'')
  camera.getLensInfo.return_value = SimpleNamespace(model=0)
  camera.getGpsData.side_effect = usb.InvalidCommandException()
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(Mock())), \
       patch.object(usb, 'getDevice', return_value=device), \
       patch.object(usb, 'SonyExtCmdCamera', return_value=camera), \
       patch('pmca.util.shutter.query_mtp_camera_shutter_count', return_value={'available': False, 'value': None, 'reason': 'No image'}):
   result = usb.getReadOnlyCameraInfo('libusb-mtp')
  self.assertEqual(result['Model'], 'ILCE-7RM2')
  self.assertNotEqual(result['Firmware version'], 'old-body-firmware')
  self.assertIsNone(usb.get_last_verified_camera_status())

 def test_readonly_installer_identity_cannot_leave_a_different_body_cached(self):
  usb.set_last_verified_camera_status({
   'model': 'ILCE-7', 'serial': 'vendor-body-one', 'raw_serial': 'transport-one',
   'firmware_version': 'old-body-firmware',
  })
  device = object.__new__(usb.SonyMtpAppInstallDevice)
  device.getDeviceInfo = Mock(return_value=device_info('ILCE-7RM2', serial='transport-two', install=True))
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(Mock())), \
       patch.object(usb, 'getDevice', return_value=device):
   result = usb.getReadOnlyCameraInfo('libusb-mtp')
  self.assertEqual(result['Model'], 'ILCE-7RM2')
  self.assertIsNone(usb.get_last_verified_camera_status())


 def test_current_vendor_serial_overrides_a_reused_transport_token(self):
  usb.set_last_verified_camera_status({
   'model': 'ILCE-7', 'raw_serial': 'shared-transport-token', 'serial': 'vendor-body-one',
   'firmware_version': 'old-body-firmware', 'shutter_count': {'available': True, 'value': 70000},
  })
  device = object.__new__(usb.SonyMtpExtCmdDevice)
  device.getDeviceInfo = Mock(return_value=device_info('ILCE-7', serial='shared-transport-token'))
  camera = Mock()
  camera.getCameraInfo.return_value = SimpleNamespace(modelName='ILCE-7', modelCode='fixture', serial='vendor-body-two', plist=b'')
  camera.getLensInfo.return_value = SimpleNamespace(model=0)
  camera.getGpsData.side_effect = usb.InvalidCommandException()
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(Mock())), \
       patch.object(usb, 'getDevice', return_value=device), \
       patch.object(usb, 'SonyExtCmdCamera', return_value=camera), \
       patch('pmca.util.shutter.query_mtp_camera_shutter_count', return_value={'available': False, 'value': None, 'reason': 'No image'}):
   result = usb.getReadOnlyCameraInfo('libusb-mtp')
  self.assertEqual(result['Serial number'], 'vendor-body-two')
  self.assertNotEqual(result['Firmware version'], 'old-body-firmware')
  self.assertNotEqual(usb.get_last_verified_camera_status().get('firmware_version'), 'old-body-firmware')


 def test_installer_transition_rejects_a_different_reported_camera_model(self):
  device = object.__new__(usb.SonyMtpExtCmdDevice)
  device.getDeviceInfo = Mock(return_value=device_info('ILCE-7'))
  app_device = object.__new__(usb.SonyMtpAppInstallDevice)
  app_device.getDeviceInfo = Mock(return_value=device_info('ILCE-7RM2', install=True))
  camera = Mock()
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(Mock())), \
       patch.object(usb, 'getDevice', return_value=device), \
       patch.object(usb, 'SonyExtCmdCamera', return_value=camera), \
       patch.object(usb, 'listDevices', return_value=[app_device]), \
       patch.object(usb, 'installApp', return_value={}) as install, \
       patch.object(usb.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
   with self.assertRaises(usb.CameraOperationError) as ctx:
    usb.installCommand('libusb-mtp', apkFile=io.BytesIO(apkFixture()))
  self.assertFalse(ctx.exception.outcome_unknown)
  install.assert_not_called()


if __name__ == '__main__':
 unittest.main()
