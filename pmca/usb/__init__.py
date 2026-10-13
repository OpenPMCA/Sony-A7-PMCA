import abc
from collections import namedtuple

from .driver import *
from ..util import *

MscDeviceInfo = namedtuple('MscDeviceInfo', 'manufacturer, model')
PtpObjectInfo = namedtuple('PtpObjectInfo', 'storageId, format, size, filename, captureDate, modificationDate')

class MtpDeviceInfo(namedtuple('MtpDeviceInfoBase', 'manufacturer, model, serialNumber, operationsSupported, vendorExtension, version, devicePropertiesSupported, eventsSupported, captureFormats, imageFormats', defaults=('', frozenset(), frozenset(), frozenset(), frozenset()))):
 pass

class MscException(Exception):
 pass

class UnknownMscException(MscException):
 pass

class MtpException(Exception):
 pass

class InvalidCommandException(Exception):
 pass


class UsbDevice(object):
 def __init__(self, driver):
  self.driver = driver
  self.reset()

 def reset(self):
  self.driver.reset()


class MscDevice(UsbDevice):
 """Manages communication with a USB mass storage device. Inspired by libreadspeaker"""
 DEFAULT_TIMEOUT = 1000

 SONY_SENSE_NOT_READY = (0x02, 0x04, 0x01)
 SONY_SENSE_NOT_FOUND = (0x05, 0x24, 0x00)

 def _checkResponse(self, response):
  if response != MSC_SENSE_OK:
   if response == self.SONY_SENSE_NOT_FOUND:
    raise InvalidCommandException()
   else:
    raise UnknownMscException('SCSI sense %x %x %x' % response)

 def _sendInquiryCommand(self, length):
  response, data = self.driver.sendReadCommand(b'\x12' + 3*b'\0' + dump8(length) + b'\0', length)
  self._checkResponse(response)
  return data

 def getDeviceInfo(self):
  """SCSI Inquiry command"""
  initial = self._sendInquiryCommand(5)
  if len(initial) < 5:
   raise MscException('Truncated SCSI Inquiry response (got %d bytes, expected at least 5)' % len(initial))
  l = 5 + parse8(initial[4:5])
  data = self._sendInquiryCommand(l)
  if len(data) < 32:
   raise MscException('Truncated SCSI Inquiry response (got %d bytes, expected at least 32)' % len(data))

  vendor = data[8:16].decode('latin1').rstrip(' \0')
  product = data[16:32].decode('latin1').rstrip(' \0')
  return MscDeviceInfo(vendor, product)


class MtpDevice(UsbDevice):
 """Manages communication with a PTP/MTP device. Inspired by libptp2"""
 PTP_OC_GetDeviceInfo = 0x1001
 PTP_OC_OpenSession = 0x1002
 PTP_OC_CloseSession = 0x1003
 PTP_RC_OK = 0x2001
 PTP_RC_SessionNotOpen = 0x2003
 PTP_RC_ParameterNotSupported = 0x2006
 PTP_RC_DeviceBusy = 0x2019
 PTP_RC_SessionAlreadyOpened = 0x201E
 PTP_OC_GetStorageIDs = 0x1004
 PTP_OC_GetStorageInfo = 0x1005
 PTP_OC_GetObjectHandles = 0x1007
 PTP_OC_GetObjectInfo = 0x1008
 PTP_OC_GetPartialObject = 0x101b

 def __init__(self, driver):
  super(MtpDevice, self).__init__(driver)
  self.openSession()

 def _checkResponse(self, code, acceptedCodes=[]):
  if code not in [self.PTP_RC_OK] + acceptedCodes:
   msg = 'MTP error 0x%x' % code
   if code == self.PTP_RC_ParameterNotSupported:
    raise InvalidCommandException(msg)
   else:
    raise MtpException(msg)

 def _parseString(self, data, offset):
  length = parse8(data[offset:offset+1])
  offset += 1
  end = offset + 2*length
  return end, data[offset:end].decode('utf16')[:-1]

 def _parseIntArray(self, data, offset):
  length = parse32le(data[offset:offset+4])
  offset += 4
  end = offset + 2*length
  return end, [parse16le(data[o:o+2]) for o in range(offset, end, 2)]

 def _parseDeviceInfo(self, data):
  offset = 8
  offset, vendorExtension = self._parseString(data, offset)
  offset += 2

  offset, operationsSupported = self._parseIntArray(data, offset)
  offset, eventsSupported = self._parseIntArray(data, offset)
  offset, devicePropertiesSupported = self._parseIntArray(data, offset)
  offset, captureFormats = self._parseIntArray(data, offset)
  offset, imageFormats = self._parseIntArray(data, offset)

  offset, manufacturer = self._parseString(data, offset)
  offset, model = self._parseString(data, offset)
  offset, version = self._parseString(data, offset)
  offset, serial = self._parseString(data, offset)

  return MtpDeviceInfo(
   manufacturer,
   model,
   serial,
   set(operationsSupported),
   vendorExtension,
   version,
   set(devicePropertiesSupported),
   set(eventsSupported),
   set(captureFormats),
   set(imageFormats),
  )

 def openSession(self, id=1):
  """Opens a new MTP session"""
  response = self.driver.sendCommand(self.PTP_OC_OpenSession, [id])
  self._checkResponse(response, [self.PTP_RC_SessionAlreadyOpened])

 def closeSession(self):
  """Closes the current session"""
  response = self.driver.sendCommand(self.PTP_OC_CloseSession, [])
  self._checkResponse(response, [self.PTP_RC_SessionNotOpen])

 def getDeviceInfo(self):
  """Gets and parses device information"""
  response, data = self.driver.sendReadCommand(self.PTP_OC_GetDeviceInfo, [])
  self._checkResponse(response)
  return self._parseDeviceInfo(data)

 def _parseObjectInfo(self, data):
  if len(data) < 52:
   raise MtpException('Malformed ObjectInfo response: dataset shorter than 52 bytes (got %d)' % len(data))
  storageId = parse32le(data[:4])
  fmt = parse16le(data[4:6])
  size = parse32le(data[8:12])
  offset = 52
  try:
   offset, filename = self._parseString(data, offset)
   offset, captureDate = self._parseString(data, offset)
   offset, modDate = self._parseString(data, offset)
  except Exception as e:
   raise MtpException('Malformed ObjectInfo string table: %s' % e)
  return PtpObjectInfo(storageId, fmt, size, filename, captureDate, modDate)

 def getObjectInfo(self, handle):
  """Gets and parses PTP ObjectInfo dataset (PTP 0x1008)"""
  response, data = self.driver.sendReadCommand(self.PTP_OC_GetObjectInfo, [handle])
  self._checkResponse(response)
  return self._parseObjectInfo(data)

 def getObjectHandles(self, storageId=0xffffffff, formatCode=0x0000, parentHandle=0x00000000):
  """Gets object handles on camera storage (PTP 0x1007)"""
  response, data = self.driver.sendReadCommand(self.PTP_OC_GetObjectHandles, [storageId, formatCode, parentHandle])
  self._checkResponse(response)
  if len(data) < 4:
   raise MtpException('Truncated GetObjectHandles response: packet shorter than 4 bytes (got %d)' % len(data))
  length = parse32le(data[:4])
  expected_size = 4 + length * 4
  if len(data) != expected_size:
   raise MtpException('Malformed GetObjectHandles response: declared %d handles (%d bytes), received %d bytes' % (length, expected_size, len(data)))
  return [parse32le(data[4+i*4:8+i*4]) for i in range(length)]

 def getPartialObject(self, handle, offset=0, maxBytes=65536):
  """Reads a partial slice of an object over PTP without full bulk transfer (PTP 0x101b)"""
  response, data = self.driver.sendReadCommand(self.PTP_OC_GetPartialObject, [handle, offset, maxBytes])
  self._checkResponse(response)
  return data
