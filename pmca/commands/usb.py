import contextlib
import io
import json
import os
import plistlib
import subprocess
import sys
import threading
import time
import struct
import zipfile

import config
from ..apk import *
from .. import appstore
from .. import firmware
from .. import installer
from ..io import *
from ..marketserver.server import *
from ..platform import *
from ..platform.backend.senser import *
from ..platform.backend.usb import *
from ..usb import *
from ..usb.driver import *
from ..usb.driver.generic import *
from ..usb.sony import *
from ..util import http
from ..compatibility import get_camera_support, normalize_camera_model

scriptRoot = getattr(sys, '_MEIPASS', os.path.dirname(__file__) + '/../..')


class CameraBusyException(Exception):
 """Raised when an exclusive camera operation is already in progress."""
 pass


_camera_lock = threading.RLock()
_camera_busy = False
_camera_busy_lock = threading.Lock()
_last_verified_camera_status = None
_status_cache_lock = threading.Lock()


def get_last_verified_camera_status():
 with _status_cache_lock:
  return dict(_last_verified_camera_status) if _last_verified_camera_status else None


def set_last_verified_camera_status(status):
 global _last_verified_camera_status
 with _status_cache_lock:
  _last_verified_camera_status = dict(status) if status else None



def _matching_camera_status(model, raw_serial=None, vendor_serial=None):
 """Reuse body metadata only when the current camera identity is verified."""
 last = get_last_verified_camera_status()
 if not last or normalize_camera_model(last.get('model') or last.get('name')) != normalize_camera_model(model):
  return None
 def valid_identity(value):
  return isinstance(value, str) and bool(value.strip()) and set(value.strip()) != {'0'} and value.strip().lower() not in ('unknown', 'none', 'n/a')
 if valid_identity(vendor_serial) and valid_identity(last.get('serial')) and vendor_serial != last['serial']:
  return None
 same_transport = bool(valid_identity(raw_serial) and raw_serial == last.get('raw_serial'))
 same_body = bool(valid_identity(vendor_serial) and vendor_serial == last.get('serial'))
 return last if same_transport or same_body else None


def _app_installation_support(model, sony_transport=False, installer_protocol=False):
 profile = get_camera_support(model)
 if installer_protocol:
  return profile, True, 'Sony app-installer protocol confirmed.'
 if profile['pmca_apps'] is False:
  return profile, False, 'This model is not listed as PMCA app-capable in the upstream device reference.'
 if profile['pmca_apps'] is None:
  return profile, False, 'PMCA app support is unconfirmed for this model; no installer protocol is active.'
 if not sony_transport:
  return profile, False, 'The camera model is PMCA-capable, but the required Sony transport commands are unavailable.'
 return profile, True, 'PMCA-capable model and required Sony transport commands detected; APK compatibility is app-specific.'


def is_camera_busy():
 with _camera_busy_lock:
  return _camera_busy


def set_camera_busy(busy):
 global _camera_busy
 with _camera_busy_lock:
  _camera_busy = bool(busy)


@contextlib.contextmanager
def camera_operation(blocking=True, timeout=None):
 """Serialized camera operation context shared by info, install, probe."""
 acquired = _camera_lock.acquire(blocking=blocking, timeout=-1 if timeout is None else timeout)
 if not acquired:
  raise CameraBusyException("Camera is busy with another operation")
 try:
  yield
 finally:
  _camera_lock.release()


def printStatus(status):
 """Print progress"""
 print('%s %d%%' % (status.message, status.percent))


appListCache = None
def listApps(enableCache=False):
 global appListCache
 appStoreRepo = appstore.GithubApi(config.githubAppListUser, config.githubAppListRepo)

 if not appListCache or not enableCache:
  print('Loading app list')
  apps = appstore.AppStore(appStoreRepo).apps
  print('Found %d apps' % len(apps))
  appListCache = apps
 return appListCache


def checkApk(apkFile):
 """Analyzes and validates an APK file before transfer.
 Strictly enforces non-empty package identifier, version, minSdkVersion (1..10), and signature certificate.
 Returns the validated ApkParser instance or raises ValueError on validation error.
 """
 try:
  apk = ApkParser(apkFile)
 except Exception as e:
  raise ValueError('Invalid APK file: %s' % e)

 package = apk.getPackageName()
 if not package or not package.strip():
  raise ValueError('The APK manifest has no package identifier.')

 version = apk.getVersionName()
 if not version or not str(version).strip():
  raise ValueError('The APK manifest has no version identifier.')

 props = [
  ('Package', package),
  ('Version', str(version)),
 ]
 try:
  apk.getVersionCode()
 except Exception:
  pass

 for k, v in props:
  print('%-9s%s' % (k + ': ', v))

 sdk = apk.getMinSdkVersion()
 if not (1 <= sdk <= 10):
  raise ValueError('Incompatible Android minSdkVersion: %s (camera requires API 1-10)' % sdk)

 try:
  cert = apk.getCert()
  if not cert:
   raise ValueError('APK signature certificate is empty')
 except Exception as e:
  raise ValueError('APK signature certificate missing or invalid: %s' % e)

 return apk


def installApp(dev, apkFile=None, appPackage=None, outFile=None, statusFunc=None):
 """Installs an app on the specified device."""
 with camera_operation(blocking=True):
  set_camera_busy(True)
  try:
   certFile = scriptRoot + '/certs/localtest.me.pem'
   with ServerContext(LocalMarketServer(certFile)) as server:
    apkData = None
    if apkFile:
     apkData = apkFile.read() if hasattr(apkFile, 'read') else apkFile
    elif appPackage:
     print('Downloading apk')
     apps = listApps(True)
     if appPackage not in apps:
      raise Exception('Unknown app: %s' % appPackage)
     apkData = apps[appPackage].release.asset

    if apkData:
     print('Analyzing apk')
     print('')
     checkApk(io.BytesIO(apkData))
     print('')
     server.setApk(apkData)

    print('Starting task')
    xpdData = server.getXpd()

    print('Starting communication')
    # Point the camera to the web api
    result = installer.install(SonyAppInstallCamera(dev), *server.server_address, xpdData, statusFunc or printStatus)
    if result.code != 0:
     raise Exception('Communication error %d: %s' % (result.code, result.message))
    try:
     serverResult = server.getResult()
    except Exception:
     serverResult = None
    if outFile and serverResult:
     print('Saving camera response')
     json.dump(serverResult, outFile, indent=2)
    return serverResult if serverResult is not None else result
  finally:
   set_camera_busy(False)


def getPassiveUsbDevice():
 """Passive read-only query of macOS I/O registry for attached Sony camera without driver detachment."""
 if sys.platform != 'darwin':
  return None
 try:
  proc_dev = subprocess.run(['ioreg', '-r', '-c', 'IOUSBHostDevice', '-l', '-a'], capture_output=True, timeout=2)
  if proc_dev.returncode != 0:
   return None
  dev_data = plistlib.loads(proc_dev.stdout)

  sony_devices = []
  def find_devs(node):
   if isinstance(node, dict):
    if node.get('idVendor') == SONY_ID_VENDOR:
     sony_devices.append(node)
    for v in node.values():
     find_devs(v)
   elif isinstance(node, list):
    for item in node:
     find_devs(item)
  find_devs(dev_data)
  if not sony_devices:
   return None

  proc_if = subprocess.run(['ioreg', '-r', '-c', 'IOUSBHostInterface', '-l', '-a'], capture_output=True, timeout=2)
  ifaces = []
  if proc_if.returncode == 0:
   if_data = plistlib.loads(proc_if.stdout)
   def find_ifs(node):
    if isinstance(node, dict):
     if 'bInterfaceClass' in node:
      ifaces.append(node)
     for v in node.values():
      find_ifs(v)
    elif isinstance(node, list):
     for item in node:
      find_ifs(item)
   find_ifs(if_data)

  dev = sony_devices[0]
  name = dev.get('USB Product Name') or dev.get('kUSBProductString') or 'Sony Camera'
  serial = dev.get('USB Serial Number') or dev.get('kUSBSerialNumberString')
  pid = dev.get('idProduct')

  mode = 'USB detected; mode not confirmed'
  for iface in ifaces:
   iface_name = iface.get('USB Product Name') or iface.get('kUSBProductString')
   if iface_name == name or len(sony_devices) == 1:
    cls = iface.get('bInterfaceClass')
    subcls = iface.get('bInterfaceSubClass')
    proto = iface.get('bInterfaceProtocol')
    if cls == 6 and subcls == 1 and proto == 1:
     mode = 'MTP / PTP (Class 6/1/1)'
     break
    elif cls == 8:
     mode = 'Mass Storage (Class 8)'
     break
    elif cls == 255:
     mode = 'Vendor Specific (Class 255)'
     break

  return {
   'name': name,
   'serial': serial,
   'mode': mode,
   'vendor': 'Sony (0x054c)',
   'pid': pid,
  }
 except Exception:
  return None


def getCameraStatus(driverName=None, probe_communication=True, quiet=False):
 """Non-intrusive read-only query of camera connection status, capabilities, and failure classification."""
 if driverName is None:
  driverName = getDefaultDriverName()
 if is_camera_busy():
  last = get_last_verified_camera_status()
  if last:
   busy_status = dict(last)
   busy_status['busy'] = True
   busy_status['status'] = 'busy'
   busy_status['mode'] = 'Busy'
   busy_status['source_mode'] = last.get('source_mode') or last.get('mode') or 'Unknown'
   busy_status['failure_reason'] = 'Camera operation in progress'
   return busy_status

  passive = getPassiveUsbDevice()
  physical_detected = bool(passive)
  return {
   'connected': False,
   'physicalDetected': physical_detected,
   'appConnected': False,
   'busy': True,
   'status': 'busy',
   'mode': 'Busy',
   'name': passive.get('name') if passive else 'Camera Busy',
   'model': passive.get('name') if passive else 'Camera Busy',
   'manufacturer': 'Sony',
   'vendor': 'Sony (0x054c)' if physical_detected else None,
   'serial': None,
   'raw_serial': passive.get('serial') if passive else None,
   'firmware_version': None,
   'capabilities': [],
   'properties': [],
   'events': [],
   'formats': [],
   'shutter_count': {'available': False, 'value': None, 'reason': 'Camera is busy with an active operation.'},
   'failure_reason': 'Camera operation in progress',
  }

 passive = getPassiveUsbDevice()
 physical_detected = bool(passive)

 if not probe_communication:
  set_last_verified_camera_status(None)
  if passive:
   return {
    'connected': False,
    'physicalDetected': True,
    'appConnected': False,
    'busy': False,
    'status': 'unverified',
    'mode': passive.get('mode', 'Unknown'),
    'name': passive.get('name', 'Sony Camera'),
    'model': passive.get('name', 'Sony Camera'),
    'manufacturer': 'Sony',
    'vendor': passive.get('vendor', 'Sony (0x054c)'),
    'serial': None,
    'raw_serial': passive.get('serial'),
    'firmware_version': None,
    'capabilities': [],
    'properties': [],
    'events': [],
    'formats': [],
    'shutter_count': {'available': False, 'value': None, 'reason': 'Communication probe skipped.'},
    'failure_reason': None,
   }
  return {
   'connected': False,
   'physicalDetected': False,
   'appConnected': False,
   'busy': False,
   'status': 'disconnected',
   'mode': 'Disconnected',
   'name': None,
   'model': None,
   'manufacturer': 'Sony',
   'vendor': None,
   'serial': None,
   'firmware_version': None,
   'capabilities': [],
   'properties': [],
   'events': [],
   'formats': [],
   'shutter_count': {'available': False, 'value': None, 'reason': 'No camera detected.'},
   'failure_reason': 'No camera detected on USB',
  }

 try:
  with camera_operation(blocking=False):
   with importDriver(driverName, quiet=quiet) as driver:
    devices = list(driver.listDevices(SONY_ID_VENDOR))
    if not devices:
     set_last_verified_camera_status(None)
     if passive:
      return {
       'connected': False,
       'physicalDetected': True,
       'appConnected': False,
       'busy': False,
       'status': 'access_denied',
       'mode': passive.get('mode', 'Access Denied'),
       'name': passive.get('name', 'Sony Camera'),
       'model': passive.get('name', 'Sony Camera'),
       'manufacturer': 'Sony',
       'vendor': 'Sony (0x054c)',
       'serial': None,
       'raw_serial': passive.get('serial'),
       'firmware_version': None,
       'capabilities': [],
       'properties': [],
       'events': [],
       'formats': [],
       'shutter_count': {'available': False, 'value': None, 'reason': 'Cannot access camera: interface unavailable.'},
       'failure_reason': 'USB interface cannot be opened (managed by macOS ptpcamerad or permission needed)',
      }
     return {
      'connected': False,
      'physicalDetected': False,
      'appConnected': False,
      'app_installation_supported': False,
      'busy': False,
      'status': 'disconnected',
      'mode': 'Disconnected',
      'name': None,
      'model': None,
      'manufacturer': 'Sony',
      'vendor': None,
      'serial': None,
      'firmware_version': None,
      'capabilities': [],
      'properties': [],
      'events': [],
      'formats': [],
      'shutter_count': {'available': False, 'value': None, 'reason': 'No camera connected.'},
      'failure_reason': 'No camera detected on USB',
     }

    if len(devices) > 1:
     set_last_verified_camera_status(None)
     return {
      'connected': False, 'physicalDetected': True, 'appConnected': False,
      'busy': False, 'status': 'multiple_devices', 'mode': 'Multiple cameras',
      'name': None, 'model': None, 'manufacturer': 'Sony', 'vendor': 'Sony (0x054c)',
      'serial': None, 'raw_serial': None, 'firmware_version': None,
      'capabilities': [], 'properties': [], 'events': [], 'formats': [],
      'app_installation_supported': False,
      'app_installation_reason': 'Connect only one camera at a time to select the intended device safely.',
      'shutter_count': {'available': False, 'value': None, 'reason': 'More than one Sony device is attached.'},
      'failure_reason': 'Connect only one camera at a time.',
     }

    dev, dev_type, drv = devices[0]
    if dev_type == USB_CLASS_PTP:
     mtp = MtpDevice(drv)
     try:
      info = mtp.getDeviceInfo()
     finally:
      try:
       mtp.closeSession()
      except Exception:
       pass

     mode = 'App installation' if isSonyMtpAppInstallCamera(info) else 'MTP' if isSonyMtpCamera(info) else 'PTP'
     ptp_ver = getattr(info, 'version', None)
     last = _matching_camera_status(info.model, raw_serial=info.serialNumber)
     prior_fw = last.get('firmware_version') if last else None
     if prior_fw and not prior_fw.startswith('Unavailable') and prior_fw != ptp_ver:
      fw_ver = prior_fw
     else:
      fw_ver = 'Unavailable without firmware query'

     # Only a vendor-verified body serial belongs in this field.
     body_serial = last.get('serial') if last else None
     shutter_data = last.get('shutter_count') if last else None
     if not shutter_data:
      if isSonyMtpAppInstallCamera(info):
       shutter_data = {
        'available': False,
        'value': None,
        'reason': 'Camera is in App installation mode. Switch back to normal MTP mode to read shutter count.',
       }
      else:
       shutter_data = {
        'available': False,
        'value': None,
        'reason': 'Query camera info to inspect shutter count.',
       }

     profile, can_install, install_reason = _app_installation_support(
      info.model, sony_transport=isSonyMtpCamera(info),
      installer_protocol=isSonyMtpAppInstallCamera(info))
     res = {
      'camera_support': profile,
      'app_installation_supported': can_install,
      'app_installation_reason': install_reason,
      'connected': True,
      'physicalDetected': True,
      'appConnected': True,
      'busy': False,
      'status': 'ready',
      'mode': mode,
      'source_mode': mode,
      'name': info.model,
      'model': info.model,
      'manufacturer': info.manufacturer,
      'vendor': 'Sony (0x054c)',
      'serial': body_serial,
      'raw_serial': info.serialNumber,
      'ptp_device_version': ptp_ver,
      'firmware_version': fw_ver,
      'capabilities': list(info.operationsSupported) if hasattr(info, 'operationsSupported') else [],
      'properties': list(getattr(info, 'devicePropertiesSupported', [])) if hasattr(info, 'devicePropertiesSupported') else [],
      'events': list(getattr(info, 'eventsSupported', [])) if hasattr(info, 'eventsSupported') else [],
      'formats': list(getattr(info, 'captureFormats', [])) if hasattr(info, 'captureFormats') else [],
      'shutter_count': shutter_data,
      'failure_reason': None,
     }
     set_last_verified_camera_status(res)
     return res

    elif dev_type == USB_CLASS_MSC:
     set_last_verified_camera_status(None)
     msc = MscDevice(drv)
     info = msc.getDeviceInfo()
     return {
      'connected': True,
      'physicalDetected': True,
      'appConnected': True,
      'busy': False,
      'status': 'ready',
      'mode': 'Mass Storage',
      'source_mode': 'Mass Storage',
      'name': info.model,
      'model': info.model,
      'manufacturer': info.manufacturer,
      'vendor': 'Sony (0x054c)',
      'serial': None,
      'raw_serial': passive.get('serial') if passive else None,
      'firmware_version': None,
      'capabilities': [],
      'properties': [],
      'events': [],
      'formats': [],
      'shutter_count': {
       'available': False,
       'value': None,
       'reason': 'Mass storage mode does not expose shutter actuation counter.',
      },
      'failure_reason': None,
     }

    else:
     set_last_verified_camera_status(None)
     return {
      'connected': False,
      'physicalDetected': True,
      'appConnected': False,
      'busy': False,
      'status': 'unsupported',
      'mode': 'Unknown (%d)' % dev_type,
      'name': passive.get('name') if passive else 'Sony Device',
      'model': passive.get('name') if passive else 'Sony Device',
      'manufacturer': 'Sony',
      'vendor': 'Sony (0x054c)',
      'serial': None,
      'raw_serial': passive.get('serial') if passive else None,
      'firmware_version': None,
      'capabilities': [],
      'properties': [],
      'events': [],
      'formats': [],
      'shutter_count': {'available': False, 'value': None, 'reason': 'Unsupported USB mode.'},
      'failure_reason': 'Unsupported USB device class %d' % dev_type,
     }

 except CameraBusyException:
  last = get_last_verified_camera_status()
  if last:
   last.update({
    'busy': True, 'status': 'busy', 'mode': 'Busy',
    'source_mode': last.get('source_mode') or last.get('mode'),
    'failure_reason': 'Camera operation in progress',
   })
   return last
  return {
   'connected': False,
   'physicalDetected': physical_detected,
   'appConnected': False,
   'app_installation_supported': False,
   'app_installation_reason': 'Camera communication has not yet been verified.',
   'busy': True,
   'status': 'busy',
   'mode': 'Busy',
   'name': passive.get('name') if passive else None,
   'model': passive.get('name') if passive else None,
   'manufacturer': 'Sony',
   'vendor': 'Sony (0x054c)',
   'serial': None,
   'firmware_version': None,
   'capabilities': [],
   'properties': [],
   'events': [],
   'formats': [],
   'shutter_count': {'available': False, 'value': None, 'reason': 'Camera is busy with an active transfer.'},
   'failure_reason': 'Camera operation in progress',
  }
 except PermissionError as e:
  set_last_verified_camera_status(None)
  return {
   'connected': False,
   'physicalDetected': True,
   'appConnected': False,
   'busy': False,
   'status': 'access_denied',
   'mode': passive.get('mode', 'Access Denied') if passive else 'Access Denied',
   'name': passive.get('name', 'Sony Camera') if passive else 'Sony Camera',
   'model': passive.get('name', 'Sony Camera') if passive else 'Sony Camera',
   'manufacturer': 'Sony',
   'vendor': 'Sony (0x054c)',
   'serial': None,
   'raw_serial': passive.get('serial') if passive else None,
   'firmware_version': None,
   'capabilities': [],
   'properties': [],
   'events': [],
   'formats': [],
   'shutter_count': {'available': False, 'value': None, 'reason': 'Camera communication denied by OS.'},
   'failure_reason': 'Camera access denied: %s' % str(e),
  }
 except Exception as e:
  set_last_verified_camera_status(None)
  err_str = str(e).lower()
  is_access = 'access' in err_str or 'permission' in err_str or getattr(e, 'backend_error_code', None) == -3
  return {
   'connected': False,
   'physicalDetected': physical_detected,
   'appConnected': False,
   'busy': False,
   'status': 'access_denied' if is_access else ('unsupported' if physical_detected else 'disconnected'),
   'mode': passive.get('mode', 'Error') if passive else 'Disconnected',
   'name': passive.get('name') if passive else None,
   'model': passive.get('name') if passive else None,
   'manufacturer': 'Sony',
   'vendor': 'Sony (0x054c)' if physical_detected else None,
   'serial': None,
   'raw_serial': passive.get('serial') if passive else None,
   'firmware_version': None,
   'capabilities': [],
   'properties': [],
   'events': [],
   'formats': [],
   'shutter_count': {'available': False, 'value': None, 'reason': 'Cannot query camera.'},
   'failure_reason': str(e),
  }


def getDefaultDriverName():
 """Returns platform-specific default USB driver: Windows native WPD, Linux libusb, macOS libusb-mtp."""
 if sys.platform == 'win32':
  return None
 elif sys.platform == 'darwin':
  return 'libusb-mtp'
 else:
  return 'libusb'


# Alias for GUI compatibility
def checkCameraConnection(driverName=None, quiet=False):
 if driverName is None:
  driverName = getDefaultDriverName()
 return getCameraStatus(driverName=driverName, quiet=quiet)


class UsbDriverList(contextlib.AbstractContextManager):
 def __init__(self, *contexts):
  self._contexts = contexts
  self._drivers = []

 def __enter__(self):
  self._drivers = [context.__enter__() for context in self._contexts]
  return self

 def __exit__(self, *ex):
  for context in self._contexts:
   context.__exit__(*ex)
  self._drivers = []

 def listDevices(self, vendor):
  for driver in self._drivers:
   for dev in driver.listDevices(vendor):
    yield dev, driver.classType, driver.openDevice(dev)


def importDriver(driverName=None, quiet=False):
 """Returns an UsbDriverList containing all available drivers"""
 MscContext = None
 MtpContext = None
 VendorSpecificContext = None
 MscContext2 = None
 MtpContext2 = None
 VendorSpecificContext2 = None

 # Load native drivers
 if driverName == 'native' or driverName is None:
  if sys.platform == 'win32':
   from ..usb.driver.windows.msc import MscContext
   from ..usb.driver.windows.wpd import MtpContext
   from ..usb.driver.windows.driverless import VendorSpecificContext
  elif sys.platform == 'darwin':
   from ..usb.driver.osx import isMscDriverAvailable
   if isMscDriverAvailable():
    from ..usb.driver.osx import MscContext
   else:
    print('Native mass storage driver unavailable; using libusb')
  else:
   print('No native drivers available')
 elif driverName == 'qemu':
  from ..usb.driver.generic.qemu import MscContext
  from ..usb.driver.generic.qemu import MtpContext
 elif driverName not in ('libusb', 'libusb-mtp'):
  raise Exception('Unknown driver')

 # Fallback to libusb
 if driverName != 'libusb-mtp' and (MscContext is None or (driverName is None and sys.platform == 'win32')):
  from ..usb.driver.generic.libusb import MscContext as MscContext2
 if MtpContext is None or (driverName is None and sys.platform == 'win32'):
  from ..usb.driver.generic.libusb import MtpContext as MtpContext2
 if driverName != 'libusb-mtp' and ((VendorSpecificContext is None and driverName != 'qemu') or (driverName is None and sys.platform == 'win32')):
  from ..usb.driver.generic.libusb import VendorSpecificContext as VendorSpecificContext2

 drivers = [context() for context in [MscContext, MtpContext, VendorSpecificContext, MscContext2, MtpContext2, VendorSpecificContext2] if context]
 if not quiet:
  print('Using drivers %s' % ', '.join(d.name for d in drivers))
 return UsbDriverList(*drivers)


def listDevices(driverList, quiet=False):
 """List all Sony usb devices"""
 if not quiet:
  print('Looking for Sony devices')
 for dev, type, drv in driverList.listDevices(SONY_ID_VENDOR):
  if type == USB_CLASS_MSC:
   if not quiet:
    print('\nQuerying mass storage device')
   # Get device info
   info = MscDevice(drv).getDeviceInfo()

   if isSonyMscCamera(info):
    if isSonyMscUpdaterCamera(dev):
     if not quiet:
      print('%s %s is a camera in updater mode' % (info.manufacturer, info.model))
     yield SonyMscUpdaterDevice(drv)
    else:
     if not quiet:
      print('%s %s is a camera in mass storage mode' % (info.manufacturer, info.model))
     yield SonyMscExtCmdDevice(drv)

  elif type == USB_CLASS_PTP:
   if not quiet:
    print('\nQuerying MTP device')
   # Get device info
   info = MtpDevice(drv).getDeviceInfo()

   if isSonyMtpCamera(info):
    if not quiet:
     print('%s %s is a camera in MTP mode' % (info.manufacturer, info.model))
    yield SonyMtpExtCmdDevice(drv)
   elif isSonyMtpAppInstallCamera(info):
    if not quiet:
     print('%s %s is a camera in app install mode' % (info.manufacturer, info.model))
    yield SonyMtpAppInstallDevice(drv)

  elif type == USB_CLASS_VENDOR_SPECIFIC:
   if isSonySenserCamera(dev):
    print('Found a camera in service mode')
    yield SonySenserDevice(drv)

  if not quiet:
   print('')


def getDevice(driver):
 """Check for exactly one Sony usb device"""
 devices = list(listDevices(driver))
 if not devices:
  print('No devices found. Please make sure that the camera is connected.')
 elif len(devices) != 1:
  print('Error: Too many Sony devices found. Only one camera is supported.')
 else:
  return devices[0]


def infoCommand(driverName=None):
 """Display information about the camera connected via usb"""
 with camera_operation(blocking=True):
  with importDriver(driverName) as driver:
   device = getDevice(driver)
   if device:
    if isinstance(device, SonyAppInstallDevice):
     info = installApp(device)
     print('')
     props = [
      ('Model', info['deviceinfo']['name']),
      ('Product code', info['deviceinfo']['productcode']),
      ('Serial number', info['deviceinfo']['deviceid']),
      ('Firmware version', info['deviceinfo']['fwversion']),
     ]
    elif isinstance(device, SonyExtCmdDevice):
     dev = SonyExtCmdCamera(device)
     info = dev.getCameraInfo()
     mtp_info = None
     if isinstance(device, SonyMtpExtCmdDevice):
      try:
       mtp_info = device.getDeviceInfo()
      except Exception:
       pass
     last = _matching_camera_status(info.modelName, getattr(mtp_info, 'serialNumber', None), info.serial)
     if not last:
      set_last_verified_camera_status(None)
     firmwareOld = None
     try:
      # Ephemeral updater version query (CMD_QUERY_VERSION without CMD_SWITCH_MODE)
      updater = SonyUpdaterCamera(device)
      updater.init()
      firmwareOld, firmwareNew = updater.getFirmwareVersion()
      try:
       updater.complete()
      except Exception:
       pass
     except Exception:
      if last and last.get('firmware_version') and not last['firmware_version'].startswith('Unavailable'):
       firmwareOld = last['firmware_version']
      else:
       try:
        mtp_info = mtp_info or device.getDeviceInfo()
        ptp_v = getattr(mtp_info, 'version', None)
        firmwareOld = 'PTP %s (firmware query unavailable)' % ptp_v if ptp_v else 'Unknown'
       except Exception:
        firmwareOld = getattr(device, 'version', None) or 'Unknown'

     # Cache verified firmware version for non-intrusive status heartbeats
     if firmwareOld and not firmwareOld.startswith('PTP') and not firmwareOld.startswith('Unavailable') and firmwareOld != 'Unknown':
      if last:
       last['firmware_version'] = firmwareOld
       set_last_verified_camera_status(last)
     props = [
      ('Model', info.modelName),
      ('Product code', info.modelCode),
      ('Serial number', info.serial),
      ('Firmware version', firmwareOld),
     ]
     try:
      lensInfo = dev.getLensInfo()
      if lensInfo.model != 0:
       props.append(('Lens', 'Model 0x%x (Firmware %s)' % (lensInfo.model, lensInfo.version)))
     except (InvalidCommandException, UnknownMscException):
      pass
     try:
      gpsInfo = dev.getGpsData()
      props.append(('GPS Data', '%s - %s' % gpsInfo))
     except (InvalidCommandException, UnknownMscException):
      pass
    else:
     print('Error: Cannot use camera in this mode. Please switch to MTP or mass storage mode.')
     return
    mode = 'App installation' if isinstance(device, SonyAppInstallDevice) else 'MTP' if isinstance(device, SonyMtpExtCmdDevice) else 'Mass Storage'
    props.insert(1, ('USB mode', mode))
    for k, v in props:
     print('%-20s%s' % (k + ': ', v))
    return dict(props)


def getReadOnlyCameraInfo(driverName=None):
 """Safe, non-intrusive read-only query of camera model, product code, serial, firmware, and lens.
 Never calls updater.init() or triggers camera mode changes.
 """
 if driverName is None:
  driverName = getDefaultDriverName()
 with camera_operation(blocking=True):
  with importDriver(driverName) as driver:
   device = getDevice(driver)
   if not device:
    set_last_verified_camera_status(None)
    return None
   if isinstance(device, SonyMtpAppInstallDevice):
    mtp_info = device.getDeviceInfo()
    last = _matching_camera_status(mtp_info.model, raw_serial=mtp_info.serialNumber) or {}
    if not last:
     set_last_verified_camera_status(None)
    profile, can_install, reason = _app_installation_support(
     mtp_info.model, installer_protocol=isSonyMtpAppInstallCamera(mtp_info))
    return {
     'Model': mtp_info.model,
     'USB mode': 'App installation',
     'PTP version': getattr(mtp_info, 'version', None) or 'Unavailable',
     'Serial number': last.get('serial') or 'Unavailable without vendor query',
     'Firmware version': last.get('firmware_version') or 'Unavailable (read-only app installation mode)',
     'App support': 'Installer protocol confirmed' if can_install else reason,
     'Shutter count': 'Unavailable',
     'Shutter note': 'App installation mode cannot refresh image-counter metadata. Return to normal MTP to inspect an existing image.',
    }
   elif isinstance(device, SonyAppInstallDevice):
    return None
   elif isinstance(device, SonyExtCmdDevice):
    dev = SonyExtCmdCamera(device)
    info = dev.getCameraInfo()
    firmware_version = None
    ptp_version = None
    mtp_info = None
    if isinstance(device, SonyMtpExtCmdDevice):
     try:
      mtp_info = device.getDeviceInfo()
      ptp_version = getattr(mtp_info, 'version', None)
     except Exception:
      pass

    if not _matching_camera_status(info.modelName, getattr(mtp_info, 'serialNumber', None), info.serial):
     set_last_verified_camera_status(None)

    # Read verified firmware if cached, or from plist
    try:
     plist_dict = plistlib.loads(info.plist)
     firmware_version = plist_dict.get('FirmwareVersion') or plist_dict.get('version')
    except Exception:
     pass
    if not firmware_version:
     last = _matching_camera_status(info.modelName, getattr(mtp_info, 'serialNumber', None), info.serial)
     if last and last.get('firmware_version') and not last['firmware_version'].startswith('Unavailable') and last['firmware_version'] != ptp_version:
      firmware_version = last['firmware_version']
     else:
      firmware_version = 'Unavailable (read-only MTP)'

    props = {
     'Model': info.modelName,
     'Product code': info.modelCode,
     'Serial number': info.serial,
     'PTP version': ptp_version or 'N/A',
     'Firmware version': firmware_version,
     'USB mode': 'MTP' if isinstance(device, SonyMtpExtCmdDevice) else 'Mass Storage',
    }
    try:
     lensInfo = dev.getLensInfo()
     if lensInfo.model != 0:
      props['Lens'] = 'Model 0x%x (Firmware %s)' % (lensInfo.model, lensInfo.version)
    except Exception:
     pass
    try:
     gpsInfo = dev.getGpsData()
     props['GPS Data'] = '%s - %s' % gpsInfo
    except Exception:
     pass

    # Query genuine shutter count over MTP if in MTP mode
    sc_data = None
    if isinstance(device, SonyMtpExtCmdDevice):
     try:
      from ..util.shutter import query_mtp_camera_shutter_count
      sc_data = query_mtp_camera_shutter_count(device)
      if sc_data:
       if sc_data.get('available') and sc_data.get('value') is not None:
        props['Shutter count'] = '{:,} actuations'.format(sc_data['value'])
        if sc_data.get('provenance'):
         props['Shutter note'] = sc_data['provenance']
       elif sc_data.get('ambiguous') and sc_data.get('shutter_count_modulo') is not None:
        props['Shutter count'] = '{:,} actuations (modulo 65,536)'.format(sc_data['shutter_count_modulo'])
        props['Shutter note'] = sc_data.get('warning') or 'Captured with flash; 16-bit counter'
       elif sc_data.get('reason'):
        props['Shutter count'] = 'Unavailable'
        props['Shutter note'] = sc_data['reason']
     except Exception:
      pass

    # Update cache with verified identity, serial, and shutter data
    if mtp_info is not None:
     last = _matching_camera_status(info.modelName, getattr(mtp_info, 'serialNumber', None), info.serial) or {}
     profile, can_install, install_reason = _app_installation_support(
      mtp_info.model, sony_transport=isSonyMtpCamera(mtp_info))
     last.update({
      'camera_support': profile, 'app_installation_supported': can_install,
      'app_installation_reason': install_reason,
      'model': info.modelName, 'name': info.modelName,
      'raw_serial': getattr(mtp_info, 'serialNumber', None), 'serial': info.serial,
      'connected': True, 'appConnected': True, 'physicalDetected': True,
      'mode': 'MTP', 'source_mode': 'MTP', 'status': 'ready', 'busy': False,
      'ptp_device_version': ptp_version,
     })
     if firmware_version != 'Unavailable (read-only MTP)':
      last['firmware_version'] = firmware_version
     if sc_data:
      last['shutter_count'] = sc_data
     set_last_verified_camera_status(last)

    return props
   return None


def installCommand(driverName=None, apkFile=None, appPackage=None, outFile=None, statusFunc=None):
 """Install the given apk on the camera"""
 with camera_operation(blocking=True):
  set_camera_busy(True)
  try:
   # Preflight immutable APK before ANY camera mode switch or transfer side effects
   apkData = None
   if apkFile:
    apkData = apkFile.read() if hasattr(apkFile, 'read') else apkFile
   elif appPackage:
    print('Downloading apk')
    apps = listApps(True)
    if appPackage not in apps:
     raise Exception('Unknown app: %s' % appPackage)
    apkData = apps[appPackage].release.asset

   if apkData:
    print('Analyzing apk')
    print('')
    checkApk(io.BytesIO(apkData))
    print('')

   selected_model = None
   with importDriver(driverName) as driver:
    device = getDevice(driver)
    if device and isinstance(device, SonyExtCmdDevice):
     if isinstance(device, SonyMtpExtCmdDevice):
      device_info = device.getDeviceInfo()
      profile, can_install, reason = _app_installation_support(
       device_info.model, sony_transport=isSonyMtpCamera(device_info))
     else:
      model_info = SonyExtCmdCamera(device).getCameraInfo()
      profile, can_install, reason = _app_installation_support(model_info.modelName, sony_transport=True)
     if not can_install:
      print('Error: PMCA installation unavailable: %s' % reason)
      return
     selected_model = profile['model']
     print('Switching to app install mode')
     try:
      SonyExtCmdCamera(device).switchToAppInstaller()
     except InvalidCommandException:
      print('Error: This camera does not support apps. Please check the compatibility list.')
      return
     device = None

     print('Waiting for camera to switch...')
     for i in range(20):
      time.sleep(.5)
      try:
       devices = list(listDevices(driver, True))
       if len(devices) == 1 and isinstance(devices[0], SonyAppInstallDevice):
        device = devices[0]
        break
      except:
       pass
     else:
      print('Operation timed out. Please run this command again when your camera has connected.')

    if device and isinstance(device, SonyAppInstallDevice):
     if isinstance(device, SonyMtpAppInstallDevice):
      installer_info = device.getDeviceInfo()
      if selected_model and normalize_camera_model(installer_info.model) != selected_model:
       print('Error: Camera model changed during installer transition; installation cancelled.')
       return
      if not isSonyMtpAppInstallCamera(installer_info):
       print('Error: PMCA installation unavailable: Sony installer proxy commands are not confirmed.')
       return
     return installApp(device, apkFile=io.BytesIO(apkData) if apkData else None, appPackage=None if apkData else appPackage, outFile=outFile, statusFunc=statusFunc)
    elif device:
     print('Error: Cannot use camera in this mode. Please switch to MTP or mass storage mode.')
  finally:
   set_camera_busy(False)


def appSelectionCommand():
 apps = list(listApps().values())
 for i, app in enumerate(apps):
  print(' [%2d] %s' % (i+1, app.package))
 i = int(input('Enter number of app to install (0 to abort): '))
 if i != 0:
  pkg = apps[i - 1].package
  print('')
  print('Installing %s' % pkg)
  return pkg
