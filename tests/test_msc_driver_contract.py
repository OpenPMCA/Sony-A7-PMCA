"""Tests for strict BaseMscDriver contract and MscDevice sense handling."""
from pathlib import Path
import sys
import unittest

repo_root = str(Path(__file__).resolve().parents[1])
if repo_root not in sys.path:
 sys.path.insert(0, repo_root)

from pmca.usb import (
 MscDevice,
 MscDeviceInfo,
 MscException,
 UnknownMscException,
 InvalidCommandException,
)
from pmca.usb.driver import BaseMscDriver, MSC_SENSE_OK
from pmca.usb.sony import SonyMscExtCmdDevice, _BaseSonyMscExtCmdDevice


class StrictMscDriver(BaseMscDriver):
 """Strict mock driver implementing the exact 2-argument sendReadCommand contract."""
 def __init__(self):
  self.inquiry_data = b'\x00\x80\x02\x02\x1f\x00\x00\x00Sony    DSC-HX60        '
  self.inquiry_sense = MSC_SENSE_OK
  self.write_sense = MSC_SENSE_OK
  self.read_sense = MSC_SENSE_OK
  self.read_payload = b''
  self.reset_called = False
  self.write_calls = []
  self.read_calls = []

 def reset(self):
  self.reset_called = True

 def sendCommand(self, command):
  return MSC_SENSE_OK

 def sendWriteCommand(self, command, data):
  self.write_calls.append((command, data))
  if callable(self.write_sense):
   return self.write_sense()
  return self.write_sense

 def sendReadCommand(self, command, size):
  """Strictly accept only 2 arguments as defined in BaseMscDriver, and validate exact 6-byte Inquiry CDB."""
  self.read_calls.append((command, size))
  if command and command[0] == 0x12:
   if len(command) != 6:
    raise ValueError('SCSI INQUIRY CDB must be exactly 6 bytes, got %d (%s)' % (len(command), command.hex()))
   if command[1:4] != b'\0\0\0':
    raise ValueError('Bytes 1..3 of INQUIRY CDB must be 0x000000, got %s' % command[1:4].hex())
   if command[4] != size:
    raise ValueError('Allocation length at byte 4 (%d) must match requested size (%d)' % (command[4], size))
   if command[5] != 0:
    raise ValueError('Control byte at byte 5 must be 0x00, got %d' % command[5])
   if callable(self.inquiry_sense):
    sense = self.inquiry_sense()
   else:
    sense = self.inquiry_sense
   return sense, self.inquiry_data[:size]
  if callable(self.read_sense):
   sense = self.read_sense()
  else:
   sense = self.read_sense
  return sense, self.read_payload


class MscDriverContractTest(unittest.TestCase):
 def test_msc_device_inquiry_with_strict_two_arg_driver_and_tuple_sense(self):
  driver = StrictMscDriver()
  device = MscDevice(driver)
  info = device.getDeviceInfo()
  self.assertEqual(info.manufacturer, 'Sony')
  self.assertEqual(info.model, 'DSC-HX60')
  self.assertTrue(driver.reset_called)
  # Verify exact 6-byte SCSI INQUIRY CDBs (allocation length at byte 4, control byte 0 at byte 5)
  self.assertEqual(driver.read_calls, [
   (b'\x12\x00\x00\x00\x05\x00', 5),
   (b'\x12\x00\x00\x00\x24\x00', 36),
  ])

 def test_msc_device_inquiry_rejects_truncated_replies(self):
  driver = StrictMscDriver()
  driver.inquiry_data = b'\x00\x80\x02' # Shorter than 5 bytes
  device = MscDevice(driver)
  with self.assertRaises(MscException) as ctx:
   device.getDeviceInfo()
  self.assertIn('Truncated', str(ctx.exception))

  driver.inquiry_data = b'\x00\x80\x02\x02\x1f\x00Sony' # Shorter than 32 bytes
  with self.assertRaises(MscException) as ctx:
   device.getDeviceInfo()
  self.assertIn('Truncated', str(ctx.exception))

 def test_msc_device_maps_sony_not_found_sense_to_invalid_command_exception(self):
  driver = StrictMscDriver()
  driver.inquiry_sense = MscDevice.SONY_SENSE_NOT_FOUND
  device = MscDevice(driver)
  with self.assertRaises(InvalidCommandException):
   device.getDeviceInfo()

 def test_msc_device_maps_other_sense_failure_to_unknown_msc_exception(self):
  driver = StrictMscDriver()
  driver.inquiry_sense = (0x02, 0x04, 0x01) # Not ready
  device = MscDevice(driver)
  with self.assertRaises(UnknownMscException) as ctx:
   device.getDeviceInfo()
  self.assertIn('SCSI sense 2 4 1', str(ctx.exception))

 def test_sony_msc_ext_cmd_device_succeeds_with_tuple_sense(self):
  driver = StrictMscDriver()
  driver.read_payload = b'\x00' * 16 + b'payload_data'
  device = SonyMscExtCmdDevice(driver)
  # SCSI opcode 0x7a
  res = device.sendSonyExtCommand(1, b'test_write', 28)
  self.assertEqual(res, b'\x00' * 16 + b'payload_data')
  self.assertEqual(len(driver.write_calls), 1)
  self.assertEqual(driver.write_calls[0][0][0], 0x7a)

 def test_sony_msc_ext_cmd_device_paces_busy_retries_and_bounds_loop(self):
  from unittest.mock import patch
  driver = StrictMscDriver()

  # Simulate camera busy for 2.5 seconds (125 retries at 20ms) then succeeding
  clock = [100.0]
  def fake_monotonic():
   return clock[0]
  def fake_sleep(sec):
   clock[0] += sec

  def busy_until_2_5s():
   if clock[0] - 100.0 < 2.5:
    return _BaseSonyMscExtCmdDevice.MSC_SENSE_DeviceBusy
   return MSC_SENSE_OK

  driver.write_sense = busy_until_2_5s
  device = SonyMscExtCmdDevice(driver)
  with patch('time.monotonic', side_effect=fake_monotonic), \
       patch('time.sleep', side_effect=fake_sleep):
   res = device.sendSonyExtCommand(1, b'data', 0)
  self.assertEqual(res, b'')
  self.assertAlmostEqual(clock[0] - 100.0, 2.5, places=1)
  self.assertGreater(len(driver.write_calls), 100)

 def test_sony_msc_ext_cmd_device_exceeding_max_busy_raises_error(self):
  from unittest.mock import patch
  driver = StrictMscDriver()
  driver.write_sense = _BaseSonyMscExtCmdDevice.MSC_SENSE_DeviceBusy
  device = SonyMscExtCmdDevice(driver)

  clock = [100.0]
  def fake_monotonic():
   return clock[0]
  def fake_sleep(sec):
   clock[0] += 5.0 # advance in 5s chunks to exceed 30s deadline quickly

  with patch('time.monotonic', side_effect=fake_monotonic), \
       patch('time.sleep', side_effect=fake_sleep):
   with self.assertRaises(UnknownMscException) as ctx:
    device.sendSonyExtCommand(1, b'data', 0)
  self.assertIn('busy', str(ctx.exception).lower())
  self.assertGreaterEqual(clock[0] - 100.0, 30.0)


if __name__ == '__main__':
 unittest.main()
