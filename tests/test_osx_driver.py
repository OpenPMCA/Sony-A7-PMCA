import ctypes
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, call, patch


class MacDriverAvailabilityTest(unittest.TestCase):
 def setUp(self):
  self.iokit = Mock()
  self.cf = Mock()
  path = Path(__file__).resolve().parents[1] / 'pmca/usb/driver/osx.py'
  spec = importlib.util.spec_from_file_location('pmca.usb.driver._test_osx', path)
  self.driver = importlib.util.module_from_spec(spec)
  with patch('ctypes.cdll.LoadLibrary', side_effect=[self.iokit, self.cf]), \
       patch('ctypes.util.find_library', side_effect=lambda name: name), \
       patch('ctypes.c_void_p.in_dll', return_value=ctypes.c_void_p()):
   spec.loader.exec_module(self.driver)

 def test_unavailable_kext_query_does_not_use_null_cf_dictionary(self):
  for result in (None, 0):
   with self.subTest(result=result):
    self.iokit.KextManagerCopyLoadedKextInfo.return_value = result
    self.cf.CFDictionaryContainsKey.reset_mock()
    self.cf.CFRelease.reset_mock()
    self.assertFalse(self.driver._isKextLoaded())
    self.cf.CFDictionaryContainsKey.assert_not_called()
    self.cf.CFRelease.assert_not_called()

 def test_installed_but_unloaded_kext_is_not_available(self):
  with patch.object(self.driver, '_isKextLoaded', return_value=False), \
       patch('os.path.exists', return_value=True):
   self.assertFalse(self.driver.isMscDriverAvailable())

 def test_loaded_sony_kext_is_available(self):
  with patch.object(self.driver, '_isKextLoaded', return_value=True):
   self.assertTrue(self.driver.isMscDriverAvailable())

 def test_loaded_dictionary_keys_and_dictionary_are_released(self):
  for loaded_keys in (set(), {b'com.sony.driver.dsccamFirmwareUpdaterType00'},
                      {b'com.sony.driver.dsccamDeviceInfo00'}):
   with self.subTest(loaded_keys=loaded_keys):
    self.cf.reset_mock()
    self.iokit.KextManagerCopyLoadedKextInfo.return_value = 100
    self.cf.CFStringCreateWithCString.side_effect = lambda allocator, name, encoding: name
    self.cf.CFDictionaryContainsKey.side_effect = lambda infos, key: key in loaded_keys
    self.assertEqual(self.driver._isKextLoaded(), bool(loaded_keys))
    self.assertEqual(self.cf.CFRelease.call_args_list, [
     call(b'com.sony.driver.dsccamFirmwareUpdaterType00'),
     call(b'com.sony.driver.dsccamDeviceInfo00'),
     call(100),
    ])


if __name__ == '__main__':
 unittest.main()
