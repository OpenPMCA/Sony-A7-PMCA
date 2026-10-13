#!/usr/bin/env python3
"""A simple gui interface"""
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.parse
from urllib import request
import webbrowser
from datetime import datetime
from queue import Empty
from tkinter import font as tkfont
from tkinter.filedialog import asksaveasfilename
from tkinter.messagebox import askyesno, showerror
import certifi
from pmca.appstore.recipelab import downloadRecipeLab, HttpsRedirectHandler
from pmca.appstore.catalog import loadCatalog, saveCatalog, syncCatalogMetadata, downloadCatalogApp, SEED_APPS
from pmca.util.http import DownloadCancelledError

import config
from pmca.commands.usb import *
from pmca.platform.backend.senser import *
from pmca.platform.backend.usb import *
from pmca.platform.tweaks import *
from pmca.ui import *

if getattr(sys, 'frozen', False):
 from frozenversion import version
else:
 from pmca import __version__ as version

class PrintRedirector(object):
 """Redirect writes to a function"""
 def __init__(self, func, parent=None):
  self.func = func
  self.parent = parent
 def write(self, str):
  if self.parent:
   self.parent.write(str)
  self.func(str)
 def flush(self):
  if self.parent:
   self.parent.flush()


import plistlib

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
    if node.get('idVendor') == 0x054c:
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
   'vendor': 'Sony (0x054c)',
   'serial': serial,
   'pid': hex(pid) if pid else None,
   'mode': mode,
   'count': len(sony_devices),
  }
 except Exception:
  pass
 return None





from pmca.commands.usb import getCameraStatus, checkCameraConnection


class AppLoadTask(BackgroundTask):
 def doBefore(self):
  self.ui.master.setCameraBusy(True)
  self.ui.updateProgress(None, 'Fetching community app catalog…')
  return True

 def do(self, arg):
  try:
   print('Loading community app catalog from GitHub…')
   return list(listApps().values())
  except Exception:
   traceback.print_exc()
   return None

 def doAfter(self, result):
  if result is not None:
   self.ui.setAppList(result)
   self.ui.updateProgress(100, 'Loaded %d catalog apps' % len(result))
  else:
   self.ui.onAppLoadFailed()
  self.ui.master.setCameraBusy(False)


class InfoTask(BackgroundTask):
 """Task to run infoCommand()"""
 def doBefore(self):
  if sys.platform == 'darwin':
   if not askyesno('Access camera', 'macOS may request permission to capture this camera. This can temporarily disconnect other camera clients.\n\nFinish any photo transfer and close Photos/Image Capture before continuing. This only reads camera information; it does not install an app.'):
    return False
  self.ui.master.setCameraBusy(True)
  self.captured_session = getattr(self.ui.master, "_cameraSessionId", 0)
  return self.ui.master.driverName

 def do(self, driverName):
  if driverName is False:
   return
  data = None
  try:
   print('')
   from pmca.commands import usb
   fn = globals().get('infoCommand')
   if fn and fn != getattr(usb, 'infoCommand', None):
    data = fn(driverName)
   elif hasattr(usb, 'getReadOnlyCameraInfo'):
    data = usb.getReadOnlyCameraInfo(driverName)
   else:
    data = usb.infoCommand(driverName)
  except Exception:
   traceback.print_exc()
  return True, data

 def doAfter(self, result):
  if result:
   current_session = getattr(self.ui.master, "_cameraSessionId", 0)
   if getattr(self, "captured_session", current_session) == current_session and getattr(self.ui.master, "cameraConnected", True) is not False:
    self.ui.showCameraInfo(result[1])
   self.ui.master.setCameraBusy(False)


def _setTaskDownloadBusy(ui, busy):
 master = getattr(ui, "master", None)
 if master is None:
  return
 if hasattr(master, "setDownloadBusy"):
  master.setDownloadBusy(busy)
 elif hasattr(master, "setCameraBusy"):
  master.setCameraBusy(busy)


class InstallTask(BackgroundTask):
 """Task to run installCommand()"""
 def doBefore(self):
  if not getattr(self.ui.master, "cameraConnected", True) or not getattr(self.ui.master, "cameraActionsEnabled", True):
   showerror('Cannot install APK', 'Camera is not connected in MTP mode. Connect camera and ensure it is ready.')
   return
  if getattr(self.ui.master, "cameraInstallEnabled", None) is False:
   reason = getattr(self.ui.master, "supportReason", "") or "PMCA app installation is not supported on this camera model."
   showerror('Cannot install APK', 'Cannot install app on this camera:\n\n%s' % reason)
   return
  if getattr(self.ui.master, "cameraBusy", False) or getattr(self.ui.master, "lastReportedBackendBusy", False) or getattr(self.ui.master, "downloadBusy", False):
   showerror('Cannot install APK', 'Camera is currently busy with another operation. Wait for the current operation to finish.')
   return
  mode, apkFilename, app = self.ui.getMode(), self.ui.getSelectedApk(), self.ui.getSelectedApp()
  apkData = None
  if mode == self.ui.MODE_APK:
   if not apkFilename or not os.path.isfile(apkFilename):
    showerror('Cannot install APK', 'No valid APK file selected. Choose a local APK or download one from the catalog first.')
    return
   try:
    with open(apkFilename, 'rb') as f:
     apkData = f.read()
    apk = ApkParser(io.BytesIO(apkData))
    if not apk.getPackageName().strip():
     raise Exception('The APK manifest has no package identifier.')
    sdk = apk.getMinSdkVersion()
    if not 1 <= sdk <= 10:
     raise Exception('The camera requires an APK with a minimum Android API between 1 and 10.')
    cert = None
    try:
     cert = apk.getCert()
    except Exception:
     cert = None
    if not cert:
     raise Exception('The APK signature certificate is missing or invalid.')
   except Exception as e:
    showerror('Cannot install APK', 'Choose a valid camera APK first.\n\n%s' % e)
    return
   name = os.path.basename(apkFilename)
  else:
   if not app:
    showerror('Cannot install app', 'Select an app first.')
    return
   name = app.package

  if not askyesno('Install app on camera', 'Install %s on the connected camera?\n\nConfirm that this app supports your model and firmware. Keep the camera powered and connected until the task completes.' % name):
   return
  if hasattr(self.ui, "_nextTaskGeneration"):
   self.taskGen = self.ui._nextTaskGeneration()
  self.ui.master.setCameraBusy(True)
  return mode, apkData, app, self.ui.master.driverName

 def do(self, args):
  if args is None:
   return
  mode, apkData, app, driverName = args
  response = None
  try:
   print('')
   self.ui.run(lambda: self._emitProgress(0, 'Starting installation'))
   if mode == self.ui.MODE_APP and app:
    response = installCommand(driverName=driverName, appPackage=app.package, statusFunc=self.onStatus)
   elif mode == self.ui.MODE_APK and apkData:
    response = installCommand(driverName=driverName, apkFile=io.BytesIO(apkData), statusFunc=self.onStatus)
  except Exception as e:
   traceback.print_exc()
   if getattr(e, "outcome_unknown", False) or hasattr(e, "phase"):
    return True, e
  return True, (response if response else False)

 def _emitProgress(self, percent, message):
  tgen = getattr(self, "taskGen", None)
  active = getattr(self.ui, "_activeTaskGen", tgen)
  if tgen is not None and active is not None and tgen != active:
   return
  self.ui.updateProgress(percent, message)

 def onStatus(self, status):
  printStatus(status)
  self.ui.run(lambda: self._emitProgress(status.percent, status.message))

 def doAfter(self, result):
  if result:
   self.ui.showInstallResult(result[1])
   self.ui.master.setCameraBusy(False)


class RecipeDownloadTask(BackgroundTask):
 """Download to a user-selected file; never communicate with the camera."""
 def doBefore(self):
  filename = asksaveasfilename(parent=self.ui.master, title='Save RecipeLab APK', initialdir=os.path.expanduser('~/Downloads'), initialfile='RecipeLab.apk', defaultextension='.apk', filetypes=[('Android apps', '*.apk')])
  if not filename:
   return
  if hasattr(self.ui, "_nextTaskGeneration"):
   self.taskGen = self.ui._nextTaskGeneration()
  self.abortEvent = threading.Event()
  self.ui.downloadAbortEvent = self.abortEvent
  _setTaskDownloadBusy(self.ui, True)
  self.ui.updateProgress(None, 'Checking the latest RecipeLab release')
  return filename

 def do(self, filename):
  if filename is None:
   return
  result = None
  try:
   print('Downloading RecipeLab from voxivoid/recipe-lab-sony-pmca')
   abort_ev = getattr(self, "abortEvent", None)
   result = downloadRecipeLab(filename, self.onProgress, abort_event=abort_ev)
   print('RecipeLab %s downloaded and validated (%d bytes). No camera app was installed.' % (result['version'], result['bytes']))
  except DownloadCancelledError:
   print('RecipeLab download cancelled.')
   return True, 'CANCELLED'
  except Exception:
   traceback.print_exc()
  return True, result

 def onProgress(self, downloaded, total):
  percent = 100 * downloaded / total if total else None
  message = 'Downloading RecipeLab (%d KB)' % (downloaded // 1024)
  def _upd(p=percent, m=message):
   tgen = getattr(self, "taskGen", None)
   active = getattr(self.ui, "_activeTaskGen", tgen)
   if tgen is not None and active is not None and tgen != active:
    return
   self.ui.updateProgress(p, m)
  self.ui.run(_upd)

 def doAfter(self, result):
  if result:
   if getattr(self.ui, "downloadAbortEvent", None) is getattr(self, "abortEvent", None):
    self.ui.downloadAbortEvent = None
   tgen = getattr(self, "taskGen", None)
   active = getattr(self.ui, "_activeTaskGen", tgen)
   is_current = (tgen is None or active is None or tgen == active)
   if result[1] == 'CANCELLED':
    if is_current and not getattr(self.ui.master, "cameraBusy", False):
     self.ui.updateProgress(0, 'Download cancelled')
   elif result[1]:
    self.ui.setApkFile(result[1]['path'])
    if is_current and not getattr(self.ui.master, "cameraBusy", False):
     self.ui.updateProgress(100, 'Download validated; not installed')
   else:
    if is_current and not getattr(self.ui.master, "cameraBusy", False):
     self.ui.updateProgress(0, 'Download failed; use a local APK or check Activity')
   _setTaskDownloadBusy(self.ui, False)



class CatalogAppDownloadTask(BackgroundTask):
 """Download a selected catalog app APK to a user-chosen file; never contact the camera."""
 def doBefore(self):
  app = self.ui.getSelectedApp()
  if not app:
   showerror('No application selected', 'Select an application from the catalog first.')
   return
  defaultName = '%s.apk' % (app.package or 'app')
  filename = asksaveasfilename(
   parent=self.ui.master,
   title='Save %s APK' % (app.name or 'Application'),
   initialdir=os.path.expanduser('~/Downloads'),
   initialfile=defaultName,
   defaultextension='.apk',
   filetypes=[('Android apps', '*.apk')]
  )
  if not filename:
   return
  if hasattr(self.ui, "_nextTaskGeneration"):
   self.taskGen = self.ui._nextTaskGeneration()
  self.abortEvent = threading.Event()
  self.ui.downloadAbortEvent = self.abortEvent
  self.appName = app.name or 'app'
  _setTaskDownloadBusy(self.ui, True)
  self.ui.updateProgress(None, 'Checking %s release information…' % (app.name or 'app'))
  return app, filename

 def do(self, args):
  if not args:
   return
  app, filename = args
  result = None
  try:
   print('Downloading %s (%s)…' % (app.name, app.package))
   abort_ev = getattr(self, "abortEvent", None)
   result = downloadCatalogApp(app, filename, self.onProgress, abort_event=abort_ev)
   print('%s %s downloaded and validated (%d bytes). No camera app was installed.' % (
    result['name'], result.get('version') or '', result['bytes']))
  except DownloadCancelledError:
   print('%s download cancelled.' % (app.name or 'App'))
   return True, 'CANCELLED'
  except Exception:
   traceback.print_exc()
  return True, result

 def onProgress(self, downloaded, total):
  percent = 100 * downloaded / total if total else None
  message = 'Downloading %s (%d KB)' % (getattr(self, 'appName', 'app'), downloaded // 1024)
  def _upd(p=percent, m=message):
   tgen = getattr(self, "taskGen", None)
   active = getattr(self.ui, "_activeTaskGen", tgen)
   if tgen is not None and active is not None and tgen != active:
    return
   self.ui.updateProgress(p, m)
  self.ui.run(_upd)

 def doAfter(self, result):
  if result:
   if getattr(self.ui, "downloadAbortEvent", None) is getattr(self, "abortEvent", None):
    self.ui.downloadAbortEvent = None
   tgen = getattr(self, "taskGen", None)
   active = getattr(self.ui, "_activeTaskGen", tgen)
   is_current = (tgen is None or active is None or tgen == active)
   if result[1] == 'CANCELLED':
    if is_current and not getattr(self.ui.master, "cameraBusy", False):
     self.ui.updateProgress(0, 'Download cancelled')
   elif result[1]:
    self.ui.setApkFile(result[1]['path'])
    if is_current and not getattr(self.ui.master, "cameraBusy", False):
     self.ui.updateProgress(100, '%s downloaded and validated; not installed' % result[1]['name'])
   else:
    if is_current and not getattr(self.ui.master, "cameraBusy", False):
     self.ui.updateProgress(0, 'Download failed; check Activity log')
   _setTaskDownloadBusy(self.ui, False)

class FirmwareUpdateTask(BackgroundTask):
 """Task to run firmwareUpdateCommand()"""
 def doBefore(self):
  self.ui.fwUpdateButton.config(state=DISABLED)
  return self.ui.getSelectedDat()

 def do(self, datFile):
  try:
   if datFile:
    print('')
    with open(datFile, 'rb') as f:
     firmwareUpdateCommand(f)
  except Exception:
   traceback.print_exc()

 def doAfter(self, result):
  self.ui.fwUpdateButton.config(state=NORMAL)


class StartPlatformShellTask(BackgroundTask):
 def doBefore(self):
  self.ui.startUpdaterShellButton.config(state=DISABLED)
  self.ui.startSenserShellButton.config(state=DISABLED)

 def do(self, arg):
  try:
   print('')
   self.start()
  except Exception:
   traceback.print_exc()

 def start(self):
  pass

 def launchShell(self, backend):
  backend.start()
  tweaks = TweakInterface(backend)

  if next(tweaks.getTweaks(), None):
   endFlag = threading.Event()
   root = self.ui.master
   root.run(lambda: root.after(0, lambda: TweakDialog(root, tweaks, endFlag)))
   endFlag.wait()
  else:
   print('No tweaks available')

  backend.stop()

 def doAfter(self, result):
  self.ui.startUpdaterShellButton.config(state=NORMAL)
  self.ui.startSenserShellButton.config(state=NORMAL)


class StartUpdaterShellTask(StartPlatformShellTask):
 """Task to run updaterShellCommand() and open TweakDialog"""
 def start(self):
  updaterShellCommand(complete=lambda dev: self.launchShell(UsbPlatformBackend(dev)))


class StartSenserShellTask(StartPlatformShellTask):
 """Task to run senserShellCommand() and open TweakDialog"""
 def start(self):
  senserShellCommand(complete=lambda dev: self.launchShell(SenserPlatformBackend(dev)))


class TweakApplyTask(BackgroundTask):
 """Task to run TweakInterface.apply()"""
 def doBefore(self):
  self.ui.setState(DISABLED)

 def do(self, arg):
  try:
   print('Applying tweaks...')
   self.ui.tweakInterface.apply()
  except Exception:
   traceback.print_exc()

 def doAfter(self, result):
  self.ui.setState(NORMAL)
  self.ui.cancel()


class MainUi(UiRoot):
 """Production desktop GUI: 1160x760 landscape, 3-item nav, real-time connection monitor, 2:8 vertical store."""
 QUEUE_MAX_SLICE_ITEMS = 40
 QUEUE_MAX_SLICE_SEC = 0.008
 QUEUE_IDLE_DELAY_MS = 16
 QUEUE_ACTIVE_DELAY_MS = 8
 MAX_LOG_RETENTION = 5000
 FILTER_DEBOUNCE_MS = 150
 FILTER_CHUNK_SIZE = 1000

 def __init__(self, title, installerOnly=False):
  self.maxLogEntries = self.MAX_LOG_RETENTION
  self.rawLogEntries = []
  self.omittedLogCount = 0
  self._logGeneration = 0
  self._filterGeneration = 0
  self._logFilterAfterId = None
  self._logFilterChunkAfterId = None
  self._pendingFilterAppends = []
  self._sliceLogBatch = []
  self._sliceLogEvictedCount = 0
  self._inQueueSlice = False
  self.downloadBusy = False
  self.fetchingInfo = False
  self._cameraSessionId = 0
  UiRoot.__init__(self)
  self.installerOnly = installerOnly
  try:
   from pmca.commands import usb as _usb_cmd
   self.driverName = _usb_cmd.getDefaultDriverName() if hasattr(_usb_cmd, "getDefaultDriverName") else ("libusb-mtp" if sys.platform == "darwin" else ("libusb" if sys.platform.startswith("linux") else None))
  except Exception:
   self.driverName = "libusb-mtp" if sys.platform == "darwin" else ("libusb" if sys.platform.startswith("linux") else None)
  self.cameraBusy = False
  self.cameraActionsEnabled = not installerOnly
  self.cameraConnected = False
  self.cameraInstallEnabled = False
  self.supportReason = ""
  self.lastReportedBackendBusy = False
  self.lastReportedState = None
  self.logBuffers = {False: "", True: ""}
  self.autoScroll = True
  self.abortSync = threading.Event()
  self.abortMonitor = threading.Event()
  self.protocol("WM_DELETE_WINDOW", self.close)
  if sys.platform == "darwin":
   self.createcommand("tk::mac::Quit", self.close)
  self.title(title)
  self.geometry("1160x760")
  self.minsize(960, 640)
  self["menu"] = Menu(self)

  style = Style(self)
  if sys.platform == "darwin" and "aqua" in style.theme_names():
   style.theme_use("aqua")
  family = tkfont.nametofont("TkDefaultFont").actual("family")
  style.configure("Title.TLabel", font=(family, 15, "bold"))
  style.configure("Section.TLabel", font=(family, 13, "bold"))
  style.configure("TLabelframe.Label", font=(family, 13, "bold"))
  style.configure("Subheading.TLabel", font=(family, 12, "bold"))
  style.configure("Detail.TLabel", font=(family, 11))
  style.layout("Hidden.TNotebook.Tab", [])
  style.configure("Hidden.TNotebook", borderwidth=0, highlightthickness=0)

  # Global Header (52px)
  header = Frame(self, padding=(16, 8))
  header.pack(side=TOP, fill=X)

  brandFrame = Frame(header)
  brandFrame.pack(side=LEFT)
  imagePath = os.path.join(scriptRoot, "assets/sony-open-pmca.png")
  if not os.path.isfile(imagePath):
   imagePath = os.path.join(scriptRoot, "assets/sony-open-pmca.png")
  if installerOnly and os.path.isfile(imagePath):
   self.logoImage = PhotoImage(master=self, file=imagePath).subsample(18, 18)
   Label(brandFrame, image=self.logoImage).pack(side=LEFT, padx=(0, 8))
  Label(brandFrame, text="Sony Open PMCA", style="Title.TLabel").pack(side=LEFT)
  Label(brandFrame, text="v%s" % version, style="Detail.TLabel").pack(side=LEFT, padx=(6, 0))

  statusFrame = Frame(header)
  statusFrame.pack(side=RIGHT)
  self.usbStatusVar = StringVar(value="○ Camera Disconnected")
  statusLabel = Label(statusFrame, textvariable=self.usbStatusVar, style="Detail.TLabel")
  statusLabel.pack(side=LEFT, padx=(0, 8))
  self.reconnectButton = Button(statusFrame, text="Reconnect", command=self.reconnectCamera, padding=(8, 3))
  self.reconnectButton.pack(side=LEFT)

  # Footer (30px)
  footer = Frame(self, padding=(18, 4, 18, 6))
  footer.pack(side=BOTTOM, fill=X)
  self.statusVar = StringVar(value="Idle.")
  Label(footer, textvariable=self.statusVar, style="Detail.TLabel").pack(side=LEFT)
  Label(footer, text="Version %s" % version, style="Detail.TLabel").pack(side=RIGHT)

  # Sidebar (156px) - Exactly 3 navigation items
  self.sidebar = Frame(self, padding=(8, 10), width=156)
  self.sidebar.pack(side=LEFT, fill=Y, padx=(10, 0), pady=(0, 4))
  self.sidebar.pack_propagate(False)

  self.navButtons = []
  navItems = [("Info", 0), ("Application", 1), ("Logs", 2)]
  for label, idx in navItems:
   btn = Button(self.sidebar, text=label, command=lambda i=idx: self.selectTab(i), padding=(10, 4))
   btn.pack(fill=X, pady=2)
   self.navButtons.append((btn, label))

  # Central Notebook (Hidden Tabs)
  self.notebook = Notebook(self, padding=(8, 0, 10, 2), style="Hidden.TNotebook")
  self.notebook.pack(side=LEFT, fill=BOTH, expand=True)
  self.notebook.bind("<<NotebookTabChanged>>", lambda e: self.updateNavHighlight())

  self.infoFrame = InfoFrame(self, padding=(14, 6))
  self.installerFrame = InstallerFrame(self, padding=(10, 4))
  self.activityFrame = Frame(self, padding=16)

  self.notebook.add(self.infoFrame, text="Camera")
  self.notebook.add(self.installerFrame, text="Applications")
  self.notebook.add(self.activityFrame, text="Activity")
  self.notebook.select(self.installerFrame)

  # Redesigned Logs View
  logToolbar = Frame(self.activityFrame)
  logToolbar.pack(fill=X, pady=(0, 8))
  Label(logToolbar, text="Activity Logs", style="Section.TLabel").pack(side=LEFT)
  Button(logToolbar, text="Clear", command=self.clearLog).pack(side=RIGHT)
  Button(logToolbar, text="Save log…", command=self.exportLog).pack(side=RIGHT, padx=(0, 6))
  Button(logToolbar, text="Copy errors", command=self.copyErrors).pack(side=RIGHT, padx=(0, 6))
  Button(logToolbar, text="Copy log", command=self.copyLog).pack(side=RIGHT, padx=(0, 6))

  logFilterBar = Frame(self.activityFrame)
  logFilterBar.pack(fill=X, pady=(0, 6))
  Label(logFilterBar, text="Search logs:", style="Detail.TLabel").pack(side=LEFT, padx=(0, 6))
  self.logFilterVar = StringVar()
  self.logFilterVar.trace_add("write", lambda *_: self._onLogFilterChanged())
  self.logFilterEntry = Entry(logFilterBar, textvariable=self.logFilterVar, width=24)
  self.logFilterEntry.pack(side=LEFT, padx=(0, 10))
  self.logLevelVar = StringVar(value="All")
  self.logLevelCombo = Combobox(logFilterBar, textvariable=self.logLevelVar, values=["All", "Errors only", "Info only"], state="readonly", width=12)
  self.logLevelCombo.pack(side=LEFT, padx=(0, 10))
  self.logLevelCombo.bind("<<ComboboxSelected>>", lambda e: self._applyLogFilterNow())
  self.logOmissionVar = StringVar(value="")
  self.logOmissionLabel = Label(logFilterBar, textvariable=self.logOmissionVar, style="Detail.TLabel")
  self.logOmissionLabel.pack(side=LEFT, padx=(0, 8))
  self.autoScrollBtn = Button(logFilterBar, text="Auto-scroll: ON", command=self.toggleAutoScroll)
  self.autoScrollBtn.pack(side=RIGHT)

  self.logText = ScrollingText(self.activityFrame)
  self.logText.text.configure(state=DISABLED, font=("Menlo" if sys.platform == "darwin" else "Courier", 11), relief="flat", borderwidth=0, height=18)
  if sys.platform == "darwin":
   self.logText.text.configure(background="systemTextBackgroundColor", foreground="systemTextColor")
  background = self.winfo_rgb(self.logText.text.cget("background"))
  dark = sum(background) < 3 * 32768
  self.logText.text.tag_configure("error", foreground="#FF6961" if dark else "#C93435")
  self.logText.text.tag_configure("info", foreground=self.logText.text.cget("foreground"))
  self.logText.pack(fill=BOTH, expand=True)

  self.setCameraBusy(False)
  self.redirectStreams()
  self.updateNavHighlight()
  self.startCameraMonitor()
  self._setupScrollClasses()
  self._setupNavShortcuts()

 def _setupNavShortcuts(self):
  for idx in (0, 1, 2):
   key_num = idx + 1
   try:
    if sys.platform == "darwin":
     self.bind_all("<Command-Key-%d>" % key_num, lambda e, i=idx: self._onNavShortcut(i))
    self.bind_all("<Control-Key-%d>" % key_num, lambda e, i=idx: self._onNavShortcut(i))
   except Exception:
    pass

 def _onNavShortcut(self, idx):
  if 0 <= idx < len(getattr(self, "navButtons", [])):
   self.selectTab(idx)
  return "break"

 def _setupScrollClasses(self):
  """Bind StoreScrollable class events across TouchpadScroll, MouseWheel, and Linux buttons."""
  try:
   self.bind_class("StoreScrollable", "<TouchpadScroll>", self._onTouchpadScroll)
  except Exception:
   pass
  try:
   self.bind_class("StoreScrollable", "<MouseWheel>", self._onMouseWheel)
   self.bind_class("StoreScrollable", "<Button-4>", self._onButtonScrollUp)
   self.bind_class("StoreScrollable", "<Button-5>", self._onButtonScrollDown)
  except Exception:
   pass

 def _decodeTouchpadScroll(self, dxdy):
  try:
   if hasattr(self, "tk"):
    res = self.tk.call("tk::PreciseScrollDeltas", dxdy)
    if isinstance(res, (list, tuple)) and len(res) == 2:
     return int(res[0]), int(res[1])
  except Exception:
   pass
  deltaX = dxdy >> 16
  low = dxdy & 0xffff
  deltaY = low if low < 0x8000 else low - 0x10000
  return deltaX, deltaY

 def _onTouchpadScroll(self, event):
  installer = getattr(self, "installerFrame", None)
  if not installer or not hasattr(installer, "canvas") or not installer.canvas.winfo_ismapped():
   return "break"
  raw = getattr(event, "delta", 0)
  dx, dy = self._decodeTouchpadScroll(raw)
  if dy != 0:
   installer.canvas.yview_scroll(-1 * dy, "units")
  return "break"

 def _onMouseWheel(self, event):
  installer = getattr(self, "installerFrame", None)
  if not installer or not hasattr(installer, "canvas") or not installer.canvas.winfo_ismapped():
   return "break"
  raw = getattr(event, "delta", 0)
  if raw != 0:
   if abs(raw) >= 120:
    units = -1 * round((raw / 120.0) * 60)
   else:
    units = -1 * round(raw * 60)
   if units == 0:
    units = -1 if raw > 0 else 1
   installer.canvas.yview_scroll(units, "units")
  return "break"

 def _onButtonScrollUp(self, event):
  installer = getattr(self, "installerFrame", None)
  if installer and hasattr(installer, "canvas") and installer.canvas.winfo_ismapped():
   installer.canvas.yview_scroll(-60, "units")
  return "break"

 def _onButtonScrollDown(self, event):
  installer = getattr(self, "installerFrame", None)
  if installer and hasattr(installer, "canvas") and installer.canvas.winfo_ismapped():
   installer.canvas.yview_scroll(60, "units")
  return "break"

 def _runSafely(self, func):
  """Thread-safe dispatch to the main GUI thread via UiRoot queue only."""
  self.run(func)

 def selectTab(self, idx):
  self.notebook.select(idx)
  self.updateNavHighlight()

 def updateNavHighlight(self):
  if not hasattr(self, "navButtons") or not self.navButtons:
   return
  current = self.notebook.index(self.notebook.select()) if self.notebook.select() else 0
  for i, (btn, baseLabel) in enumerate(self.navButtons):
   btn.config(text=("• " + baseLabel) if i == current else baseLabel)

 def toggleAutoScroll(self):
  self.autoScroll = not getattr(self, "autoScroll", True)
  self.autoScrollBtn.config(text="Auto-scroll: ON" if self.autoScroll else "Resume auto-scroll")
  if self.autoScroll:
   self.logText.text.see(END)

 def _canPollCameraMonitor(self):
  return not bool(getattr(self, "cameraBusy", False) or getattr(self, "fetchingInfo", False))

 def startCameraMonitor(self):
  threading.Thread(target=self._cameraMonitorWorker, daemon=True).start()

 def _cameraMonitorWorker(self):
  while hasattr(self, "abortMonitor") and not self.abortMonitor.is_set():
   if self._canPollCameraMonitor():
    try:
     import inspect
     sig = inspect.signature(checkCameraConnection)
     if "quiet" in sig.parameters:
      info = checkCameraConnection(self.driverName, quiet=True)
     else:
      info = checkCameraConnection(self.driverName)
     self._runSafely(lambda i=info: self.onCameraStatusUpdate(i))
    except Exception as e:
     print("Camera monitor error:", e)
   if self.abortMonitor.wait(3.0):
    break

 def fetchSafeCameraInfo(self, info=None):
  if getattr(self, "fetchingInfo", False) or self.cameraBusy:
   return
  captured_model = info.get("model") or info.get("name") if info else None
  captured_serial = info.get("serial") or info.get("raw_serial") if info else None
  captured_id = (captured_model, captured_serial)
  self.fetchingInfo = True
  def worker():
   try:
    from pmca.commands import usb
    fn = globals().get('infoCommand')
    if fn and fn != getattr(usb, 'infoCommand', None):
     data = fn(self.driverName)
    elif hasattr(usb, 'getReadOnlyCameraInfo'):
     data = usb.getReadOnlyCameraInfo(self.driverName)
    elif hasattr(usb, 'infoCommand'):
     data = usb.infoCommand(self.driverName)
    else:
     data = None
    if data:
     def apply_info(d=data, cid=captured_id):
      if not getattr(self, "cameraConnected", False):
       return
      current_model = getattr(self.infoFrame, "cameraSnapshot", {}).get("Model")
      current_serial = getattr(self.infoFrame, "cameraSnapshot", {}).get("Serial number")
      current_raw = getattr(self.infoFrame, "cameraSnapshot", {}).get("PTP descriptor")
      if cid[0] and current_model and current_model != "—" and cid[0] != current_model:
       return
      if cid[1] and current_serial and current_serial != "—" and cid[1] not in (current_serial, current_raw):
       return
      self.infoFrame.showCameraInfo(d)
     self._runSafely(apply_info)
   except Exception:
    pass
   finally:
    self.fetchingInfo = False
  threading.Thread(target=worker, daemon=True).start()

 def onCameraStatusUpdate(self, info):
  appConnected = bool(info and info.get("appConnected"))
  physical = bool(info and (info.get("physicalDetected") or info.get("connected") or "USB" in str(info.get("status", "")) or info.get("status") in ("access_denied", "unverified", "multiple_devices", "msc_excluded", "wrong_mode", "unsupported_mode")))
  status = info.get("status") if info else "disconnected"
  self.lastReportedPhysical = physical
  just_connected = appConnected and not getattr(self, "cameraConnected", False)
  backend_busy = bool(info and info.get("busy"))
  self.lastReportedBackendBusy = backend_busy

  new_session_key = (
   appConnected,
   (info.get("name") or info.get("model")) if isinstance(info, dict) else None,
   (info.get("serial") or info.get("raw_serial")) if isinstance(info, dict) else None,
  ) if appConnected else (False, None, None)
  if getattr(self, "_lastCameraSessionKey", (False, None, None)) != new_session_key:
   self._lastCameraSessionKey = new_session_key
   self._cameraSessionId = getattr(self, "_cameraSessionId", 0) + 1

  if getattr(self, "lastReportedState", None) != (appConnected, status):
   self.lastReportedState = (appConnected, status)
   if appConnected:
    print("Camera connection established: %s [%s] via %s" % (info.get("name", "Camera"), info.get("vendor", "Sony"), info.get("mode", "MTP")))
   elif physical:
    reason = info.get("failure_reason") or "app connection unavailable"
    print("USB device detected on bus: %s (%s)" % (info.get("name", "Sony Camera"), reason))
   else:
    print("Camera disconnected")

  if appConnected:
   self.cameraConnected = True
   self.cameraActionsEnabled = True

   if hasattr(info, "get") and info.get("app_installation_supported") is not None:
    if backend_busy:
     self.cameraInstallEnabled = False
     self.supportReason = "Camera is currently busy."
    else:
     self.cameraInstallEnabled = bool(info["app_installation_supported"])
     self.supportReason = info.get("app_installation_reason") or ("Ready to install." if self.cameraInstallEnabled else "Not supported.")
   else:
    self.cameraInstallEnabled = False
    self.supportReason = "Camera is currently busy." if backend_busy else (info.get("app_installation_reason") if hasattr(info, "get") and info.get("app_installation_reason") else "Camera installation eligibility is unverified.")

   self.usbStatusVar.set("● Connected: %s (%s)" % (info.get("name", "Camera"), info.get("mode", "MTP")))
   if hasattr(self, "infoFrame") and hasattr(self.infoFrame, "showConnectedCamera"):
    self.infoFrame.showConnectedCamera(info)
   if hasattr(self, "installerFrame") and hasattr(self.installerFrame, "updateCameraStatus"):
    self.installerFrame.updateCameraStatus(True, info.get("mode", "MTP"), info.get("name"), self.cameraInstallEnabled, self.supportReason)
   if just_connected and hasattr(self, "fetchSafeCameraInfo") and not backend_busy:
    self.fetchSafeCameraInfo(info)

  elif physical:
   self.cameraConnected = False
   self.cameraActionsEnabled = False
   self.cameraInstallEnabled = False
   mode_str = str(info.get("mode") or "")
   if status == "multiple_devices":
    reason = info.get("failure_reason") or "Multiple Sony cameras detected. Connect only one Sony camera at a time."
    self.supportReason = reason
    self.usbStatusVar.set("○ Multiple Sony cameras connected")
   elif "Mass Storage" in mode_str or "MSC" in mode_str or status in ("msc_excluded", "wrong_mode", "unsupported_mode"):
    reason = info.get("failure_reason") or "Camera is in Mass Storage mode. Switch USB Connection to MTP in the camera Setup menu."
    self.supportReason = reason
    self.usbStatusVar.set("○ USB Mass Storage — MTP unavailable")
   elif "access_denied" in str(status):
    reason = info.get("failure_reason") or "USB access denied."
    self.supportReason = reason
    self.usbStatusVar.set("○ USB detected, MTP unavailable")
   else:
    reason = info.get("failure_reason") or "app connection unavailable"
    self.supportReason = reason
    self.usbStatusVar.set("○ USB detected, MTP unavailable")

   if hasattr(self, "infoFrame") and hasattr(self.infoFrame, "showConnectedCamera"):
    self.infoFrame.showConnectedCamera(info)
   if hasattr(self, "installerFrame") and hasattr(self.installerFrame, "updateCameraStatus"):
    self.installerFrame.updateCameraStatus(False, info.get("mode", "MTP"), info.get("name"), False, self.supportReason)

  else:
   self.cameraConnected = False
   self.cameraActionsEnabled = False
   self.cameraInstallEnabled = False
   self.supportReason = "Camera not connected. Connect camera in MTP mode to enable install."
   self.usbStatusVar.set("○ Camera Disconnected")
   if hasattr(self, "infoFrame") and hasattr(self.infoFrame, "showConnectedCamera"):
    self.infoFrame.showConnectedCamera(None)
   if hasattr(self, "installerFrame") and hasattr(self.installerFrame, "updateCameraStatus"):
    self.installerFrame.updateCameraStatus(False, installSupported=False, installReason=self.supportReason)

  self.setCameraBusy(self.cameraBusy)

 def reconnectCamera(self):
  if self.cameraBusy:
   return
  self._cameraSessionId = getattr(self, "_cameraSessionId", 0) + 1
  self.usbStatusVar.set("Scanning USB…")
  threading.Thread(target=self._manualProbeWorker, daemon=True).start()

 def _manualProbeWorker(self):
  try:
   import inspect
   sig = inspect.signature(checkCameraConnection)
   if "quiet" in sig.parameters:
    info = checkCameraConnection(self.driverName, quiet=True)
   else:
    info = checkCameraConnection(self.driverName)
   self._runSafely(lambda i=info: self.onCameraStatusUpdate(i))
  except Exception as e:
   print("Manual reconnect error:", e)

 def checkPassiveUsb(self):
  info = checkCameraConnection(self.driverName)
  self.onCameraStatusUpdate(info)

 def _buildFilteredLogSnapshot(self):
  raw_entries = getattr(self, "rawLogEntries", None)
  if not raw_entries:
   return self.logText.text.get("1.0", END).rstrip()
  q = self.logFilterVar.get() if hasattr(self, "logFilterVar") else ""
  q_low = q.lower()
  level = self.logLevelVar.get() if hasattr(self, "logLevelVar") else "All"
  omitted = getattr(self, "omittedLogCount", 0)
  lines = []
  for ts, text, tag in list(raw_entries):
   if level == "Errors only" and tag != "error":
    continue
   if level == "Info only" and tag != "info":
    continue
   if q_low and q_low not in text.lower():
    continue
   lines.append("[%s] %s" % (ts, text))
  header_parts = []
  if level != "All" or q != "" or omitted > 0:
   scope_desc = "level=%s" % level
   if q != "":
    scope_desc += ', filter="%s"' % q
   if omitted > 0:
    scope_desc += ", %d older lines omitted (retaining latest %d)" % (omitted, getattr(self, "maxLogEntries", 5000))
   header_parts.append("# Activity Log Snapshot (%s)" % scope_desc)
  return "\n".join(header_parts + lines)

 def exportLog(self):
  filename = asksaveasfilename(
   parent=self,
   title="Save Activity Log",
   initialdir=os.path.expanduser("~/Downloads"),
   initialfile="pmca-activity-%s.log" % datetime.now().strftime("%Y%m%d-%H%M%S"),
   defaultextension=".log",
   filetypes=[("Log files", "*.log"), ("Text files", "*.txt"), ("All files", "*")]
  )
  if filename:
   try:
    snapshot = self._buildFilteredLogSnapshot() if hasattr(self, "_buildFilteredLogSnapshot") else self.logText.text.get("1.0", END).rstrip()
    with open(filename, "w", encoding="utf-8") as f:
     f.write(snapshot)
    print("Activity log saved to %s" % filename)
   except Exception as e:
    showerror("Cannot save log", str(e))

 def copyErrors(self):
  error_blocks = []
  current_block = []
  for ts, line, tag in getattr(self, "rawLogEntries", []):
   if tag == "error":
    current_block.append("[%s] %s" % (ts, line))
   else:
    if current_block:
     error_blocks.append("\n".join(current_block))
     current_block = []
  if current_block:
   error_blocks.append("\n".join(current_block))
  omitted = getattr(self, "omittedLogCount", 0)
  prefix = ""
  if omitted > 0:
   prefix = "[Warning: %d older log lines were omitted/evicted; earlier error or traceback context may be missing.]\n\n" % omitted
  body = "\n\n".join(error_blocks) if error_blocks else "No errors in log."
  text = prefix + body
  self.clipboard_clear()
  self.clipboard_append(text)
  print("Copied %d complete error blocks to clipboard" % len(error_blocks))

 def _onLogFilterChanged(self):
  self._filterGeneration = getattr(self, "_filterGeneration", 0) + 1
  self._pendingFilterAppends = []
  self._pendingFilterEvictions = 0
  if getattr(self, "_logFilterAfterId", None) is not None:
   try:
    self.after_cancel(self._logFilterAfterId)
   except Exception:
    pass
   self._logFilterAfterId = None
  if getattr(self, "_logFilterChunkAfterId", None) is not None:
   try:
    self.after_cancel(self._logFilterChunkAfterId)
   except Exception:
    pass
   self._logFilterChunkAfterId = None
  debounce = getattr(self, "FILTER_DEBOUNCE_MS", 150)
  try:
   self._logFilterAfterId = self.after(debounce, self._applyLogFilterNow)
  except Exception:
   self.filterLogDisplay()

 def _applyLogFilterNow(self):
  if getattr(self, "_logFilterAfterId", None) is not None:
   try:
    self.after_cancel(self._logFilterAfterId)
   except Exception:
    pass
   self._logFilterAfterId = None
  self.filterLogDisplay()

 def filterLogDisplay(self):
  if getattr(self, "_logFilterAfterId", None) is not None:
   try:
    self.after_cancel(self._logFilterAfterId)
   except Exception:
    pass
   self._logFilterAfterId = None
  if getattr(self, "_logFilterChunkAfterId", None) is not None:
   try:
    self.after_cancel(self._logFilterChunkAfterId)
   except Exception:
    pass
   self._logFilterChunkAfterId = None
  self._pendingFilterAppends = []
  self._pendingFilterEvictions = 0
  self._filterGeneration = getattr(self, "_filterGeneration", 0) + 1
  gen = self._filterGeneration
  q = self.logFilterVar.get().lower() if hasattr(self, "logFilterVar") else ""
  level = self.logLevelVar.get() if hasattr(self, "logLevelVar") else "All"
  matching = []
  for timestamp, text, tag in getattr(self, "rawLogEntries", []):
   if level == "Errors only" and tag != "error":
    continue
   if level == "Info only" and tag != "info":
    continue
   if q and q not in text.lower():
    continue
   matching.append((tag, "[%s] %s\n" % (timestamp, text)))

  chunk_size = getattr(self, "FILTER_CHUNK_SIZE", 1000)
  first_batch = matching[:chunk_size]
  remaining = matching[chunk_size:]

  saved_sel_ranges = []
  saved_sel_text = ""
  try:
   y_top, y_bottom = self.logText.text.yview()
   raw_sel = self.logText.text.tag_ranges("sel")
   has_sel = bool(raw_sel)
   if has_sel:
    saved_sel_ranges = [str(idx) for idx in raw_sel]
    if len(saved_sel_ranges) >= 2:
     saved_sel_text = self.logText.text.get(saved_sel_ranges[0], saved_sel_ranges[1])
   if y_bottom < 0.98 or has_sel:
    self.autoScroll = False
    if hasattr(self, "autoScrollBtn"):
     self.autoScrollBtn.config(text="Resume auto-scroll")
  except Exception:
   pass
  self._savedFilterSelection = (saved_sel_text, saved_sel_ranges)

  self.logText.text.configure(state=NORMAL)
  self.logText.text.delete("1.0", END)
  runs = []
  for tag, formatted in first_batch:
   if runs and runs[-1][0] == tag:
    runs[-1] = (tag, runs[-1][1] + formatted)
   else:
    runs.append((tag, formatted))
  for run_tag, run_text in runs:
   self.logText.text.insert(END, run_text, run_tag)
  sel_info = getattr(self, "_savedFilterSelection", None)
  if sel_info and (sel_info[0] or sel_info[1]):
   try:
    sel_text, sel_ranges = sel_info
    if sel_text:
     pos = self.logText.text.search(sel_text, "1.0", END)
     if pos:
      self.logText.text.tag_remove("sel", "1.0", END)
      self.logText.text.tag_add("sel", pos, "%s+%dc" % (pos, len(sel_text)))
    elif len(sel_ranges) >= 2 and self.logText.text.compare(sel_ranges[0], "<", "end-1c"):
     self.logText.text.tag_remove("sel", "1.0", END)
     self.logText.text.tag_add("sel", sel_ranges[0], sel_ranges[1])
   except Exception:
    pass
  self.logText.text.configure(state=DISABLED)
  if remaining and hasattr(self, "after"):
   self._logFilterChunkAfterId = self.after(4, lambda g=gen, rem=remaining: self._renderFilterChunk(g, rem))
  elif getattr(self, "autoScroll", True):
   self.logText.text.see(END)

 def _renderFilterChunk(self, gen, remaining):
  self._logFilterChunkAfterId = None
  if getattr(self, "_closed", False) or gen != getattr(self, "_filterGeneration", 0):
   return
  try:
   y_top, y_bottom = self.logText.text.yview()
   has_sel = bool(self.logText.text.tag_ranges("sel"))
   if y_bottom < 0.98 or has_sel:
    self.autoScroll = False
    if hasattr(self, "autoScrollBtn"):
     self.autoScrollBtn.config(text="Resume auto-scroll")
  except Exception:
   pass
  chunk_size = getattr(self, "FILTER_CHUNK_SIZE", 1000)
  batch = remaining[:chunk_size]
  rest = remaining[chunk_size:]
  runs = []
  for tag, formatted in batch:
   if runs and runs[-1][0] == tag:
    runs[-1] = (tag, runs[-1][1] + formatted)
   else:
    runs.append((tag, formatted))
  self.logText.text.configure(state=NORMAL)
  for run_tag, run_text in runs:
   self.logText.text.insert(END, run_text, run_tag)
  sel_info = getattr(self, "_savedFilterSelection", None)
  if sel_info and (sel_info[0] or sel_info[1]):
   try:
    sel_text, sel_ranges = sel_info
    if sel_text:
     pos = self.logText.text.search(sel_text, "1.0", END)
     if pos:
      self.logText.text.tag_remove("sel", "1.0", END)
      self.logText.text.tag_add("sel", pos, "%s+%dc" % (pos, len(sel_text)))
    elif len(sel_ranges) >= 2 and self.logText.text.compare(sel_ranges[0], "<", "end-1c"):
     self.logText.text.tag_remove("sel", "1.0", END)
     self.logText.text.tag_add("sel", sel_ranges[0], sel_ranges[1])
   except Exception:
    pass
  self.logText.text.configure(state=DISABLED)
  if rest and hasattr(self, "after"):
   self._logFilterChunkAfterId = self.after(4, lambda g=gen, rem=rest: self._renderFilterChunk(g, rem))
  else:
   pending_runs = getattr(self, "_pendingFilterAppends", None)
   pending_evict = getattr(self, "_pendingFilterEvictions", 0)
   self._pendingFilterAppends = []
   self._pendingFilterEvictions = 0
   if pending_runs or pending_evict > 0:
    self._appendFormattedRunsToText(pending_runs or [], evicted_matching_count=pending_evict)
   elif getattr(self, "autoScroll", True):
    self.logText.text.see(END)

 def setDownloadBusy(self, busy):
  self.downloadBusy = bool(busy)
  self.setCameraBusy(getattr(self, "cameraBusy", False))

 def setCameraBusy(self, busy):
  self.cameraBusy = bool(busy)
  dl_busy = bool(getattr(self, "downloadBusy", False))
  any_busy = bool(self.cameraBusy or dl_busy)
  state = DISABLED if any_busy else NORMAL
  cameraState = (DISABLED if self.cameraBusy else NORMAL) if getattr(self, "cameraActionsEnabled", True) else DISABLED
  if hasattr(self, "infoFrame") and hasattr(self.infoFrame, "infoButton"):
   self.infoFrame.infoButton.config(state=cameraState)
  if hasattr(self, "installerFrame") and hasattr(self.installerFrame, "updateInstallButton"):
   self.installerFrame.updateInstallButton()
  elif hasattr(self, "installerFrame") and hasattr(self.installerFrame, "installButton"):
   self.installerFrame.installButton.config(state=DISABLED if any_busy or not getattr(self, "cameraActionsEnabled", True) else NORMAL)
  for name in ["downloadButton", "apkSelectButton", "apkRevealButton", "appLoadButton", "appDownloadButton"]:
   button = getattr(self.installerFrame, name, None)
   if button is not None:
    if not any_busy and name == "appDownloadButton":
     selected = self.installerFrame.getSelectedApp() if hasattr(self.installerFrame, "getSelectedApp") else None
     button.config(state=NORMAL if selected else DISABLED)
    elif not any_busy and name == "apkRevealButton":
     apkPath = self.installerFrame.getSelectedApk() if hasattr(self.installerFrame, "getSelectedApk") else None
     button.config(state=NORMAL if (apkPath and os.path.isfile(apkPath)) else DISABLED)
    else:
     button.config(state=state)
  combo = getattr(self.installerFrame, "appCombo", None)
  if combo is not None:
   combo.config(state=DISABLED if any_busy else "readonly")
  search = getattr(self.installerFrame, "searchEntry", None)
  if search is not None:
   search.config(state=DISABLED if any_busy else NORMAL)
  if hasattr(self, "reconnectButton"):
   self.reconnectButton.config(state=DISABLED if self.cameraBusy else NORMAL)
  if hasattr(self.installerFrame, "setStoreBusy"):
   self.installerFrame.setStoreBusy(any_busy)
  if hasattr(self.installerFrame, "cancelDownloadButton"):
   can_cancel = bool(dl_busy and not self.cameraBusy)
   self.installerFrame.cancelDownloadButton.config(state=NORMAL if can_cancel else DISABLED)
  if hasattr(self, "statusVar"):
   if self.cameraBusy:
    self.statusVar.set("An operation is running…")
   elif dl_busy:
    self.statusVar.set("Downloading APK…")
   elif not getattr(self, "cameraActionsEnabled", True):
    self.statusVar.set("Camera not connected — connect camera in MTP mode.")
   else:
    self.statusVar.set("Idle.")

 def _processQueue(self):
  if getattr(self, "_queueAfterId", None) is not None:
   try:
    self.after_cancel(self._queueAfterId)
   except Exception:
    pass
   self._queueAfterId = None
  slice_start = time.perf_counter()
  processed = 0
  max_items = getattr(self, "QUEUE_MAX_SLICE_ITEMS", 40)
  max_sec = getattr(self, "QUEUE_MAX_SLICE_SEC", 0.008)
  self._inQueueSlice = True
  try:
   while processed < max_items:
    try:
     func = self._queue.get(block=False)
    except Empty:
     break
    processed += 1
    try:
     func()
    except Exception:
     traceback.print_exc()
    if processed >= max_items or (time.perf_counter() - slice_start) >= max_sec:
     break
  finally:
   self._inQueueSlice = False
   if getattr(self, "_sliceLogBatch", None) or getattr(self, "_sliceLogEvictedCount", 0) > 0:
    self._flushSliceLogBatch()
  if not getattr(self, "_closed", False):
   delay = getattr(self, "QUEUE_ACTIVE_DELAY_MS", 8) if not self._queue.empty() else getattr(self, "QUEUE_IDLE_DELAY_MS", 16)
   self._queueAfterId = self.after(delay, self._processQueue)

 def close(self):
  if getattr(self, "cameraBusy", False) or getattr(self, "fetchingInfo", False) or getattr(self, "lastReportedBackendBusy", False):
   showerror("Operation in progress", "Wait for the current operation to finish before closing. If the camera is in use, keep it connected.")
   return
  if getattr(self, "downloadBusy", False) and hasattr(self, "installerFrame") and hasattr(self.installerFrame, "cancelDownload"):
   self.installerFrame.cancelDownload()
  self.destroy()

 def destroy(self):
  self._closed = True
  for timer_attr in ("_queueAfterId", "_logFilterAfterId", "_logFilterChunkAfterId"):
   tid = getattr(self, timer_attr, None)
   if tid is not None:
    try:
     self.after_cancel(tid)
    except Exception:
     pass
    setattr(self, timer_attr, None)
  if hasattr(self, "abortMonitor"):
   self.abortMonitor.set()
  abort = getattr(self, "abortSync", None)
  if abort is not None:
   abort.set()
  if hasattr(self, "_origStreams") and self._origStreams:
   sys.stdout, sys.stderr = self._origStreams
   self._origStreams = None
  UiRoot.destroy(self)

 def _updateOmissionNotice(self):
  if not hasattr(self, "logOmissionVar"):
   return
  omitted = getattr(self, "omittedLogCount", 0)
  max_entries = getattr(self, "maxLogEntries", 5000)
  if omitted > 0:
   self.logOmissionVar.set("{:,} older lines omitted (retaining latest {:,})".format(omitted, max_entries))
  else:
   self.logOmissionVar.set("")

 def _appendFormattedRunsToText(self, runs, evicted_matching_count=0):
  if not runs and evicted_matching_count <= 0:
   return
  if getattr(self, "_logFilterChunkAfterId", None) is not None or getattr(self, "_logFilterAfterId", None) is not None:
   if getattr(self, "_logFilterChunkAfterId", None) is not None:
    if not hasattr(self, "_pendingFilterAppends") or self._pendingFilterAppends is None:
     self._pendingFilterAppends = []
    self._pendingFilterAppends.extend(runs)
    self._pendingFilterEvictions = getattr(self, "_pendingFilterEvictions", 0) + evicted_matching_count
    return
  text_widget = self.logText.text
  try:
   y_top, y_bottom = text_widget.yview()
   has_sel = bool(text_widget.tag_ranges("sel"))
   if y_bottom < 0.98 or has_sel:
    self.autoScroll = False
    if hasattr(self, "autoScrollBtn"):
     self.autoScrollBtn.config(text="Resume auto-scroll")
  except Exception:
   pass
  text_widget.configure(state=NORMAL)
  try:
   for run_tag, run_text in runs:
    text_widget.insert(END, run_text, run_tag)
   if evicted_matching_count > 0:
    try:
     text_widget.delete("1.0", "%d.0" % (evicted_matching_count + 1))
    except Exception:
     pass
  finally:
   text_widget.configure(state=DISABLED)
  if getattr(self, "autoScroll", True):
   text_widget.see(END)

 def _flushSliceLogBatch(self):
  batch = getattr(self, "_sliceLogBatch", None)
  evicted_matching = getattr(self, "_sliceLogEvictedCount", 0)
  self._sliceLogBatch = []
  self._sliceLogEvictedCount = 0
  if not batch and evicted_matching <= 0:
   return
  runs = []
  for tag, formatted in (batch or []):
   if runs and runs[-1][0] == tag:
    runs[-1] = (tag, runs[-1][1] + formatted)
   else:
    runs.append((tag, formatted))
  self._appendFormattedRunsToText(runs, evicted_matching_count=evicted_matching)

 def log(self, msg, error=False):
  self.logBuffers[error] += msg
  if "\n" not in self.logBuffers[error]:
   return
  parts = self.logBuffers[error].split("\n")
  self.logBuffers[error] = parts.pop()
  ts = datetime.now().strftime("%H:%M:%S")
  q = self.logFilterVar.get().lower() if hasattr(self, "logFilterVar") else ""
  level = self.logLevelVar.get() if hasattr(self, "logLevelVar") else "All"
  has_raw = hasattr(self, "rawLogEntries")
  batch_entries = []
  for line in parts:
   if not line:
    continue
   tag = "error" if error or line.startswith(("Error:", "No devices found", "Operation timed out")) else "info"
   batch_entries.append((ts, line, tag))

  if not batch_entries:
   return

  evicted_matching_count = 0
  if has_raw:
   max_entries = getattr(self, "maxLogEntries", 5000)
   prev_len = len(self.rawLogEntries)
   batch_len = len(batch_entries)
   total_len = prev_len + batch_len
   if total_len > max_entries:
    overflow = total_len - max_entries
    evicted_from_prev = min(prev_len, overflow)
    for _, ev_line, ev_tag in self.rawLogEntries[:evicted_from_prev]:
     if (level == "Errors only" and ev_tag != "error") or (level == "Info only" and ev_tag != "info") or (q and q not in ev_line.lower()):
      continue
     evicted_matching_count += 1
    if overflow <= prev_len:
     del self.rawLogEntries[:overflow]
     surviving_batch = batch_entries
    else:
     self.rawLogEntries.clear()
     surviving_batch = batch_entries[-max_entries:]
    self.rawLogEntries.extend(surviving_batch)
    self.omittedLogCount = getattr(self, "omittedLogCount", 0) + overflow
    if hasattr(self, "_updateOmissionNotice"):
     self._updateOmissionNotice()
   else:
    surviving_batch = batch_entries
    self.rawLogEntries.extend(surviving_batch)
  else:
   surviving_batch = batch_entries

  new_matching = []
  for entry_ts, line, tag in surviving_batch:
   if (level == "Errors only" and tag != "error") or (level == "Info only" and tag != "info") or (q and q not in line.lower()):
    continue
   new_matching.append((tag, "[%s] %s\n" % (entry_ts, line)))

  if not new_matching and evicted_matching_count <= 0:
   return

  if getattr(self, "_inQueueSlice", False) and hasattr(self, "_sliceLogBatch"):
   self._sliceLogBatch.extend(new_matching)
   self._sliceLogEvictedCount = getattr(self, "_sliceLogEvictedCount", 0) + evicted_matching_count
   return

  runs = []
  for tag, formatted in new_matching:
   if runs and runs[-1][0] == tag:
    runs[-1] = (tag, runs[-1][1] + formatted)
   else:
    runs.append((tag, formatted))

  if hasattr(self, "_appendFormattedRunsToText"):
   self._appendFormattedRunsToText(runs, evicted_matching_count=evicted_matching_count)
  else:
   try:
    y_top, y_bottom = self.logText.text.yview()
    has_sel = bool(self.logText.text.tag_ranges("sel"))
    if y_bottom < 0.98 or has_sel:
     self.autoScroll = False
     if hasattr(self, "autoScrollBtn"):
      self.autoScrollBtn.config(text="Resume auto-scroll")
   except Exception:
    pass
   self.logText.text.configure(state=NORMAL)
   for run_tag, run_text in runs:
    self.logText.text.insert(END, run_text, run_tag)
   self.logText.text.configure(state=DISABLED)
   if getattr(self, "autoScroll", True):
    self.logText.text.see(END)

 def copyLog(self):
  snapshot = self._buildFilteredLogSnapshot() if hasattr(self, "_buildFilteredLogSnapshot") else self.logText.text.get("1.0", END).rstrip()
  self.clipboard_clear()
  self.clipboard_append(snapshot)

 def clearLog(self):
  self._logGeneration = getattr(self, "_logGeneration", 0) + 1
  self._filterGeneration = getattr(self, "_filterGeneration", 0) + 1
  for timer_attr in ("_logFilterAfterId", "_logFilterChunkAfterId"):
   tid = getattr(self, timer_attr, None)
   if tid is not None:
    try:
     self.after_cancel(tid)
    except Exception:
     pass
    setattr(self, timer_attr, None)
  self.logBuffers = {False: "", True: ""}
  self.rawLogEntries = []
  self.omittedLogCount = 0
  self._pendingFilterAppends = []
  self._pendingFilterEvictions = 0
  self._sliceLogBatch = []
  self._sliceLogEvictedCount = 0
  if hasattr(self, "_updateOmissionNotice"):
   self._updateOmissionNotice()
  self.logText.text.configure(state=NORMAL)
  self.logText.text.delete("1.0", END)
  self.logText.text.configure(state=DISABLED)

 def redirectStreams(self):
  self._origStreams = (sys.stdout, sys.stderr)
  for stream in ["stdout", "stderr"]:
   is_err = (stream == "stderr")
   def make_cb(err=is_err):
    def _cb(text):
     gen = getattr(self, "_logGeneration", 0)
     self.run(lambda t=text, e=err, g=gen: self.log(t, e) if getattr(self, "_logGeneration", 0) == g else None)
    return _cb
   setattr(sys, stream, PrintRedirector(make_cb(), getattr(sys, stream)))


class InfoFrame(UiFrame):
 def __init__(self, parent, **kwargs):
  UiFrame.__init__(self, parent, **kwargs)

  # Title & Status at TOP
  header = Frame(self)
  header.pack(side=TOP, fill=X, pady=(0, 4))
  Label(header, text="Camera Overview & Diagnostics", style="Section.TLabel").pack(anchor=W)
  self.infoStatus = StringVar(value="Connect a Sony camera in MTP mode to read properties." if not parent.cameraActionsEnabled else "Ready to read camera information.")
  Label(header, textvariable=self.infoStatus, style="Detail.TLabel").pack(anchor=W, pady=(2, 0))

  self.infoVars = {
   "Model": StringVar(value="—"),
   "Vendor": StringVar(value="—"),
   "App Support": StringVar(value="—"),
   "App support": StringVar(value="—"),
   "USB mode": StringVar(value="—"),
   "Product code": StringVar(value="—"),
   "Serial number": StringVar(value="—"),
   "Firmware version": StringVar(value="—"),
   "Lens": StringVar(value="—"),
   "Shutter count": StringVar(value="—"),
   "Shutter note": StringVar(value="—"),
   "PTP Capabilities": StringVar(value="—"),
   "macOS subsystem": StringVar(value="—"),
   "PTP version": StringVar(value="—"),
   "PTP descriptor": StringVar(value="—"),
  }
  self.cameraSnapshot = {}

  # Controls pinned at BOTTOM!
  btnBox = Frame(self)
  btnBox.pack(side=BOTTOM, fill=X, pady=(4, 0))
  self.infoButton = Button(btnBox, text="Get camera info", command=InfoTask(self).run, padding=(10, 3))
  self.infoButton.pack(side=LEFT, padx=(0, 8))
  if hasattr(self.master, "reconnectCamera"):
   Button(btnBox, text="Reconnect Camera", command=self.master.reconnectCamera, padding=(8, 3)).pack(side=LEFT)

  guideText = "MTP Checklist: Camera Menu → Setup → USB Connection → set to MTP. Close Photos/Image Capture before connecting."
  self.guideLabel = Label(self, text=guideText, style="Detail.TLabel", wraplength=680)
  self.guideLabel.pack(side=BOTTOM, fill=X, pady=(2, 2))
  Separator(self, orient=HORIZONTAL).pack(side=BOTTOM, fill=X, pady=(4, 4))

  def _onInfoFrameConfigure(event):
   w = max(400, event.width - 32)
   if hasattr(self, "guideLabel"):
    try:
     self.guideLabel.config(wraplength=w)
    except Exception:
     pass

  self.bind("<Configure>", _onInfoFrameConfigure)

  # Cards container in the middle
  cardsContainer = Frame(self)
  cardsContainer.pack(side=TOP, fill=BOTH, expand=True)
  cardsContainer.columnconfigure(0, weight=1)
  cardsContainer.columnconfigure(1, weight=1)

  # Left Column Card: Camera Identity & Hardware
  leftCard = Labelframe(cardsContainer, text="Camera Identity", padding=(10, 4))
  leftCard.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 2))
  leftCard.columnconfigure(1, weight=1)

  idFields = [
   ("Model:", "Model"),
   ("Vendor:", "Vendor"),
   ("App Support:", "App Support"),
   ("Body Serial:", "Serial number"),
   ("Product Code:", "Product code"),
   ("Camera Firmware:", "Firmware version"),
   ("Lens Attached:", "Lens"),
  ]
  self.leftLabels = []
  for r, (lbl, key) in enumerate(idFields):
   Label(leftCard, text=lbl, style="Detail.TLabel").grid(row=r, column=0, sticky=W, padx=(0, 8), pady=1)
   v_lbl = Label(leftCard, textvariable=self.infoVars[key], wraplength=170)
   v_lbl.grid(row=r, column=1, sticky=W, pady=1)
   self.leftLabels.append(v_lbl)

  # Right Container: Connection + Diagnostics
  rightBox = Frame(cardsContainer)
  rightBox.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=(0, 2))
  rightBox.columnconfigure(0, weight=1)

  connCard = Labelframe(rightBox, text="Connection & Transport", padding=(10, 4))
  connCard.pack(fill=X, pady=(0, 4))
  connCard.columnconfigure(1, weight=1)

  connFields = [
   ("USB Mode:", "USB mode"),
   ("PTP Version:", "PTP version"),
   ("Capabilities:", "PTP Capabilities"),
   ("Subsystem:", "macOS subsystem"),
   ("PTP Descriptor:", "PTP descriptor"),
  ]
  self.connLabels = []
  for r, (lbl, key) in enumerate(connFields):
   Label(connCard, text=lbl, style="Detail.TLabel").grid(row=r, column=0, sticky=W, padx=(0, 8), pady=1)
   v_lbl = Label(connCard, textvariable=self.infoVars[key], wraplength=170)
   v_lbl.grid(row=r, column=1, sticky=W, pady=1)
   self.connLabels.append(v_lbl)

  diagCard = Labelframe(rightBox, text="Diagnostics & Actuations", padding=(10, 4))
  diagCard.pack(fill=X)
  diagCard.columnconfigure(1, weight=1)

  Label(diagCard, text="Shutter Count:", style="Detail.TLabel").grid(row=0, column=0, sticky=W, padx=(0, 8), pady=1)
  self.shutterCountLabel = Label(diagCard, textvariable=self.infoVars["Shutter count"], wraplength=170)
  self.shutterCountLabel.grid(row=0, column=1, sticky=W, pady=1)
  Label(diagCard, text="Actuation Note:", style="Detail.TLabel").grid(row=1, column=0, sticky=W, padx=(0, 8), pady=1)
  self.shutterNoteLabel = Label(diagCard, textvariable=self.infoVars["Shutter note"], style="Detail.TLabel", wraplength=170)
  self.shutterNoteLabel.grid(row=1, column=1, sticky=W, pady=1)

  def _onLeftCardConfigure(event):
   w = max(170, event.width - 165)
   for lbl in getattr(self, "leftLabels", []):
    try:
     lbl.config(wraplength=w)
    except Exception:
     pass

  leftCard.bind("<Configure>", _onLeftCardConfigure)

  def _onRightBoxConfigure(event):
   w = max(170, event.width - 155)
   for lbl in getattr(self, "connLabels", []):
    try:
     lbl.config(wraplength=w)
    except Exception:
     pass
   if hasattr(self, "shutterCountLabel"):
    try:
     self.shutterCountLabel.config(wraplength=w)
    except Exception:
     pass
   if hasattr(self, "shutterNoteLabel"):
    try:
     self.shutterNoteLabel.config(wraplength=w)
    except Exception:
     pass

  rightBox.bind("<Configure>", _onRightBoxConfigure)

 def _updateInfoVars(self):
  for key, var in self.infoVars.items():
   val = getattr(self, "cameraSnapshot", {}).get(key)
   var.set(str(val) if val is not None and val != "" else "—")

 def showConnectedCamera(self, info):
  if not hasattr(self, "cameraSnapshot"):
   self.cameraSnapshot = {}
  if info and (info.get("appConnected") or info.get("physicalDetected")):
   model = info.get("name") or info.get("model")
   current_model = self.cameraSnapshot.get("Model")
   sn = info.get("serial")
   current_sn = self.cameraSnapshot.get("Serial number")
   raw_desc = info.get("raw_serial") or (info.get("serialNumber") if str(info.get("serialNumber", "")).startswith("0000000000000000") else (info.get("serial") if str(info.get("serial", "")).startswith("0000000000000000") else None))
   current_raw = self.cameraSnapshot.get("PTP descriptor")

   # Detect device identity change: different model, different body serial, or different PTP descriptor
   identity_changed = False
   if current_model and model and current_model != "—" and current_model != model:
    identity_changed = True
   if current_sn and sn and current_sn not in ("—", "Unavailable without query") and not str(sn).startswith("0000000000000000") and current_sn != str(sn):
    identity_changed = True
   if current_raw and raw_desc and current_raw != "—" and current_raw != raw_desc:
    identity_changed = True
   if current_sn and current_sn not in ("—", "Unavailable without query") and raw_desc and not raw_desc.endswith(current_sn) and current_sn not in raw_desc:
    identity_changed = True
   if current_raw and current_raw != "—" and sn and not str(sn).startswith("0000000000000000") and sn not in current_raw:
    identity_changed = True

   if identity_changed:
    self.cameraSnapshot.clear()

   if not info.get("appConnected"):
    for stale_key in ["Firmware version", "Lens", "Shutter count", "Shutter note", "Product code", "PTP Capabilities"]:
     self.cameraSnapshot.pop(stale_key, None)

   if model:
    self.cameraSnapshot["Model"] = model
   if info.get("vendor"):
    self.cameraSnapshot["Vendor"] = str(info.get("vendor"))
   elif "Vendor" not in self.cameraSnapshot:
    self.cameraSnapshot["Vendor"] = "Sony (0x054c)"

   # Determine App Support string
   app_support_text = "—"
   if info.get("mode") == "App installation":
    app_support_text = "Supported (Installer active)"
   else:
    cs = info.get("camera_support")
    if not cs and model:
     try:
      from pmca.compatibility import get_camera_support
      cs = get_camera_support(model)
     except Exception:
      pass

    if cs and isinstance(cs, dict):
     pmca_apps = cs.get("pmca_apps")
     tested = cs.get("installation_tested")
     if pmca_apps is True:
      if tested:
       app_support_text = "Supported (Verified on ILCE-7)"
      else:
       app_support_text = "Supported (PMCA reference model)"
     elif pmca_apps is False:
      app_support_text = "Not supported (No PMCA subsystem)"
     else:
      app_support_text = "Unconfirmed model"
    elif "app_installation_supported" in info:
     if info["app_installation_supported"] is True:
      app_support_text = "Supported"
     elif info["app_installation_supported"] is False:
      app_support_text = "Not supported"

   self.cameraSnapshot["App Support"] = app_support_text
   self.cameraSnapshot["App support"] = app_support_text

   if info.get("mode"):
    self.cameraSnapshot["USB mode"] = info["mode"]
   elif "USB mode" not in self.cameraSnapshot:
    self.cameraSnapshot["USB mode"] = "MTP"

   raw_desc = info.get("raw_serial") or (info.get("serialNumber") if str(info.get("serialNumber", "")).startswith("0000000000000000") else (info.get("serial") if str(info.get("serial", "")).startswith("0000000000000000") else None))
   if raw_desc:
    self.cameraSnapshot["PTP descriptor"] = raw_desc
   elif "PTP descriptor" not in self.cameraSnapshot:
    self.cameraSnapshot["PTP descriptor"] = "—"

   sn = info.get("serial")
   if sn and not str(sn).startswith("0000000000000000"):
    self.cameraSnapshot["Serial number"] = str(sn)
   elif "Serial number" not in self.cameraSnapshot or self.cameraSnapshot["Serial number"] == "—":
    self.cameraSnapshot["Serial number"] = "Unavailable without query"

   pc = info.get("product_code") or info.get("modelCode")
   if pc:
    self.cameraSnapshot["Product code"] = pc

   if info.get("ptp_device_version"):
    self.cameraSnapshot["PTP version"] = "PTP v%s" % info["ptp_device_version"]
   elif "PTP version" not in self.cameraSnapshot:
    self.cameraSnapshot["PTP version"] = "—"

   fw = info.get("firmware_version")
   if fw and not fw.startswith("Unavailable") and not fw.startswith("PTP"):
    self.cameraSnapshot["Firmware version"] = fw
   elif "Firmware version" not in self.cameraSnapshot or self.cameraSnapshot["Firmware version"] == "—":
    self.cameraSnapshot["Firmware version"] = fw or "Unavailable without query" 

   lens = info.get("lens")
   if lens:
    self.cameraSnapshot["Lens"] = lens

   subsystem = info.get("macOS_subsystem") or ("IOUSBHostDevice (ptpcamerad managed)" if sys.platform == "darwin" else "libusb")
   self.cameraSnapshot["macOS subsystem"] = subsystem

   if "shutter_count" in info:
    sc = info.get("shutter_count")
    if isinstance(sc, dict):
     if sc.get("available") and sc.get("value") is not None:
      val = sc["value"]
      try:
       val_str = "{:,} actuations".format(int(val))
      except Exception:
       val_str = "%s actuations" % val
      if sc.get("ambiguous"):
       val_str += " (modulo 65,536)"
      self.cameraSnapshot["Shutter count"] = val_str
      provenance_parts = []
      if sc.get("provenance"):
       provenance_parts.append(sc["provenance"])
      elif sc.get("source"):
       provenance_parts.append(sc["source"])
      if sc.get("date"):
       provenance_parts.append("captured %s" % sc["date"])
      elif sc.get("captured_at"):
       provenance_parts.append("as of %s" % sc["captured_at"])
      if sc.get("warning"):
       provenance_parts.append(sc["warning"])
      self.cameraSnapshot["Shutter note"] = " • ".join(provenance_parts) if provenance_parts else "Decoded via Sony MakerNote Tag 0x9050"
     elif sc.get("status") == "pending":
      self.cameraSnapshot["Shutter count"] = "Decoding (pending photo)…"
      self.cameraSnapshot["Shutter note"] = sc.get("reason") or "Reading MakerNote metadata from sample photo…"
     elif sc.get("reason"):
      reason_text = sc["reason"]
      if "App installation" in reason_text:
       self.cameraSnapshot["Shutter count"] = "Unavailable in App Install mode"
      elif "No captured image" in reason_text or "no photo" in reason_text.lower():
       self.cameraSnapshot["Shutter count"] = "No photo on SD card"
      elif any(term in reason_text.lower() for term in ["unsupported", "not supported", "not implemented"]):
       self.cameraSnapshot["Shutter count"] = "Unsupported on this model"
      elif any(term in reason_text.lower() for term in ["unconfirmed", "unknown"]):
       self.cameraSnapshot["Shutter count"] = "Unconfirmed for this model"
      elif "query camera info" in reason_text.lower():
       self.cameraSnapshot["Shutter count"] = "Query camera info to inspect"
      else:
       self.cameraSnapshot["Shutter count"] = "Unavailable (not exposed over MTP)"
      self.cameraSnapshot["Shutter note"] = reason_text
     else:
      self.cameraSnapshot["Shutter count"] = "—"
      self.cameraSnapshot["Shutter note"] = "—"
    elif isinstance(sc, (int, str)) and sc != "" and sc != "—":
     try:
      self.cameraSnapshot["Shutter count"] = "{:,} actuations".format(int(sc))
     except Exception:
      self.cameraSnapshot["Shutter count"] = "%s actuations" % sc
     self.cameraSnapshot["Shutter note"] = "Decoded via Sony MakerNote"

   if "capabilities" in info or "properties" in info:
    caps = info.get("capabilities", [])
    props = info.get("properties", [])
    if caps or props:
     self.cameraSnapshot["PTP Capabilities"] = "%d operations, %d properties supported" % (len(caps), len(props))

   for key, var in self.infoVars.items():
    val = getattr(self, "cameraSnapshot", {}).get(key)
    var.set(str(val) if val is not None and val != "" else "—")

   model_str = getattr(self, "cameraSnapshot", {}).get("Model") or info.get("name", "Camera")
   mode_str = getattr(self, "cameraSnapshot", {}).get("USB mode") or info.get("mode", "MTP")
   if info.get("appConnected"):
    if hasattr(self, "infoStatus"):
     self.infoStatus.set("Camera connected: %s via %s (Ready)." % (model_str, mode_str))
   else:
    reason = info.get("failure_reason") or "MTP application connection unavailable."
    if hasattr(self, "infoStatus"):
     self.infoStatus.set("USB device detected: %s (%s)" % (model_str, reason))
  else:
   if hasattr(self, "cameraSnapshot"):
    self.cameraSnapshot.clear()
   for key, var in self.infoVars.items():
    var.set("—")
   if hasattr(self, "infoStatus"):
    self.infoStatus.set("No camera connected. Connect camera in MTP mode.")

 def showPassiveUsb(self, dev):
  if not hasattr(self, "cameraSnapshot"):
   self.cameraSnapshot = {}
  self.cameraSnapshot.clear()
  if dev:
   self.cameraSnapshot["Model"] = dev.get("name") or "Sony Camera"
   self.cameraSnapshot["Vendor"] = dev.get("vendor") or "Sony (0x054c)"
   self.cameraSnapshot["USB mode"] = dev.get("mode") or "MTP / PTP"
   if dev.get("serial"):
    self.cameraSnapshot["Serial number"] = dev["serial"]
   self.cameraSnapshot["macOS subsystem"] = "IOUSBHostDevice (ptpcamerad managed)"
   for key, var in self.infoVars.items():
    val = getattr(self, "cameraSnapshot", {}).get(key)
    var.set(str(val) if val is not None and val != "" else "—")
   if hasattr(self, "infoStatus"):
    self.infoStatus.set("macOS detects %s via USB. Note: Full camera session requires native camera transport." % dev.get("name", "Sony Camera"))
  else:
   for key, var in self.infoVars.items():
    var.set("—")
   if hasattr(self, "infoStatus"):
    self.infoStatus.set("No Sony camera detected on USB bus.")

 def showCameraInfo(self, data):
  if not hasattr(self, "cameraSnapshot"):
   self.cameraSnapshot = {}
  if not data:
   self.cameraSnapshot.clear()
   for key, var in self.infoVars.items():
    var.set("—")
   if hasattr(self, "infoStatus"):
    self.infoStatus.set("Could not read camera information. Check Activity for details.")
   return
  for key, val in data.items():
   if val is not None and val != "":
    if key == "Serial number":
     val_sn = str(val)
     if not val_sn.startswith("0000000000000000"):
      self.cameraSnapshot["Serial number"] = val_sn
     else:
      self.cameraSnapshot["PTP descriptor"] = val_sn
    elif key == "Firmware version":
     cur_fw = self.cameraSnapshot.get("Firmware version")
     if not str(val).startswith("Unavailable") or not cur_fw or cur_fw == "—":
      self.cameraSnapshot["Firmware version"] = str(val)
    elif key == "Shutter count":
     val_sc = str(val)
     if any(term in val_sc.lower() for term in ["unsupported", "not supported", "not implemented"]):
      self.cameraSnapshot["Shutter count"] = "Unsupported on this model"
      self.cameraSnapshot["Shutter note"] = val_sc
     elif any(term in val_sc.lower() for term in ["unconfirmed", "unknown"]):
      self.cameraSnapshot["Shutter count"] = "Unconfirmed for this model"
      self.cameraSnapshot["Shutter note"] = val_sc
     elif len(val_sc) > 40 or "not exposed" in val_sc.lower() or "service-mode" in val_sc.lower():
      self.cameraSnapshot["Shutter count"] = "Unavailable (not exposed over MTP)"
      self.cameraSnapshot["Shutter note"] = val_sc
     else:
      self.cameraSnapshot["Shutter count"] = val_sc
    else:
     self.cameraSnapshot[key] = str(val)
    if key.lower() == "app support":
     self.cameraSnapshot["App Support"] = str(val)
     self.cameraSnapshot["App support"] = str(val)
  for key, var in self.infoVars.items():
   val = getattr(self, "cameraSnapshot", {}).get(key)
   var.set(str(val) if val is not None and val != "" else "—")
  if hasattr(self, "infoStatus"):
   self.infoStatus.set("Camera information received." if data.get("Model") else "Could not read camera information. Check Activity for details.")


class InstallerFrame(UiFrame):
 MODE_APP = 0
 MODE_APK = 1

 def __init__(self, parent, **kwargs):
  UiFrame.__init__(self, parent, **kwargs)
  self.modeVar = IntVar(value=self.MODE_APK)
  self.appList = []
  self.filteredApps = []
  self.catalog = loadCatalog()
  self.cardDownloadButtons = []
  self._pendingScrollUnits = 0
  self._scrollTimerId = None
  self._activeTaskGen = 0
  self.downloadAbortEvent = None
  self._progressIndeterminateActive = False
  self._renderedCards = {}
  self._renderedCardKeys = []
  self._focusedStorePkg = None
  self._lastCanvasWidth = None

  # Progress Section - pinned to bottom
  progressSection = Frame(self)
  progressSection.pack(side=BOTTOM, fill=X, pady=(4, 0))
  progressTop = Frame(progressSection)
  progressTop.pack(fill=X, pady=(0, 2))
  self.progressText = StringVar(value="No operation running.")
  Label(progressTop, textvariable=self.progressText, style="Detail.TLabel").pack(side=LEFT, anchor=W)
  self.cancelDownloadButton = Button(progressTop, text="Cancel Download", command=self.cancelDownload, padding=(6, 1), state=DISABLED)
  self.cancelDownloadButton.pack(side=RIGHT)
  self.progressBar = Progressbar(progressSection, mode="determinate", maximum=100)
  self.progressBar.pack(fill=X)

  # ====================================================
  # Upper Area (~20%, 118px): Compact Local APK Staging Bar
  # ====================================================
  self.apkPanel = Labelframe(self, text="Local APK Staging & Installation", padding=(10, 6))
  self.apkPanel.pack(side=TOP, fill=X, pady=(0, 6))

  apkSelectRow = Frame(self.apkPanel)
  apkSelectRow.pack(fill=X, pady=(0, 4))
  self.apkFile = Entry(apkSelectRow, state="readonly")
  self.apkFile.pack(side=LEFT, fill=X, expand=True, padx=(0, 6))
  self.apkSelectButton = Button(apkSelectRow, text="Browse APK…", command=self.openApk)
  self.apkSelectButton.pack(side=LEFT, padx=(0, 4))
  self.apkRevealButton = Button(apkSelectRow, text="Reveal…", command=self.revealApk, state=DISABLED)
  self.apkRevealButton.pack(side=LEFT, padx=(0, 6))
  self.installButton = Button(apkSelectRow, text="Install APK to Camera", command=InstallTask(self).run, padding=(10, 3), state=DISABLED)
  self.installButton.pack(side=RIGHT)

  self.apkSummary = StringVar(value="No APK selected. Choose a local file above or click Download APK on any app below.")
  self.apkSummaryLabel = Label(self.apkPanel, textvariable=self.apkSummary, wraplength=700, justify=LEFT)
  self.apkSummaryLabel.pack(anchor=W, pady=(0, 2))
  self.apkStatusNote = StringVar(value="Camera not connected. Connect camera in MTP mode to enable install." if not parent.cameraActionsEnabled else "Camera connected: Ready to install.")
  self.apkStatusLabel = Label(self.apkPanel, textvariable=self.apkStatusNote, style="Detail.TLabel", wraplength=700)
  self.apkStatusLabel.pack(anchor=W)

  # ====================================================
  # Lower Area (~80%, ~548px): Application Store Vertical Wide List
  # ====================================================
  self.catalogPanel = Labelframe(self, text="Application Store", padding=(10, 6))
  self.catalogPanel.pack(side=TOP, fill=BOTH, expand=True, pady=(0, 4))

  storeTop = Frame(self.catalogPanel)
  storeTop.pack(fill=X, pady=(0, 4))
  self.searchVar = StringVar(value="")
  self.storeStatusVar = StringVar(value="%d catalog apps loaded (cached)" % len(self.catalog))
  Label(storeTop, textvariable=self.storeStatusVar, style="Detail.TLabel").pack(side=LEFT, padx=(4, 0))
  self.appLoadButton = Button(storeTop, text="Check Updates", command=self.refreshCatalog, padding=(6, 2))
  self.appLoadButton.pack(side=RIGHT)

  # Scrollable List Container
  canvasContainer = Frame(self.catalogPanel)
  canvasContainer.pack(fill=BOTH, expand=True)

  self.canvas = Canvas(canvasContainer, borderwidth=0, highlightthickness=0, yscrollincrement=1)
  self.scrollbar = Scrollbar(canvasContainer, orient=VERTICAL, command=self.canvas.yview)
  self.cardsFrame = Frame(self.canvas)

  self.cardsFrame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
  self.canvasWindow = self.canvas.create_window((0, 0), window=self.cardsFrame, anchor="nw")
  self.canvas.configure(yscrollcommand=self.scrollbar.set)
  self.canvas.bind("<Configure>", self._onCanvasConfigure)
  self._tagStoreScrollable(canvasContainer)
  self._tagStoreScrollable(self.canvas)
  self._tagStoreScrollable(self.cardsFrame)

  self.canvas.pack(side=LEFT, fill=BOTH, expand=True)
  self.scrollbar.pack(side=RIGHT, fill=Y)

  # Compatibility widgets for test suite
  self.appCombo = Combobox(self, state="readonly")
  self.appDownloadButton = Button(self, text="Download App APK…", command=CatalogAppDownloadTask(self).run, state=DISABLED)
  self.downloadButton = Button(self, text="Download RecipeLab…", command=RecipeDownloadTask(self).run)
  self.appDetailVar = StringVar(value="")

  self.renderAppCards()
  self.setAppList([])
  self.startBackgroundSync()

 def _nextTaskGeneration(self):
  self._activeTaskGen = getattr(self, "_activeTaskGen", 0) + 1
  return self._activeTaskGen

 def cancelDownload(self):
  abort_ev = getattr(self, "downloadAbortEvent", None)
  if abort_ev is not None:
   abort_ev.set()

 def _tagStoreScrollable(self, widget):
  try:
   tags = list(widget.bindtags())
   if "StoreScrollable" not in tags:
    widget.bindtags(("StoreScrollable",) + tuple(tags))
   for child in widget.winfo_children():
    self._tagStoreScrollable(child)
  except Exception:
   pass

 def _queueScrollUnits(self, units):
  if not hasattr(self, "canvas") or not self.canvas.winfo_ismapped() or units == 0:
   return

  # 1. Edge clamp: if already at top and scrolling up, or at bottom and scrolling down, don't accumulate dead delta
  try:
   y_top, y_bottom = self.canvas.yview()
   if y_top <= 0.0 and units < 0:
    if self._pendingScrollUnits < 0:
     self._pendingScrollUnits = 0
    return
   if y_bottom >= 1.0 and units > 0:
    if self._pendingScrollUnits > 0:
     self._pendingScrollUnits = 0
    return
  except Exception:
   pass

  # 2. Direction reversal: if user abruptly reverses direction, flush previous momentum immediately
  if (self._pendingScrollUnits > 0 and units < 0) or (self._pendingScrollUnits < 0 and units > 0):
   self._flushPendingScroll()

  self._pendingScrollUnits += units

  # 3. Frame-paced flush: schedule single redraw at idle (coalesced 60 FPS pace)
  if self._scrollTimerId is None:
   try:
    self._scrollTimerId = self.after_idle(self._flushPendingScroll)
   except Exception:
    self._flushPendingScroll()

 def _flushPendingScroll(self):
  if getattr(self, "_scrollTimerId", None) is not None:
   try:
    self.after_cancel(self._scrollTimerId)
   except Exception:
    pass
   self._scrollTimerId = None

  units = getattr(self, "_pendingScrollUnits", 0)
  self._pendingScrollUnits = 0
  if units != 0 and hasattr(self, "canvas") and self.canvas.winfo_ismapped():
   try:
    self.canvas.yview_scroll(units, "units")
   except Exception:
    pass

 def destroy(self):
  if getattr(self, "_scrollTimerId", None) is not None:
   try:
    self.after_cancel(self._scrollTimerId)
   except Exception:
    pass
   self._scrollTimerId = None
  UiFrame.destroy(self)

 def _onMouseWheel(self, event):
  if hasattr(self.master, "_onMouseWheel"):
   return self.master._onMouseWheel(event)
  if not self.canvas.winfo_ismapped():
   return "break"
  raw = getattr(event, "delta", 0)
  if raw != 0:
   if abs(raw) >= 120:
    units = -1 * round((raw / 120.0) * 60)
   else:
    units = -1 * round(raw * 60)
   if units == 0:
    units = -1 if raw > 0 else 1
   self.canvas.yview_scroll(units, "units")
  return "break"

 def _onCanvasConfigure(self, event):
  if getattr(self, "_lastCanvasWidth", None) == event.width:
   return
  self._lastCanvasWidth = event.width
  self.canvas.itemconfig(self.canvasWindow, width=event.width)
  wrap = max(300, event.width - 250)
  for lbl in getattr(self, "cardTextLabels", None) or getattr(self, "descLabels", []):
   try:
    lbl.config(wraplength=wrap)
   except Exception:
    pass

 def _ensureRowVisible(self, row):
  if not hasattr(self, "canvas") or not self.canvas.winfo_ismapped():
   return
  try:
   self.cardsFrame.update_idletasks()
   bbox = self.canvas.bbox("all")
   total_h = (bbox[3] - bbox[1]) if bbox else self.cardsFrame.winfo_reqheight()
   canvas_h = self.canvas.winfo_height()
   if total_h <= 0 or canvas_h <= 1 or total_h <= canvas_h:
    return
   row_top = row.winfo_y()
   row_h = max(row.winfo_height(), row.winfo_reqheight(), 48)
   row_bottom = row_top + row_h
   y_top, y_bottom = self.canvas.yview()
   vis_top = y_top * total_h
   vis_bottom = y_top * total_h + canvas_h
   if row_top < vis_top:
    self.canvas.yview_moveto(max(0.0, float(row_top) / float(total_h)))
   elif row_bottom > vis_bottom:
    target_top = max(0.0, float(row_bottom - canvas_h + 12))
    self.canvas.yview_moveto(min(1.0, target_top / float(total_h)))
  except Exception:
   pass

 def _onCardWidgetFocusIn(self, row, pkg):
  self._focusedStorePkg = pkg
  self._ensureRowVisible(row)

 def renderAppCards(self, filterQuery=None):
  q = (filterQuery or "").strip().lower()
  visible_items = []
  for pkg, app in self.catalog.items():
   name = app.get("name", "")
   author = app.get("author", "")
   desc = app.get("desc", "")
   actual_pkg = app.get("package") or pkg
   if q and q not in name.lower() and q not in pkg.lower() and q not in desc.lower() and q not in author.lower() and q not in actual_pkg.lower():
    continue
   visible_items.append((pkg, app))

  visible_keys = [pkg for pkg, _ in visible_items]
  any_busy = bool(getattr(self.master, "cameraBusy", False) or getattr(self.master, "downloadBusy", False))

  # Fast path: update existing card widgets in place when visible package keys match
  rendered_cards = getattr(self, "_renderedCards", None)
  if rendered_cards and getattr(self, "_renderedCardKeys", None) == visible_keys:
   all_alive = True
   for pkg in visible_keys:
    entry = rendered_cards.get(pkg)
    if not entry or not entry["row"].winfo_exists():
     all_alive = False
     break
   if all_alive:
    for pkg, app in visible_items:
     entry = rendered_cards[pkg]
     name = app.get("name", "")
     author = app.get("author", "")
     desc = app.get("desc", "")
     ver = app.get("version")
     ver_display = ver if (ver and ver != "Release pending") else "Version unverified"
     actual_pkg = app.get("package") or pkg
     caveat = app.get("support_caveats") or app.get("compatibility")
     title_text = "%s  (%s)" % (name, ver_display)
     meta_text = "by %s  •  %s" % (author, actual_pkg)
     if caveat:
      meta_text += "  •  %s" % caveat
     if entry["titleLabel"].cget("text") != title_text:
      entry["titleLabel"].config(text=title_text)
     if entry["metaLabel"].cget("text") != meta_text:
      entry["metaLabel"].config(text=meta_text)
     if entry["descLabel"].cget("text") != desc:
      entry["descLabel"].config(text=desc)
     btn = entry["btn"]
     pkg_cmd = RecipeDownloadTask(self).run if pkg == "com.voxivoid.recipelab" else (lambda p=pkg: self.downloadStoreApp(p))
     if not app.get("url"):
      btn.config(text="No APK", command=pkg_cmd, state=DISABLED)
     else:
      btn.config(text="Download APK", command=pkg_cmd, state=DISABLED if any_busy else NORMAL)
    if not hasattr(self, "_lastSyncResult"):
     self.storeStatusVar.set("%d catalog apps available" % len(self.catalog))
    return

  prev_y = None
  if getattr(self, "_renderedCardKeys", None) and hasattr(self, "canvas"):
   try:
    prev_y = self.canvas.yview()[0]
   except Exception:
    prev_y = None
  focused_pkg = getattr(self, "_focusedStorePkg", None)

  self.cardDownloadButtons = []
  self.descLabels = []
  self.cardTextLabels = []
  self._renderedCards = {}
  self._renderedCardKeys = visible_keys
  for w in self.cardsFrame.winfo_children():
   w.destroy()
  self.cardsFrame.columnconfigure(0, weight=1)
  canvas_w = self.canvas.winfo_width() if hasattr(self, "canvas") and self.canvas.winfo_width() > 100 else 800
  wrap_width = max(300, canvas_w - 250)
  for pkg, app in visible_items:
   name = app.get("name", "")
   author = app.get("author", "")
   desc = app.get("desc", "")
   ver = app.get("version")
   ver_display = ver if (ver and ver != "Release pending") else "Version unverified"
   actual_pkg = app.get("package") or pkg
   caveat = app.get("support_caveats") or app.get("compatibility")
   row = Frame(self.cardsFrame, padding=(10, 6))
   row.pack(fill=X, pady=2, padx=4)
   row.columnconfigure(0, weight=1)
   row.columnconfigure(1, weight=0, minsize=220)

   textBox = Frame(row)
   textBox.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

   # Line 1: Name and Version
   titleLabel = Label(textBox, text="%s  (%s)" % (name, ver_display), style="Subheading.TLabel", wraplength=wrap_width)
   titleLabel.pack(anchor=W)

   # Line 2: Author, Package, and Compatibility Note
   meta_text = "by %s  •  %s" % (author, actual_pkg)
   if caveat:
    meta_text += "  •  %s" % caveat
   metaLabel = Label(textBox, text=meta_text, style="Detail.TLabel", wraplength=wrap_width)
   metaLabel.pack(anchor=W, pady=(1, 2))

   # Line 3: Description
   descLabel = Label(textBox, text=desc, style="Detail.TLabel", wraplength=wrap_width)
   descLabel.pack(anchor=W)
   self.descLabels.append(descLabel)
   self.cardTextLabels.extend((titleLabel, metaLabel, descLabel))

   # Column 1: Action group docked on the right
   actionBox = Frame(row)
   actionBox.grid(row=0, column=1, sticky="e")
   pkg_cmd = RecipeDownloadTask(self).run if pkg == "com.voxivoid.recipelab" else (lambda p=pkg: self.downloadStoreApp(p))
   if not app.get("url"):
    btn = Button(actionBox, text="No APK", command=pkg_cmd, state=DISABLED, padding=(8, 3))
   else:
    btn = Button(actionBox, text="Download APK", command=pkg_cmd, state=DISABLED if any_busy else NORMAL, padding=(8, 3))
   btn.pack(side=LEFT, padx=(0, 6))
   btn.bind("<FocusIn>", lambda e, r=row, p=pkg: self._onCardWidgetFocusIn(r, p), add="+")
   self.cardDownloadButtons.append(btn)
   homepage = app.get("homepage")
   if homepage:
    srcBtn = Button(actionBox, text="Source ↗", command=lambda u=homepage: webbrowser.open_new(u), padding=(6, 3))
    srcBtn.pack(side=LEFT)
    srcBtn.bind("<FocusIn>", lambda e, r=row, p=pkg: self._onCardWidgetFocusIn(r, p), add="+")
   Separator(self.cardsFrame, orient=HORIZONTAL).pack(fill=X, padx=4, pady=1)
   self._tagStoreScrollable(row)
   self._renderedCards[pkg] = {
    "row": row,
    "titleLabel": titleLabel,
    "metaLabel": metaLabel,
    "descLabel": descLabel,
    "btn": btn,
   }
  spacer = Frame(self.cardsFrame, height=20)
  spacer.pack(fill=X)
  self._tagStoreScrollable(spacer)
  self.cardsFrame.update_idletasks()
  self.canvas.configure(scrollregion=self.canvas.bbox("all"))
  if prev_y is not None:
   try:
    self.canvas.yview_moveto(prev_y)
   except Exception:
    pass
  if focused_pkg and focused_pkg in self._renderedCards:
   try:
    self._renderedCards[focused_pkg]["btn"].focus_set()
   except Exception:
    pass
  if not hasattr(self, "_lastSyncResult"):
   self.storeStatusVar.set("%d catalog apps available" % len(self.catalog))
  if any_busy:
   self.setStoreBusy(True)

 def _bindMouseWheel(self, widget):
  try:
   widget.bind("<MouseWheel>", self._onMouseWheel, add="+")
   widget.bind("<Button-4>", self._onMouseWheel, add="+")
   widget.bind("<Button-5>", self._onMouseWheel, add="+")
   for child in widget.winfo_children():
    self._bindMouseWheel(child)
  except Exception:
   pass

 def setStoreBusy(self, busy):
  state = DISABLED if busy else NORMAL
  for btn in getattr(self, "cardDownloadButtons", []):
   try:
    if str(btn.cget("text")) == "No APK":
     btn.config(state=DISABLED)
    else:
     btn.config(state=state)
   except Exception:
    pass

 def filterAppCards(self):
  query = self.searchVar.get() if hasattr(self, "searchVar") else ""
  self.renderAppCards(query)
  self.filterAppList()

 def refreshCatalog(self):
  self.appLoadButton.config(state=DISABLED)
  self.storeStatusVar.set("Checking for updates…")
  threading.Thread(target=self._syncWorker, daemon=True).start()

 def _runSafely(self, func):
  self.run(func)

 def _syncWorker(self):
  abort_event = getattr(self.master, "abortSync", None)
  try:
   res = syncCatalogMetadata(self.catalog, abort_event=abort_event)
   newCat = res[0] if isinstance(res, tuple) else res
   if abort_event and abort_event.is_set():
    return
   saveCatalog(res if hasattr(res, "catalog") else newCat)
   self.catalog = newCat
   self._runSafely(lambda: self.onCatalogSynced(res))
  except Exception:
   self._runSafely(lambda: self.onCatalogSynced(False))

 def onCatalogSynced(self, res):
  self._lastSyncResult = res
  any_busy = bool(getattr(self.master, "cameraBusy", False) or getattr(self.master, "downloadBusy", False))
  if not any_busy:
   self.appLoadButton.config(state=NORMAL)
  else:
   self.appLoadButton.config(state=DISABLED)
  self.renderAppCards(self.searchVar.get() if hasattr(self, "searchVar") else "")
  if hasattr(res, "success"):
   if res.success:
    updated = getattr(res, "updated_count", 0)
    if updated:
     self.storeStatusVar.set("Catalog metadata updated (%d apps updated)" % updated)
    else:
     self.storeStatusVar.set("Catalog metadata checked (%d applications)" % len(self.catalog))
   elif getattr(res, "partial", False):
    self.storeStatusVar.set("Catalog partially updated (cached fallback used)")
   elif getattr(res, "errors", None):
    self.storeStatusVar.set("Using cached catalog (updates deferred)")
   else:
    self.storeStatusVar.set("Using cached catalog")
  elif res is True:
   self.storeStatusVar.set("Catalog updated with latest versions")
  else:
   self.storeStatusVar.set("Using cached catalog")

 def startBackgroundSync(self):
  if getattr(self, "_syncStarted", False):
   return
  self._syncStarted = True
  threading.Thread(target=self._syncWorker, daemon=True).start()

 def downloadStoreApp(self, pkg):
  appData = self.catalog.get(pkg)
  if not appData:
   return
  if not appData.get("url"):
   showerror("Download unavailable", "No direct download URL is available for %s yet. Check the source repository." % appData.get("name"))
   return
  from types import SimpleNamespace
  rel = SimpleNamespace(version=appData.get("version"), url=appData.get("url"))
  expected_pkg = appData.get("package") or pkg
  appObj = SimpleNamespace(name=appData.get("name"), package=expected_pkg, release=rel)
  filename = asksaveasfilename(
   parent=self.master,
   title="Save %s APK" % appData.get("name"),
   initialdir=os.path.expanduser("~/Downloads"),
   initialfile="%s.apk" % pkg,
   defaultextension=".apk",
   filetypes=[("Android apps", "*.apk")]
  )
  if not filename:
   return
  task_gen = self._nextTaskGeneration() if hasattr(self, "_nextTaskGeneration") else 0
  abort_ev = threading.Event()
  self.downloadAbortEvent = abort_ev
  _setTaskDownloadBusy(self, True)
  self.updateProgress(None, "Downloading %s APK…" % appData.get("name"), taskGen=task_gen)
  threading.Thread(target=self._downloadStoreWorker, args=(appObj, filename, task_gen, abort_ev), daemon=True).start()

 def _downloadStoreWorker(self, appObj, filename, task_gen=None, abort_ev=None):
  result = None
  try:
   print("Downloading %s (%s)…" % (appObj.name, appObj.package))
   def _prog(d, t):
    self.run(lambda: self.updateProgress(100*d/t if t else None, "Downloading %d KB" % (d//1024), taskGen=task_gen))
   result = downloadCatalogApp(appObj, filename, _prog, abort_event=abort_ev)
   print("%s downloaded and validated (%d bytes)." % (result["name"], result["bytes"]))
  except DownloadCancelledError:
   print("%s download cancelled." % (appObj.name or "App"))
   result = "CANCELLED"
  except Exception:
   traceback.print_exc()
  self._runSafely(lambda: self._downloadStoreDone(result, task_gen, abort_ev))

 def _downloadStoreDone(self, result, task_gen=None, abort_ev=None):
  if getattr(self, "downloadAbortEvent", None) is abort_ev:
   self.downloadAbortEvent = None
  active_gen = getattr(self, "_activeTaskGen", task_gen)
  is_current = (task_gen is None or active_gen is None or task_gen == active_gen)
  camera_busy = bool(getattr(self.master, "cameraBusy", False))
  if result == "CANCELLED":
   if is_current and not camera_busy:
    self.updateProgress(0, "Download cancelled", taskGen=task_gen)
  elif isinstance(result, dict) and result.get("path"):
   self.setApkFile(result["path"])
   if is_current and not camera_busy:
    self.updateProgress(100, "%s downloaded and validated; not installed" % result["name"], taskGen=task_gen)
  else:
   if is_current and not camera_busy:
    self.updateProgress(0, "Download failed; check Activity log", taskGen=task_gen)
  _setTaskDownloadBusy(self, False)

 def getMode(self):
  return self.modeVar.get()

 def openApk(self):
  filename = askopenfilename(parent=self.master, filetypes=[("Android apps", "*.apk"), ("All files", "*")])
  if filename:
   self.setApkFile(filename)

 def revealApk(self):
  path = self.getSelectedApk()
  if path and os.path.isfile(path):
   if sys.platform == "darwin":
    subprocess.run(["open", "-R", path])
   else:
    webbrowser.open("file://" + os.path.dirname(os.path.abspath(path)))

 def focusCatalog(self):
  if hasattr(self, "searchEntry"):
   self.searchEntry.focus_set()

 def focusApk(self):
  if hasattr(self, "apkFile"):
   self.apkFile.focus_set()

 def setApkFile(self, filename):
  self.apkFile.config(state=NORMAL)
  self.apkFile.delete(0, END)
  self.apkFile.insert(0, filename)
  self.apkFile.config(state="readonly")
  self.modeVar.set(self.MODE_APK)
  if hasattr(self, "apkRevealButton"):
   self.apkRevealButton.config(state=NORMAL if os.path.isfile(filename) else DISABLED)
  self._apkIsValid = False
  try:
   with open(filename, "rb") as file:
    apk = ApkParser(file)
    pkg = apk.getPackageName()
    if not pkg or not pkg.strip():
     raise ValueError("Manifest package identifier missing")
    sdk = apk.getMinSdkVersion()
    if not (1 <= sdk <= 10):
     raise ValueError("Android SDK %d is incompatible (camera requires API 1–10)" % sdk)
    cert = None
    try:
     cert = apk.getCert()
    except Exception:
     cert = None
    if not cert:
     raise ValueError("APK signature certificate missing or invalid")
    self._apkIsValid = True
    sdkStatus = "Android API %d (Camera API 1–10 required; check model/firmware compatibility)" % sdk
    text = "Package: %s\nVersion: %s   •   %s" % (
     pkg,
     apk.getVersionName() or "—",
     sdkStatus
    )
   self.apkSummary.set(text)
  except Exception as error:
   self._apkIsValid = False
   self.apkSummary.set("Could not read APK: %s" % error)
  self.updateInstallButton()

 def updateInstallButton(self):
  master = self.master
  cameraReady = bool(getattr(master, "cameraActionsEnabled", False) and getattr(master, "cameraConnected", False))
  installSupported = getattr(master, "cameraInstallEnabled", True) is not False
  backendBusy = bool(getattr(master, "lastReportedBackendBusy", False))
  busy = bool(getattr(master, "cameraBusy", False) or backendBusy or getattr(master, "downloadBusy", False))
  apkPath = self.getSelectedApk()
  hasValidApk = bool(apkPath and os.path.isfile(apkPath) and getattr(self, "_apkIsValid", True))
  canInstall = cameraReady and installSupported and hasValidApk and not busy
  if hasattr(self, "installButton"):
   self.installButton.config(state=NORMAL if canInstall else DISABLED)
  if hasattr(self, "apkRevealButton"):
   self.apkRevealButton.config(state=NORMAL if (apkPath and os.path.isfile(apkPath) and not busy) else DISABLED)

 def updateCameraStatus(self, connected, mode="MTP", cameraName=None, installSupported=None, installReason=None):
  if connected:
   name = cameraName or "Camera"
   if installSupported is False:
    reason = installReason or "PMCA app installation is not supported on this model (diagnostic-only)."
    self.apkStatusNote.set("Camera connected: %s (%s) — %s" % (name, mode, reason))
   elif getattr(self.master, "lastReportedBackendBusy", False):
    self.apkStatusNote.set("Camera connected: %s (%s). Camera is busy." % (name, mode))
   else:
    self.apkStatusNote.set("Camera connected: %s (%s). Ready to install." % (name, mode))
  else:
   master = self.master
   if getattr(master, "lastReportedPhysical", False):
    reason = installReason or getattr(master, "supportReason", "")
    if reason and reason != "app connection unavailable":
     self.apkStatusNote.set(reason)
    else:
     self.apkStatusNote.set("USB device detected on bus, but MTP session unavailable.")
   else:
    self.apkStatusNote.set("Camera not connected. Connect camera in MTP mode to enable install.")
  self.updateInstallButton()

 def getSelectedApk(self):
  return self.apkFile.get()

 def setAppList(self, apps):
  self.appList = apps
  self.filteredApps = list(apps)
  if self.appCombo is not None:
   if apps:
    self.appCombo["values"] = ["(Select an application)"] + [app.name for app in apps]
    self.appCombo.current(0)
    self.appDetailVar.set("Found %d applications in catalog." % len(apps))
   else:
    self.appCombo["values"] = ["(Catalog not loaded)"]
    self.appCombo.current(0)
    self.appDetailVar.set("Click Check Updates to sync catalog.")
  if self.appDownloadButton is not None:
   self.appDownloadButton.config(state=DISABLED)

 def filterAppList(self):
  if not hasattr(self, "searchVar"):
   return
  query = self.searchVar.get().strip().lower()
  if not self.appList:
   return
  if not query:
   self.filteredApps = list(self.appList)
  else:
   self.filteredApps = [
    app for app in self.appList
    if query in (getattr(app, "name", "") or "").lower()
    or query in (getattr(app, "package", "") or "").lower()
    or query in (getattr(app, "desc", "") or "").lower()
    or query in (getattr(app, "author", "") or "").lower()
   ]
  if self.filteredApps:
   self.appCombo["values"] = ["(Select an application)"] + [app.name for app in self.filteredApps]
   self.appCombo.current(0)
  else:
   self.appCombo["values"] = ["(No matching applications)"]
   self.appCombo.current(0)
  if self.appDownloadButton is not None:
   self.appDownloadButton.config(state=DISABLED)

 def onAppLoadFailed(self):
  if not self.appList:
   self.appCombo["values"] = ["(Catalog unavailable)"]
   self.appCombo.current(0)
   self.appDetailVar.set("Could not fetch online catalog.")
  else:
   self.appDetailVar.set("Could not refresh catalog; retaining %d apps." % len(self.appList))
  self.updateProgress(0, "Failed to fetch catalog; check Activity log")

 def onAppSelected(self, event=None):
  app = self.getSelectedApp()
  if app:
   if self.appDownloadButton is not None:
    self.appDownloadButton.config(state=NORMAL)
   author = getattr(app, "author", "") or "OpenMemories community"
   desc = getattr(app, "desc", "") or "No description provided."
   text = "%s by %s\nPackage: %s\n%s" % (app.name, author, app.package, desc)
   self.appDetailVar.set(text)
  else:
   if self.appDownloadButton is not None:
    self.appDownloadButton.config(state=DISABLED)
   self.appDetailVar.set("Select an application from the dropdown above.")

 def getSelectedApp(self):
  apps = getattr(self, "filteredApps", None) or self.appList
  if self.appCombo is not None and self.appCombo.current() > 0 and (self.appCombo.current() - 1) < len(apps):
   return apps[self.appCombo.current() - 1]
  return None

 def updateProgress(self, percent, message, taskGen=None):
  active_gen = getattr(self, "_activeTaskGen", taskGen)
  if taskGen is not None and active_gen is not None and taskGen != active_gen:
   return
  if percent is None:
   if not getattr(self, "_progressIndeterminateActive", False):
    self.progressBar.config(mode="indeterminate")
    self.progressBar.start(30)
    self._progressIndeterminateActive = True
   self.progressText.set(message)
  else:
   if getattr(self, "_progressIndeterminateActive", False):
    self.progressBar.stop()
    self._progressIndeterminateActive = False
   self.progressBar.config(mode="determinate")
   value = max(0, min(100, int(percent)))
   self.progressBar["value"] = value
   self.progressText.set("%s — %d%%" % (message, value))

 def showInstallResult(self, result):
  self._progressIndeterminateActive = False
  is_error = isinstance(result, BaseException) or getattr(result, "outcome_unknown", False) or (hasattr(result, "code") and getattr(result, "code", 0) not in (0, None))
  is_success = bool(result) and not is_error
  if hasattr(self, "progressBar") and self.progressBar is not None:
   try:
    prev_val = self.progressBar["value"] if "value" in self.progressBar else None
   except Exception:
    try:
     prev_val = self.progressBar["value"]
    except Exception:
     prev_val = None
   try:
    self.progressBar.stop()
    self.progressBar.config(mode="determinate")
    if is_success:
     self.progressBar["value"] = 100
    elif prev_val is not None:
     self.progressBar["value"] = prev_val
   except Exception:
    pass
  if is_error:
   if getattr(result, "outcome_unknown", False):
    self.progressText.set("Installation outcome unknown: %s Check the camera applications list before retrying." % result)
   else:
    self.progressText.set("Installation did not complete: %s" % result)
  elif is_success:
   msg = "Installation completed. Verify the app on the camera."
   if isinstance(result, dict):
    apps = result.get("applications", [])
    dev = result.get("deviceinfo", {})
    dev_name = dev.get("name") or "camera"
    if apps and isinstance(apps, list) and len(apps) > 0:
     app_info = apps[0]
     if isinstance(app_info, dict):
      name = app_info.get("name", "App")
      ver = app_info.get("version", "")
      msg = "Successfully installed %s %s on %s!" % (name, ver, dev_name)
    elif dev.get("name"):
     msg = "Installation completed on %s. App acknowledged by camera." % dev.get("name")
   elif hasattr(result, "message") and getattr(result, "code", None) == 0:
    msg = "Installation completed: %s." % result.message
   self.progressText.set(msg)
  else:
   self.progressText.set("Installation did not complete. Check Activity for details.")


class FirmwareFrame(UiFrame):
 def __init__(self, parent, **kwargs):
  UiFrame.__init__(self, parent, **kwargs)

  datFrame = Labelframe(self, padding=5)
  datFrame['labelwidget'] = Label(datFrame, text='Firmware file')
  datFrame.pack(fill=X)

  self.datFile = Entry(datFrame)
  self.datFile.pack(side=LEFT, fill=X, expand=True)

  self.datSelectButton = Button(datFrame, text='Open...', command=self.openDat)
  self.datSelectButton.pack()

  self.fwUpdateButton = Button(self, text='Update firmware', command=FirmwareUpdateTask(self).run, padding=5)
  self.fwUpdateButton.pack(fill=X, pady=(5, 0))

 def openDat(self):
  fn = askopenfilename(filetypes=[('Firmware files', '.dat'), ('All files', '.*')])
  if fn:
   self.datFile.delete(0, END)
   self.datFile.insert(0, fn)

 def getSelectedDat(self):
  return self.datFile.get()


class UpdaterShellFrame(UiFrame):
 def __init__(self, parent, **kwargs):
  UiFrame.__init__(self, parent, **kwargs)

  self.startUpdaterShellButton = Button(self, text='Start tweaking (updater mode)', command=StartUpdaterShellTask(self).run, padding=5)
  self.startUpdaterShellButton.pack(fill=X)

  self.startSenserShellButton = Button(self, text='Start tweaking (service mode)', command=StartSenserShellTask(self).run, padding=5)
  self.startSenserShellButton.pack(fill=X, pady=(5, 0))


class TweakDialog(UiDialog):
 def __init__(self, parent, tweakInterface, endFlag=None):
  self.tweakInterface = tweakInterface
  self.endFlag = endFlag
  UiDialog.__init__(self, parent, "Tweaks")

 def body(self, top):
  tweakFrame = Labelframe(top, padding=5)
  tweakFrame['labelwidget'] = Label(tweakFrame, text='Tweaks')
  tweakFrame.pack(fill=X)

  self.boxFrame = Frame(tweakFrame)
  self.boxFrame.pack(fill=BOTH, expand=True)

  self.applyButton = Button(top, text='Apply', command=TweakApplyTask(self).run, padding=5)
  self.applyButton.pack(fill=X)

  self.updateStatus()

 def updateStatus(self):
  for child in self.boxFrame.winfo_children():
   child.destroy()
  for id, desc, status, value in self.tweakInterface.getTweaks():
   var = IntVar(value=status)
   c = Checkbutton(self.boxFrame, text=desc + '\n' + value, variable=var, command=lambda id=id, var=var: self.setTweak(id, var.get()))
   c.pack(fill=X)

 def setTweak(self, id, enabled):
  self.tweakInterface.setEnabled(id, enabled)
  self.updateStatus()

 def setState(self, state):
  for widget in self.boxFrame.winfo_children() + [self.applyButton]:
   widget.config(state=state)

 def cancel(self, event=None):
  UiDialog.cancel(self, event)
  if self.endFlag:
   self.endFlag.set()


def checkCamera(outFile):
 """Check camera connection status and write report without opening a window."""
 from pmca.commands.usb import getCameraStatus
 status = getCameraStatus(quiet=True)
 with open(outFile, 'w') as f:
  json.dump(status, f, indent=2)


def checkRuntime(outFile):
 """Check packaged dependencies without opening a window or USB device."""
 import platform
 from tkinter import Tcl
 from pmca import spk
 import tlslite

 libusb_loads = False
 libusb_path = None
 try:
  import usb.backend.libusb1
  find_lib = None
  if sys.platform == 'win32':
   try:
    import libusb_package
    find_lib = libusb_package.find_library
   except ImportError:
    pass
  library = usb.backend.libusb1._load_library(find_library=find_lib) if find_lib else usb.backend.libusb1._load_library()
  if library:
   libusb_loads = bool(getattr(library, 'libusb_get_version', None))
   libusb_path = str(getattr(library, '_name', 'libusb'))
 except Exception:
  pass

 with open(os.path.join(scriptRoot, 'certs/localtest.me.pem')) as f:
  pem = f.read()
 chain = tlslite.X509CertChain()
 chain.parsePemList(pem)
 key = tlslite.parsePEMKey(pem, private=True)
 sample = b'Sony Open PMCA runtime check'
 result = {
  'version': version or '1.2.0',
  'python': platform.python_version(),
  'architecture': platform.machine(),
  'frozen': bool(getattr(sys, 'frozen', False)),
  'tcl_version': Tcl().eval('info patchlevel'),
  'libusb_loads': libusb_loads,
  'libusb_path': libusb_path,
  'spk_roundtrip': spk.parse(spk.dump(sample)) == sample,
  'certificate_key_parses': bool(chain.x509List and key),
 }
 try:
  from pmca.marketserver.server import verify_tls_handshake
  tls_info = verify_tls_handshake(certFile=os.path.join(scriptRoot, 'certs/localtest.me.pem'))
  if isinstance(tls_info, dict):
   result['tls_handshake_verified'] = (tls_info.get('success') is True)
   if tls_info.get('cipher'):
    result['tls_cipher'] = tls_info.get('cipher')
   if tls_info.get('version'):
    result['tls_version'] = tls_info.get('version')
   if (tls_info.get('success') is not True) and tls_info.get('error'):
    result['tls_error'] = str(tls_info.get('error'))
  else:
   result['tls_handshake_verified'] = (tls_info is True)
 except Exception as e:
  result['tls_handshake_verified'] = False
  result['tls_error'] = str(e)
 with open(outFile, 'w') as f:
  json.dump(result, f, indent=2)


def main():
 """Gui main"""
 if len(sys.argv) == 3 and sys.argv[1] == '--check-runtime':
  checkRuntime(sys.argv[2])
  return
 if len(sys.argv) == 3 and sys.argv[1] == '--check-camera':
  checkCamera(sys.argv[2])
  return
 installerOnly = True
 title = 'Sony Open PMCA'
 ui = MainUi(title + (' ' + version if version else ''), installerOnly=installerOnly)
 ui.mainloop()


if __name__ == '__main__':
 main()
