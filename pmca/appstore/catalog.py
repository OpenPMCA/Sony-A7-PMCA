"""Persistent catalog cache and metadata synchronization for Sony PMCA applications."""
import copy
from datetime import datetime, timezone
import json
import os
import ssl
import tempfile
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse

import certifi

from .recipelab import HttpsRedirectHandler
from ..apk import ApkParser

SEED_APPS = {
 "com.voxivoid.recipelab": {
  "package": "com.voxivoid.recipelab",
  "name": "RecipeLab",
  "author": "voxivoid",
  "desc": "Film recipes and picture profile manager for Sony cameras.",
  "version": "1.6.2",
  "url": "https://github.com/voxivoid/recipe-lab-sony-pmca/releases/download/v1.6.2/RecipeLab.apk",
  "homepage": "https://github.com/voxivoid/recipe-lab-sony-pmca",
  "featured": True,
  "github_repo": "voxivoid/recipe-lab-sony-pmca",
 },
 "com.github.ma1co.pmcademo.app": {
  "package": "com.github.ma1co.pmcademo.app",
  "name": "PMCADemo",
  "author": "ma1co",
  "desc": "A demo app for Sony camera developers with liveview and keypad tests",
  "version": "0.7",
  "url": "https://github.com/ma1co/PMCADemo/releases/download/v0.7/PMCADemo-release-0.7.apk",
  "homepage": "https://github.com/ma1co/PMCADemo",
  "featured": False,
  "github_repo": "ma1co/PMCADemo",
 },
 "com.github.ma1co.openmemories.tweak": {
  "package": "com.github.ma1co.openmemories.tweak",
  "name": "OpenMemories: Tweak",
  "author": "ma1co",
  "desc": "Unlock your camera's settings",
  "version": "0.11",
  "url": "https://github.com/ma1co/OpenMemories-Tweak/releases/download/v0.11/OpenMemories-Tweak-release-0.11.apk",
  "homepage": "https://github.com/ma1co/OpenMemories-Tweak",
  "featured": False,
  "github_repo": "ma1co/OpenMemories-Tweak",
 },
 "com.github.ma1co.openmemories.appstore": {
  "package": "com.github.ma1co.openmemories.appstore",
  "name": "OpenMemories: AppStore",
  "author": "ma1co",
  "desc": "Install new apps directly on your camera",
  "version": "1.3",
  "url": "https://github.com/ma1co/OpenMemories-AppStore/releases/download/1.3/OpenMemories-AppStore-release-1.3.apk",
  "homepage": "https://github.com/ma1co/OpenMemories-AppStore",
  "featured": False,
  "github_repo": "ma1co/OpenMemories-AppStore",
 },
 "org.bostwickenator.dofmath": {
  "package": "org.bostwickenator.dofmath",
  "name": "dof-math",
  "author": "Bostwickenator",
  "desc": "Calculate the front, back, and hyperfocal distances",
  "version": "1.0",
  "url": "https://github.com/Bostwickenator/dof-math/releases/download/1.0/dof-1.0.apk",
  "homepage": "https://github.com/Bostwickenator/dof-math",
  "featured": False,
  "github_repo": "Bostwickenator/dof-math",
 },
 "org.bostwickenator.googlephotos": {
  "package": "org.bostwickenator.googlephotos",
  "name": "STG Uploader",
  "author": "Bostwickenator",
  "desc": "Upload photos directly into Google Photos",
  "version": "1.8",
  "url": "https://www.stg-uploader.xyz/releases/stg-uploader-1.8.apk",
  "homepage": "https://www.stg-uploader.xyz/",
  "featured": False,
 },
 "org.bostwickenator.ftpuploader": {
  "catalog_id": "org.bostwickenator.ftpuploader",
  "package": "org.bostwickenator.googlephotos",
  "name": "FTP Uploader",
  "author": "Bostwickenator",
  "desc": "Upload photos to your FTP server",
  "version": "1.1",
  "url": "https://www.stg-uploader.xyz/ftp-releases/ftp-uploader-1.1.apk",
  "homepage": "https://www.stg-uploader.xyz/",
  "featured": False,
 },
 "com.obsidium.focusbracket": {
  "package": "com.obsidium.focusbracket",
  "name": "FocusBracket",
  "author": "obs1dium",
  "desc": "Proof-of-concept app for focus bracketing",
  "version": "1.5",
  "url": "https://github.com/obs1dium/FocusBracket/releases/download/1.5/FocusBracket-release-1.5.apk",
  "homepage": "https://github.com/obs1dium/FocusBracket",
  "featured": False,
  "github_repo": "obs1dium/FocusBracket",
 },
 "com.obsidium.bettermanual": {
  "package": "com.obsidium.bettermanual",
  "name": "BetterManual",
  "author": "obs1dium",
  "desc": "Manual shooting helper (Designed for Alpha 5100; limited ILCE-7 key mapping)",
  "version": "1.5",
  "url": "https://github.com/obs1dium/BetterManual/releases/download/1.5/BetterManual-release-1.5.apk",
  "homepage": "https://github.com/obs1dium/BetterManual",
  "featured": False,
  "github_repo": "obs1dium/BetterManual",
 },
 "com.jonasjuffinger.timelapse": {
  "package": "com.jonasjuffinger.timelapse",
  "name": "TimeLapse",
  "author": "jonasjuffinger",
  "desc": "A simple app to take pictures with a given interval",
  "version": "1.4.0",
  "url": "https://github.com/jonasjuffinger/TimeLapse/releases/download/v.1.4.0/TimeLapse-release-1.4.0.apk",
  "homepage": "https://github.com/jonasjuffinger/TimeLapse",
  "featured": False,
  "github_repo": "jonasjuffinger/TimeLapse",
 },
 "com.github.LubikR.synologyuploader": {
  "package": "com.github.LubikR.synologyuploader",
  "name": "SynologyUploader",
  "author": "LubikR",
  "desc": "Upload photos to Synology NAS",
  "version": "1.5",
  "url": "https://github.com/LubikR/SynologyUploader/releases/download/1.5/SynologyUploader-1.5.apk",
  "homepage": "https://github.com/LubikR/SynologyUploader",
  "featured": False,
  "github_repo": "LubikR/SynologyUploader",
 },
 "info.schnatterer.pmcaFilesystemServer": {
  "package": "info.schnatterer.pmcaFilesystemServer",
  "name": "pmcaFilesystemServer",
  "author": "schnatterer",
  "desc": "Provides the File System of the camera via HTTP",
  "version": "0.2.0",
  "url": "https://github.com/schnatterer/pmcaFilesystemServer/releases/download/0.2.0/pmcaFilesystemServer-0.2.0.apk",
  "homepage": "https://github.com/schnatterer/pmcaFilesystemServer",
  "featured": False,
  "github_repo": "schnatterer/pmcaFilesystemServer",
 },
 "com.yxy.astrofish": {
  "package": "com.yxy.astrofish",
  "name": "AstroFish",
  "author": "yxy (astrofish-tools)",
  "desc": "Star View low-light preview, Bulb timer (31s-6h), and long-exposure intervalometer (ILCE-7R verified)",
  "version": "1.0.0",
  "url": "https://github.com/astrofish-tools/AstroFish/releases/download/v1.0.0/AstroFish-1.0.0.apk",
  "homepage": "https://github.com/astrofish-tools/AstroFish",
  "featured": False,
  "github_repo": "astrofish-tools/AstroFish",
 },
 "com.github.benhawks.canondirectprint": {
  "package": "com.github.benhawks.canondirectprint",
  "name": "CanonDirectPrint",
  "author": "ben-hawks",
  "desc": "Print photos directly from camera to Canon SELPHY Wi-Fi printers",
  "version": "0.1.0",
  "url": "https://github.com/ben-hawks/OpenMemories-CanonDirectPrint/releases/download/v0.1.0/CanonDirectPrint-release-0.1.0.apk",
  "homepage": "https://github.com/ben-hawks/OpenMemories-CanonDirectPrint",
  "featured": False,
  "github_repo": "ben-hawks/OpenMemories-CanonDirectPrint",
 },
 "com.lenscatalog": {
  "package": "com.lenscatalog",
  "name": "LensCatalog",
  "author": "Grohle-developer",
  "desc": "In-camera manual lens database and EXIF focal length injector",
  "version": "0.4.0",
  "url": "https://github.com/Grohle-developer/lenscatalog/releases/download/v0.4.0/lenscatalog-0.4.0.apk",
  "homepage": "https://github.com/Grohle-developer/lenscatalog",
  "featured": False,
  "github_repo": "Grohle-developer/lenscatalog",
 },
 "com.sonylut.app": {
  "package": "com.sonylut.app",
  "name": "CustomLut (A6000-LUT)",
  "author": "starshine09074-ui",
  "desc": "Custom 3D LUT profile loader (Experimental; tested on A6000)",
  "version": "0.3.2",
  "url": "https://github.com/starshine09074-ui/A6000-LUT/releases/download/v0.3.2/CustomLut.apk",
  "homepage": "https://github.com/starshine09074-ui/A6000-LUT",
  "featured": False,
  "github_repo": "starshine09074-ui/A6000-LUT",
 },
 "io.github.bi2qfa.alphasync": {
  "package": "io.github.bi2qfa.alphasync",
  "name": "AlphaSync",
  "author": "BI2QFA",
  "desc": "PTP/IP camera wireless sync and transfer utility",
  "version": "1.0",
  "url": "https://github.com/BI2QFA/AlphaSync/releases/download/1.0/AlphaSync-Camera-1.0.apk",
  "homepage": "https://github.com/BI2QFA/AlphaSync",
  "featured": False,
  "github_repo": "BI2QFA/AlphaSync",
 },
 "bi2qfa.sony.ftp": {
  "package": "bi2qfa.sony.ftp",
  "name": "SonyFTP",
  "author": "BI2QFA",
  "desc": "Background wireless FTP photo auto-uploader",
  "version": "2.0",
  "url": "https://github.com/BI2QFA/SonyFTP/releases/download/v2.0/SonyFTP-v2.0.apk",
  "homepage": "https://github.com/BI2QFA/SonyFTP",
  "featured": False,
  "github_repo": "BI2QFA/SonyFTP",
 },
 "io.github.bi2qfa.sonyconnect": {
  "package": "io.github.bi2qfa.sonyconnect",
  "name": "SonyConnect",
  "author": "BI2QFA",
  "desc": "Automated camera Wi-Fi connection manager",
  "version": "2.5",
  "url": "https://github.com/BI2QFA/SonyConnect/releases/download/2.5/SonyConnect-Camera-2.5.apk",
  "homepage": "https://github.com/BI2QFA/SonyConnect",
  "featured": False,
  "github_repo": "BI2QFA/SonyConnect",
 },
 "com.vlousada.legacylenses": {
  "package": "com.vlousada.legacylenses",
  "name": "LegacyLenses",
  "author": "vlousada",
  "desc": "Manual focus assist & focal length EXIF recorder for vintage lenses",
  "version": "0.96r",
  "url": "https://github.com/vlousada/LegacyLenses/releases/download/0.96r/LegacyLensExif-0.96.apk",
  "homepage": "https://github.com/vlousada/LegacyLenses",
  "featured": False,
  "github_repo": "vlousada/LegacyLenses",
 },
 "com.github.dired.pmcahdmicam": {
  "package": "com.github.dired.pmcahdmicam",
  "name": "HDMI Camera (PMCA-HDMICam)",
  "author": "dired",
  "desc": "Clean HDMI video output helper for streaming",
  "version": "v0.2",
  "url": "https://github.com/dired/PMCA-HDMICam/releases/download/v0.2/com.github.dired.pmcahdmicam-v0.2.46-debug.apk",
  "homepage": "https://github.com/dired/PMCA-HDMICam",
  "featured": False,
  "github_repo": "dired/PMCA-HDMICam",
 },
 "org.mg.gpsdownloader": {
  "package": "org.mg.gpsdownloader",
  "name": "GPS Downloader",
  "author": "grueni75",
  "desc": "In-camera A-GPS data downloader via Wi-Fi (Requires built-in GPS hardware)",
  "version": "1.0",
  "url": "https://github.com/grueni75/GPSDownloader/releases/download/V1.0/gps-downloader-1.0.apk",
  "homepage": "https://github.com/grueni75/GPSDownloader",
  "featured": False,
  "github_repo": "grueni75/GPSDownloader",
 },
 "com.frosbe.timelapse": {
  "package": "com.frosbe.timelapse",
  "name": "SonyHolyGrailTimelapse",
  "author": "Frosbe",
  "desc": "Day-to-night holy grail exposure ramping intervalometer",
  "version": "1.0.0",
  "url": "https://github.com/Frosbe/SonyHolyGrailTimelapse/releases/download/1.0.0b/HolyGrail-release-1.0.0.apk",
  "homepage": "https://github.com/Frosbe/SonyHolyGrailTimelapse",
  "featured": False,
  "github_repo": "Frosbe/SonyHolyGrailTimelapse",
 },
 "com.example.xpanoverlay": {
  "package": "com.example.xpanoverlay",
  "name": "XPanOverlay",
  "author": "lngyneric",
  "desc": "24:65 panoramic crop overlay guide for shooting",
  "version": "1.2",
  "url": "https://raw.githubusercontent.com/lngyneric/xpan-overlay-sony-pmca/master/XPanOverlay-1.2.apk",
  "homepage": "https://github.com/lngyneric/xpan-overlay-sony-pmca",
  "featured": False,
 },
 "com.sony.imaging.app.livestreaming": {
  "package": "com.sony.imaging.app.livestreaming",
  "name": "OpenMemories: Launcher",
  "author": "ma1co",
  "desc": "Direct application launcher (Caveat: intended for camcorder/liveview models)",
  "version": "2.0",
  "url": "https://github.com/ma1co/OpenMemories-Launcher/releases/download/2.0/OpenMemories-Launcher-release-2.0.apk",
  "homepage": "https://github.com/ma1co/OpenMemories-Launcher",
  "featured": False,
  "github_repo": "ma1co/OpenMemories-Launcher",
 },
 "com.github.pyzahl.sofimagic": {
  "package": "com.github.pyzahl.sofimagic",
  "name": "SoFiMagic",
  "author": "pyzahl",
  "desc": "Solar eclipse automation and exposure bracketing",
  "version": "1.4.0",
  "url": "https://raw.githubusercontent.com/pyzahl/SoFiMagic/main/app/build/outputs/apk/debug/SoFiMagic-debug-1.4.0.apk",
  "homepage": "https://github.com/pyzahl/SoFiMagic",
  "featured": False,
 },
}


def getAllVerifiedApps():
 """Returns full catalog of all verified applications."""
 return copy.deepcopy(SEED_APPS)


class SyncResult(tuple):
 """Structured sync result providing rich metadata with backward-compatible 2-tuple unpacking and tuple inheritance."""
 def __new__(cls, catalog, updated=False, success=True, partial=False, errors=None, last_success=None, updated_count=0):
  obj = super(SyncResult, cls).__new__(cls, (catalog, updated))
  obj.catalog = catalog
  obj.updated = updated
  obj.success = success
  obj.partial = partial
  obj.errors = errors or []
  obj.last_success = last_success
  obj.updated_count = updated_count
  return obj

 def __repr__(self):
  return "<SyncResult success=%s partial=%s updated=%s errors=%d last_success=%s>" % (
   self.success, self.partial, self.updated, len(self.errors), self.last_success
  )


def getDefaultCachePath():
 base = os.path.expanduser("~/.cache/sony-pmca")
 os.makedirs(base, exist_ok=True)
 return os.path.join(base, "catalog-cache.json")


def loadCatalog(cachePath=None):
 """Load catalog from persistent cache using deep copy, falling back to seed.
 Preserves immutable package/catalog_id/author/compat provenance from curated seed,
 and ignores broken legacy cache entries (e.g. old FTP package or TimeLapse 0.2 404).
 """
 path = cachePath or getDefaultCachePath()
 catalog = copy.deepcopy(SEED_APPS)
 if os.path.isfile(path):
  try:
   with open(path, "r", encoding="utf-8") as f:
    cached = json.load(f)
    if isinstance(cached, dict) and "apps" in cached:
     for pkg_key, item in cached["apps"].items():
      if pkg_key in catalog:
       cached_ver = item.get("version")
       cached_url = item.get("url")
       # Reject known broken legacy cached entries
       if pkg_key == "com.jonasjuffinger.timelapse" and (cached_ver == "0.2" or (cached_url and "0.2" in str(cached_url))):
        continue
       if cached_ver and str(cached_ver).strip() and str(cached_ver) != "None":
        catalog[pkg_key]["version"] = str(cached_ver)
       if cached_url and isinstance(cached_url, str) and cached_url.startswith("https://"):
        if not (pkg_key == "com.jonasjuffinger.timelapse" and ("0.2" in cached_url or cached_ver == "0.2")):
         catalog[pkg_key]["url"] = cached_url
      elif isinstance(item, dict):
       catalog[pkg_key] = item
  except Exception:
   pass
 return catalog


def getCacheMetadata(cachePath=None):
 """Read catalog cache envelope metadata without mutating catalog."""
 path = cachePath or getDefaultCachePath()
 if os.path.isfile(path):
  try:
   with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
    if isinstance(data, dict):
     return {
      "last_sync_attempt": data.get("last_sync_attempt") or data.get("last_sync"),
      "last_successful_sync": data.get("last_successful_sync"),
     }
  except Exception:
   pass
 return {"last_sync_attempt": None, "last_successful_sync": None}


def saveCatalog(catalog, cachePath=None, last_success=None):
 """Atomically save catalog to persistent cache with timestamp, preserving prior last_success unless updated."""
 path = cachePath or getDefaultCachePath()
 if hasattr(catalog, 'catalog'):
  if last_success is None and hasattr(catalog, 'last_success'):
   last_success = catalog.last_success
  catalog = catalog.catalog
 existing_meta = getCacheMetadata(path)
 successful_ts = last_success if last_success is not None else existing_meta.get("last_successful_sync")
 now_iso = datetime.now(timezone.utc).isoformat()

 payload = {
  "last_sync_attempt": now_iso,
  "last_successful_sync": successful_ts,
  "apps": catalog,
 }
 partial = None
 try:
  dirName = os.path.dirname(path)
  os.makedirs(dirName, exist_ok=True)
  with tempfile.NamedTemporaryFile(dir=dirName, prefix=".catalog-", suffix=".json", delete=False, mode="w", encoding="utf-8") as f:
   partial = f.name
   json.dump(payload, f, indent=2)
  os.replace(partial, path)
  partial = None
 finally:
  if partial and os.path.exists(partial):
   try:
    os.unlink(partial)
   except OSError:
    pass


def syncCatalogMetadata(existingCatalog=None, timeout=10, abort_event=None, cachePath=None, force=False):
 """Fetch updated metadata for all catalog apps with bounded timeouts, rate limit fallback, and structured results."""
 catalog = copy.deepcopy(existingCatalog or loadCatalog(cachePath))
 meta = getCacheMetadata(cachePath)
 last_success = meta.get("last_successful_sync")

 if abort_event and abort_event.is_set():
  return SyncResult(catalog, updated=False, success=True, partial=False, errors=[], last_success=last_success)

 # Check hourly cache expiration if not forced
 if not force and last_success:
  try:
   dt = datetime.fromisoformat(last_success)
   age = (datetime.now(timezone.utc) - dt).total_seconds()
   if age < 3600:
    return SyncResult(catalog, updated=False, success=True, partial=False, errors=[], last_success=last_success)
  except Exception:
   pass

 context = ssl.create_default_context(cafile=certifi.where())
 opener = urllib_request.build_opener(HttpsRedirectHandler(), urllib_request.HTTPSHandler(context=context))
 headers = {
  "User-Agent": "Sony-A7-PMCA",
  "Accept": "application/vnd.github+json"
 }

 updated_any = False
 updated_count = 0
 errors = []
 rate_limited = False

 # Check each app with known github repo
 for pkg, app in list(catalog.items()):
  if abort_event and abort_event.is_set():
   break
  repo = app.get("github_repo")
  if not repo or rate_limited:
   continue

  api_url = "https://api.github.com/repos/%s/releases/latest" % repo
  try:
   req = urllib_request.Request(api_url, headers=headers)
   with opener.open(req, timeout=timeout) as resp:
    rel = json.load(resp)
    tag = rel.get("tag_name")
    if tag:
     old_ver = app.get("version")
     app["version"] = tag
     for asset in rel.get("assets", []):
      asset_name = asset.get("name", "")
      if asset_name.endswith(".apk") and asset.get("browser_download_url"):
       old_url = app.get("url")
       app["url"] = asset["browser_download_url"]
       if old_ver != tag or old_url != app["url"]:
        updated_any = True
        updated_count += 1
       break
  except urllib_error.HTTPError as e:
   if e.code == 403:
    rate_limited = True
    errors.append("GitHub API rate limit exceeded")
   elif e.code == 404:
    # No release published yet
    pass
   else:
    errors.append("%s: HTTP %d" % (pkg, e.code))
  except Exception as e:
   errors.append("%s: %s" % (pkg, str(e)))



 success = len(errors) == 0
 partial = len(errors) > 0 and (updated_count > 0 or not rate_limited)
 new_last_success = datetime.now(timezone.utc).isoformat() if success else last_success

 return SyncResult(
  catalog=catalog,
  updated=updated_any,
  success=success,
  partial=partial,
  errors=errors,
  last_success=new_last_success,
  updated_count=updated_count,
 )


def downloadCatalogApp(app, filename, progress=None, timeout=30):
 """Download and validate a catalog app APK with HTTPS verification, minSdk/cert check, and atomic file write."""
 path = os.path.abspath(filename)

 # Extract app metadata from dict or App object
 if isinstance(app, dict):
  package_name = app.get("package")
  app_name = app.get("name", package_name)
  url = app.get("url")
  version = app.get("version")
 else:
  package_name = getattr(app, "package", None)
  app_name = getattr(app, "name", package_name)
  release = getattr(app, "release", None)
  if not release:
   raise ValueError("No release found for %s" % app_name)
  url = getattr(release, "url", None)
  version = getattr(release, "version", None)

 if not url or not isinstance(url, str):
  raise ValueError("No download URL available for %s" % app_name)
 parsed = urlparse(url)
 if parsed.scheme != "https":
  raise ValueError("Release for %s has an invalid or insecure download URL (scheme must be HTTPS)" % app_name)

 context = ssl.create_default_context(cafile=certifi.where())
 opener = urllib_request.build_opener(HttpsRedirectHandler(), urllib_request.HTTPSHandler(context=context))
 headers = {"User-Agent": "Sony-A7-PMCA"}

 partial = None
 try:
  dirName = os.path.dirname(path)
  os.makedirs(dirName, exist_ok=True)
  with tempfile.NamedTemporaryFile(dir=dirName, prefix=".pmca-app-", suffix=".apk", delete=False) as f:
   partial = f.name
   downloaded = 0
   req = urllib_request.Request(url, headers=headers)
   with opener.open(req, timeout=timeout) as response:
    length = response.headers.get("Content-Length")
    total = int(length) if length is not None else None
    while True:
     chunk = response.read(64 * 1024)
     if not chunk:
      break
     f.write(chunk)
     downloaded += len(chunk)
     if progress is not None:
      progress(downloaded, total)
   if total is not None and downloaded != total:
    raise ValueError("Incomplete download for %s (%d of %d bytes)" % (app_name, downloaded, total))
   f.flush()
   f.seek(0)
   parser = ApkParser(f)
   parsed_pkg = parser.getPackageName()
   if package_name and parsed_pkg != package_name:
    raise ValueError("Package mismatch for %s: expected %s, got %s" % (app_name, package_name, parsed_pkg))
   sdk = parser.getMinSdkVersion()
   if not 1 <= sdk <= 10:
    raise ValueError("APK minimum Android SDK must be between 1 and 10 (got %s)" % sdk)
   cert = parser.getCert()
   if not cert:
    raise ValueError("APK signature certificate missing or invalid")
  os.replace(partial, path)
  partial = None
  return {
   "path": path,
   "package": parsed_pkg,
   "version": version or parser.getVersionName(),
   "bytes": downloaded,
   "name": app_name,
   "cert_len": len(cert),
  }
 finally:
  if partial is not None and os.path.exists(partial):
   try:
    os.unlink(partial)
   except OSError:
    pass
