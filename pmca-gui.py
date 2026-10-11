#!/usr/bin/env python3
"""A simple gui interface"""
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import traceback
import urllib.parse
from urllib import request
import webbrowser
from datetime import datetime
from tkinter import font as tkfont
from tkinter.filedialog import asksaveasfilename
from tkinter.messagebox import askyesno, showerror
import certifi
from pmca.appstore.recipelab import downloadRecipeLab, HttpsRedirectHandler
from pmca.appstore.catalog import loadCatalog, saveCatalog, syncCatalogMetadata, downloadCatalogApp, SEED_APPS

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
  if getattr(self.ui.master, "cameraBusy", False) or getattr(self.ui.master, "lastReportedBackendBusy", False):
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
  self.ui.master.setCameraBusy(True)
  return mode, apkData, app, self.ui.master.driverName

 def do(self, args):
  if args is None:
   return
  mode, apkData, app, driverName = args
  response = None
  try:
   print('')
   self.ui.run(lambda: self.ui.updateProgress(0, 'Starting installation'))
   if mode == self.ui.MODE_APP and app:
    response = installCommand(driverName=driverName, appPackage=app.package, statusFunc=self.onStatus)
   elif mode == self.ui.MODE_APK and apkData:
    response = installCommand(driverName=driverName, apkFile=io.BytesIO(apkData), statusFunc=self.onStatus)
  except Exception:
   traceback.print_exc()
  return True, (response if response else False)

 def onStatus(self, status):
  printStatus(status)
  self.ui.run(lambda: self.ui.updateProgress(status.percent, status.message))

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
  self.ui.master.setCameraBusy(True)
  self.ui.updateProgress(None, 'Checking the latest RecipeLab release')
  return filename

 def do(self, filename):
  if filename is None:
   return
  result = None
  try:
   print('Downloading RecipeLab from voxivoid/recipe-lab-sony-pmca')
   result = downloadRecipeLab(filename, self.onProgress)
   print('RecipeLab %s downloaded and validated (%d bytes). No camera app was installed.' % (result['version'], result['bytes']))
  except Exception:
   traceback.print_exc()
  return True, result

 def onProgress(self, downloaded, total):
  percent = 100 * downloaded / total if total else None
  message = 'Downloading RecipeLab (%d KB)' % (downloaded // 1024)
  self.ui.run(lambda: self.ui.updateProgress(percent, message))

 def doAfter(self, result):
  if result:
   if result[1]:
    self.ui.setApkFile(result[1]['path'])
    self.ui.updateProgress(100, 'Download validated; not installed')
   else:
    self.ui.updateProgress(0, 'Download failed; use a local APK or check Activity')
   self.ui.master.setCameraBusy(False)



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
  self.ui.master.setCameraBusy(True)
  self.ui.updateProgress(None, 'Checking %s release information…' % (app.name or 'app'))
  return app, filename

 def do(self, args):
  if not args:
   return
  app, filename = args
  result = None
  try:
   print('Downloading %s (%s)…' % (app.name, app.package))
   result = downloadCatalogApp(app, filename, self.onProgress)
   print('%s %s downloaded and validated (%d bytes). No camera app was installed.' % (
    result['name'], result.get('version') or '', result['bytes']))
  except Exception:
   traceback.print_exc()
  return True, result

 def onProgress(self, downloaded, total):
  percent = 100 * downloaded / total if total else None
  message = 'Downloading %s (%d KB)' % (getattr(self, 'appName', 'app'), downloaded // 1024)
  self.ui.run(lambda: self.ui.updateProgress(percent, message))

 def doAfter(self, result):
  if result:
   if result[1]:
    self.ui.setApkFile(result[1]['path'])
    self.ui.updateProgress(100, '%s downloaded and validated; not installed' % result[1]['name'])
   else:
    self.ui.updateProgress(0, 'Download failed; check Activity log')
   self.ui.master.setCameraBusy(False)

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
 def __init__(self, title, installerOnly=False):
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
  self.logFilterVar.trace_add("write", lambda *_: self.filterLogDisplay())
  self.logFilterEntry = Entry(logFilterBar, textvariable=self.logFilterVar, width=24)
  self.logFilterEntry.pack(side=LEFT, padx=(0, 10))
  self.logLevelVar = StringVar(value="All")
  self.logLevelCombo = Combobox(logFilterBar, textvariable=self.logLevelVar, values=["All", "Errors only", "Info only"], state="readonly", width=12)
  self.logLevelCombo.pack(side=LEFT, padx=(0, 10))
  self.logLevelCombo.bind("<<ComboboxSelected>>", lambda e: self.filterLogDisplay())
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
  self.rawLogEntries = []

  self.setCameraBusy(False)
  self.redirectStreams()
  self.updateNavHighlight()
  self.startCameraMonitor()
  self._setupScrollClasses()

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
  """Thread-safe dispatch to the main GUI thread via UiRoot queue."""
  try:
   UiRoot.run(self, func)
  except Exception:
   try:
    self.after(0, func)
   except Exception:
    pass

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

 def startCameraMonitor(self):
  threading.Thread(target=self._cameraMonitorWorker, daemon=True).start()

 def _cameraMonitorWorker(self):
  while hasattr(self, "abortMonitor") and not self.abortMonitor.is_set():
   if not self.cameraBusy:
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
  physical = bool(info and (info.get("physicalDetected") or info.get("connected") or "USB" in str(info.get("status", "")) or info.get("status") in ("access_denied", "unverified", "multiple_devices")))
  status = info.get("status") if info else "disconnected"
  self.lastReportedPhysical = physical
  just_connected = appConnected and not getattr(self, "cameraConnected", False)
  backend_busy = bool(info and info.get("busy"))
  self.lastReportedBackendBusy = backend_busy

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
    if backend_busy:
     self.cameraInstallEnabled = False
     self.supportReason = "Camera is currently busy."
    else:
     self.cameraInstallEnabled = True
     self.supportReason = ""

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
   if status == "multiple_devices":
    reason = info.get("failure_reason") or "Multiple Sony cameras detected. Connect only one Sony camera at a time."
    self.supportReason = reason
    self.usbStatusVar.set("○ Multiple Sony cameras connected")
   elif "access_denied" in status:
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
    with open(filename, "w", encoding="utf-8") as f:
     f.write(self.logText.text.get("1.0", END).rstrip())
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
  text = "\n\n".join(error_blocks) if error_blocks else "No errors in log."
  self.clipboard_clear()
  self.clipboard_append(text)
  print("Copied %d complete error blocks to clipboard" % len(error_blocks))

 def filterLogDisplay(self):
  q = self.logFilterVar.get().lower() if hasattr(self, "logFilterVar") else ""
  level = self.logLevelVar.get() if hasattr(self, "logLevelVar") else "All"
  self.logText.text.configure(state=NORMAL)
  self.logText.text.delete("1.0", END)
  for timestamp, text, tag in getattr(self, "rawLogEntries", []):
   if level == "Errors only" and tag != "error":
    continue
   if level == "Info only" and tag != "info":
    continue
   if q and q not in text.lower():
    continue
   line = "[%s] %s\n" % (timestamp, text)
   self.logText.text.insert(END, line, tag)
  self.logText.text.configure(state=DISABLED)
  if getattr(self, "autoScroll", True):
   self.logText.text.see(END)

 def setCameraBusy(self, busy):
  self.cameraBusy = busy
  state = DISABLED if busy else NORMAL
  cameraState = state if getattr(self, "cameraActionsEnabled", True) else DISABLED
  if hasattr(self, "infoFrame") and hasattr(self.infoFrame, "infoButton"):
   self.infoFrame.infoButton.config(state=cameraState)
  if hasattr(self, "installerFrame") and hasattr(self.installerFrame, "updateInstallButton"):
   self.installerFrame.updateInstallButton()
  elif hasattr(self, "installerFrame") and hasattr(self.installerFrame, "installButton"):
   self.installerFrame.installButton.config(state=cameraState)
  for name in ["downloadButton", "apkSelectButton", "apkRevealButton", "appLoadButton", "appDownloadButton"]:
   button = getattr(self.installerFrame, name, None)
   if button is not None:
    if not busy and name == "appDownloadButton":
     selected = self.installerFrame.getSelectedApp() if hasattr(self.installerFrame, "getSelectedApp") else None
     button.config(state=NORMAL if selected else DISABLED)
    elif not busy and name == "apkRevealButton":
     apkPath = self.installerFrame.getSelectedApk() if hasattr(self.installerFrame, "getSelectedApk") else None
     button.config(state=NORMAL if (apkPath and os.path.isfile(apkPath)) else DISABLED)
    else:
     button.config(state=state)
  combo = getattr(self.installerFrame, "appCombo", None)
  if combo is not None:
   combo.config(state=DISABLED if busy else "readonly")
  search = getattr(self.installerFrame, "searchEntry", None)
  if search is not None:
   search.config(state=DISABLED if busy else NORMAL)
  if hasattr(self, "reconnectButton"):
   self.reconnectButton.config(state=state)
  if hasattr(self.installerFrame, "setStoreBusy"):
   self.installerFrame.setStoreBusy(busy)
  if hasattr(self, "statusVar"):
   self.statusVar.set("An operation is running…" if busy else "Camera not connected — connect camera in MTP mode." if not self.cameraActionsEnabled else "Idle.")

 def close(self):
  if self.cameraBusy:
   showerror("Operation in progress", "Wait for the current operation to finish before closing. If the camera is in use, keep it connected.")
   return
  if hasattr(self, "abortMonitor"):
   self.abortMonitor.set()
  abort = getattr(self, "abortSync", None)
  if abort is not None:
   abort.set()
  self.destroy()

 def log(self, msg, error=False):
  self.logBuffers[error] += msg
  while "\n" in self.logBuffers[error]:
   line, self.logBuffers[error] = self.logBuffers[error].split("\n", 1)
   if not line:
    continue
   tag = "error" if error or line.startswith(("Error:", "No devices found", "Operation timed out")) else "info"
   ts = datetime.now().strftime("%H:%M:%S")
   if hasattr(self, "rawLogEntries"):
    self.rawLogEntries.append((ts, line, tag))
   # Check if matches current filter
   q = self.logFilterVar.get().lower() if hasattr(self, "logFilterVar") else ""
   level = self.logLevelVar.get() if hasattr(self, "logLevelVar") else "All"
   if (level == "Errors only" and tag != "error") or (level == "Info only" and tag != "info") or (q and q not in line.lower()):
    continue
   text = "[%s] %s\n" % (ts, line)
   self.logText.text.configure(state=NORMAL)
   self.logText.text.insert(END, text, tag)
   self.logText.text.configure(state=DISABLED)
   # Check if user scrolled away from bottom or has active text selection
   try:
    y_top, y_bottom = self.logText.text.yview()
    has_sel = bool(self.logText.text.tag_ranges("sel"))
    if y_bottom < 0.98 or has_sel:
     self.autoScroll = False
     if hasattr(self, "autoScrollBtn"):
      self.autoScrollBtn.config(text="Resume auto-scroll")
   except Exception:
    pass
   if getattr(self, "autoScroll", True):
    self.logText.text.see(END)

 def copyLog(self):
  self.clipboard_clear()
  self.clipboard_append(self.logText.text.get("1.0", END).rstrip())

 def clearLog(self):
  self.logBuffers = {False: "", True: ""}
  self.rawLogEntries = []
  self.logText.text.configure(state=NORMAL)
  self.logText.text.delete("1.0", END)
  self.logText.text.configure(state=DISABLED)

 def redirectStreams(self):
  for stream in ["stdout", "stderr"]:
   callback = lambda text, error=stream == "stderr": self.run(lambda: self.log(text, error))
   setattr(sys, stream, PrintRedirector(callback, getattr(sys, stream)))


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

  # Progress Section - pinned to bottom
  progressSection = Frame(self)
  progressSection.pack(side=BOTTOM, fill=X, pady=(4, 0))
  self.progressText = StringVar(value="No operation running.")
  Label(progressSection, textvariable=self.progressText, style="Detail.TLabel").pack(anchor=W, pady=(0, 2))
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
  self.canvas.itemconfig(self.canvasWindow, width=event.width)
  wrap = max(300, event.width - 250)
  for lbl in getattr(self, "descLabels", []):
   try:
    lbl.config(wraplength=wrap)
   except Exception:
    pass

 def renderAppCards(self, filterQuery=None):
  self.cardDownloadButtons = []
  self.descLabels = []
  for w in self.cardsFrame.winfo_children():
   w.destroy()
  self.cardsFrame.columnconfigure(0, weight=1)
  q = (filterQuery or "").strip().lower()
  displayed = 0
  canvas_w = self.canvas.winfo_width() if hasattr(self, "canvas") else 800
  wrap_width = max(360, canvas_w - 240)
  for idx, (pkg, app) in enumerate(self.catalog.items()):
   name = app.get("name", "")
   author = app.get("author", "")
   desc = app.get("desc", "")
   ver = app.get("version")
   ver_display = ver if (ver and ver != "Release pending") else "Version unverified"
   actual_pkg = app.get("package") or pkg
   caveat = app.get("support_caveats") or app.get("compatibility")
   if q and q not in name.lower() and q not in pkg.lower() and q not in desc.lower() and q not in author.lower() and q not in actual_pkg.lower():
    continue
   displayed += 1
   row = Frame(self.cardsFrame, padding=(10, 6))
   row.pack(fill=X, pady=2, padx=4)
   row.columnconfigure(0, weight=1)
   row.columnconfigure(1, weight=0, minsize=220)

   textBox = Frame(row)
   textBox.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

   # Line 1: Name and Version
   titleLabel = Label(textBox, text="%s  (%s)" % (name, ver_display), style="Subheading.TLabel")
   titleLabel.pack(anchor=W)

   # Line 2: Author, Package, and Compatibility Note
   meta_text = "by %s  •  %s" % (author, actual_pkg)
   if caveat:
    meta_text += "  •  %s" % caveat
   metaLabel = Label(textBox, text=meta_text, style="Detail.TLabel")
   metaLabel.pack(anchor=W, pady=(1, 2))

   # Line 3: Description
   descLabel = Label(textBox, text=desc, style="Detail.TLabel")
   descLabel.pack(anchor=W)
   self.descLabels.append(descLabel)

   def _onTextBoxConfigure(event, tl=titleLabel, ml=metaLabel, dl=descLabel):
    alloc_w = max(180, event.width - 4)
    tl.config(wraplength=alloc_w)
    ml.config(wraplength=alloc_w)
    dl.config(wraplength=alloc_w)

   textBox.bind("<Configure>", _onTextBoxConfigure)

   # Column 1: Action group docked on the right
   actionBox = Frame(row)
   actionBox.grid(row=0, column=1, sticky="e")
   btn = None
   if not app.get("url"):
    btn = Button(actionBox, text="No APK", state=DISABLED, padding=(8, 3))
   elif pkg == "com.voxivoid.recipelab":
    btn = Button(actionBox, text="Download APK", command=RecipeDownloadTask(self).run, padding=(8, 3))
   else:
    btn = Button(actionBox, text="Download APK", command=lambda p=pkg: self.downloadStoreApp(p), padding=(8, 3))
   btn.pack(side=LEFT, padx=(0, 6))
   self.cardDownloadButtons.append(btn)
   homepage = app.get("homepage")
   if homepage:
    Button(actionBox, text="Source ↗", command=lambda u=homepage: webbrowser.open_new(u), padding=(6, 3)).pack(side=LEFT)
   Separator(self.cardsFrame, orient=HORIZONTAL).pack(fill=X, padx=4, pady=1)
   self._tagStoreScrollable(row)
  spacer = Frame(self.cardsFrame, height=20)
  spacer.pack(fill=X)
  self._tagStoreScrollable(spacer)
  self.cardsFrame.update_idletasks()
  self.canvas.configure(scrollregion=self.canvas.bbox("all"))
  if not hasattr(self, "_lastSyncResult"):
   self.storeStatusVar.set("%d catalog apps available" % len(self.catalog))
  if getattr(self.master, "cameraBusy", False):
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
  if hasattr(self, "run"):
   try:
    self.run(func)
    return
   except Exception:
    pass
  if hasattr(self, "after"):
   try:
    self.after(0, func)
   except Exception:
    pass

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
  if not getattr(self.master, "cameraBusy", False):
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
  self.master.setCameraBusy(True)
  self.updateProgress(None, "Downloading %s APK…" % appData.get("name"))
  threading.Thread(target=self._downloadStoreWorker, args=(appObj, filename), daemon=True).start()

 def _downloadStoreWorker(self, appObj, filename):
  result = None
  try:
   print("Downloading %s (%s)…" % (appObj.name, appObj.package))
   result = downloadCatalogApp(appObj, filename, lambda d, t: self.run(lambda: self.updateProgress(100*d/t if t else None, "Downloading %d KB" % (d//1024))))
   print("%s downloaded and validated (%d bytes)." % (result["name"], result["bytes"]))
  except Exception:
   traceback.print_exc()
  self._runSafely(lambda: self._downloadStoreDone(result))

 def _downloadStoreDone(self, result):
  if result and result.get("path"):
   self.setApkFile(result["path"])
   self.updateProgress(100, "%s downloaded and validated; not installed" % result["name"])
  else:
   self.updateProgress(0, "Download failed; check Activity log")
  self.master.setCameraBusy(False)

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
  busy = bool(getattr(master, "cameraBusy", False) or backendBusy)
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
    if reason and "Multiple" in reason:
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

 def updateProgress(self, percent, message):
  self.progressBar.stop()
  if percent is None:
   self.progressBar.config(mode="indeterminate")
   self.progressBar.start(30)
   self.progressText.set(message)
  else:
   self.progressBar.config(mode="determinate")
   value = max(0, min(100, int(percent)))
   self.progressBar["value"] = value
   self.progressText.set("%s — %d%%" % (message, value))

 def showInstallResult(self, result):
  if hasattr(self, "progressBar") and self.progressBar is not None:
   try:
    self.progressBar.stop()
    self.progressBar.config(mode="determinate")
    if result:
     self.progressBar["value"] = 100
   except Exception:
    pass
  if result:
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
  'version': version or '1.1.0',
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
