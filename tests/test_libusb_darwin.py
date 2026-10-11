"""Unit tests for Darwin libusb backend reset and access error handling."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
import usb.core

repo_root = str(Path(__file__).resolve().parents[1])
if repo_root not in sys.path:
 sys.path.insert(0, repo_root)

from pmca.usb.driver.generic.libusb import UsbBackend


class LibusbDarwinResetTest(unittest.TestCase):
 def test_darwin_access_denied_error_is_safely_ignored(self):
  """Verify that on Darwin, backend_error_code -3 (LIBUSB_ERROR_ACCESS) is ignored without NameError."""
  mock_dev = Mock()
  mock_dev.is_kernel_driver_active.return_value = True
  err = usb.core.USBError('Access denied (insufficient permissions)')
  err.backend_error_code = -3
  mock_dev.detach_kernel_driver.side_effect = err

  backend = UsbBackend(mock_dev)
  with patch('sys.platform', 'darwin'):
   # Must NOT raise USBError and must NOT raise NameError
   try:
    backend.reset()
   except Exception as e:
    self.fail(f"reset() raised unexpected exception: {e}")

 def test_darwin_non_access_error_is_reraised(self):
  """Verify that on Darwin, other errors (like -1 LIBUSB_ERROR_IO) propagate."""
  mock_dev = Mock()
  mock_dev.is_kernel_driver_active.return_value = True
  err = usb.core.USBError('Input/Output Error')
  err.backend_error_code = -1
  mock_dev.detach_kernel_driver.side_effect = err

  backend = UsbBackend(mock_dev)
  with patch('sys.platform', 'darwin'):
   with self.assertRaises(usb.core.USBError):
    backend.reset()

 def test_non_darwin_access_error_is_reraised(self):
  """Verify that on non-Darwin platforms (e.g. linux), error -3 propagates."""
  mock_dev = Mock()
  mock_dev.is_kernel_driver_active.return_value = True
  err = usb.core.USBError('Access denied')
  err.backend_error_code = -3
  mock_dev.detach_kernel_driver.side_effect = err

  backend = UsbBackend(mock_dev)
  with patch('sys.platform', 'linux'):
   with self.assertRaises(usb.core.USBError):
    backend.reset()


if __name__ == '__main__':
 unittest.main()
