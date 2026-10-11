import contextlib
import io
import unittest
from unittest.mock import patch

from pmca.commands import usb


class MacMtpSelectionTest(unittest.TestCase):
 def test_mtp_only_driver_never_includes_mass_storage_or_service_context(self):
  with patch('sys.platform', 'darwin'), contextlib.redirect_stdout(io.StringIO()):
   try:
    result = usb.importDriver('libusb-mtp')
   except Exception as error:
    result = error
  self.assertIsInstance(result, usb.UsbDriverList)
  self.assertEqual([context.name for context in result._contexts], ['libusb-MTP'])
  self.assertEqual([context.classType for context in result._contexts], [6])



class PlatformDriverDefaultsTest(unittest.TestCase):
 def test_platform_driver_defaults(self):
  """Verify getDefaultDriverName returns platform-appropriate driver defaults."""
  with patch('sys.platform', 'win32'):
   self.assertIsNone(usb.getDefaultDriverName())

  with patch('sys.platform', 'darwin'):
   self.assertEqual(usb.getDefaultDriverName(), 'libusb-mtp')

  with patch('sys.platform', 'linux'):
   self.assertEqual(usb.getDefaultDriverName(), 'libusb')


if __name__ == '__main__':
 unittest.main()
