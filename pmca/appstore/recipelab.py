import json
import os
import ssl
import tempfile
from urllib import request
from urllib.parse import urlparse

import certifi

from ..apk import ApkParser


class HttpsRedirectHandler(request.HTTPRedirectHandler):
 def redirect_request(self, req, fp, code, msg, headers, newurl):
  if urlparse(newurl).scheme != 'https':
   raise ValueError('RecipeLab redirects must remain HTTPS')
  return super().redirect_request(req, fp, code, msg, headers, newurl)


def downloadRecipeLab(filename, progress=None):
 """Download and validate RecipeLab; never install it or contact a camera."""
 path = os.path.abspath(filename)
 context = ssl.create_default_context(cafile=certifi.where())
 opener = request.build_opener(HttpsRedirectHandler(), request.HTTPSHandler(context=context))
 headers = {'User-Agent': 'Sony-A7-PMCA'}
 api = request.Request(
  'https://api.github.com/repos/voxivoid/recipe-lab-sony-pmca/releases/latest',
  headers=dict(headers, Accept='application/vnd.github+json'))
 with opener.open(api, timeout=30) as response:
  release = json.load(response)
 if release.get('draft') or release.get('prerelease'):
  raise ValueError('No latest stable RecipeLab release available')
 version = release['tag_name']
 assets = release.get('assets', [])
 candidates = [asset for asset in assets if asset.get('name') == 'RecipeLab.apk']
 if not candidates:
  candidates = [asset for asset in assets if asset.get('name', '').endswith('.apk')]
 if len(candidates) != 1:
  raise ValueError('RecipeLab release must contain one unambiguous APK asset')
 url = candidates[0].get('browser_download_url')
 if not isinstance(url, str) or not url.startswith(
  'https://github.com/voxivoid/recipe-lab-sony-pmca/releases/download/'):
  raise ValueError('Invalid RecipeLab APK download URL')

 partial = None
 try:
  with tempfile.NamedTemporaryFile(dir=os.path.dirname(path), prefix='.recipelab-',
   suffix='.apk', delete=False) as file:
   partial = file.name
   downloaded = 0
   with opener.open(request.Request(url, headers=headers), timeout=30) as response:
    length = response.headers.get('Content-Length')
    total = int(length) if length is not None else None
    while True:
     data = response.read(64 * 1024)
     if not data:
      break
     file.write(data)
     downloaded += len(data)
     if progress is not None:
      progress(downloaded, total)
   if total is not None and downloaded != total:
    raise ValueError('Incomplete RecipeLab APK download')
   file.flush()
   file.seek(0)
   parser = ApkParser(file)
   package = parser.getPackageName()
   if package != 'com.voxivoid.recipelab':
    raise ValueError('Unexpected RecipeLab APK package: %s' % package)
   sdk = parser.getMinSdkVersion()
   if not 1 <= sdk <= 10:
    raise ValueError('RecipeLab APK minimum SDK must be between 1 and 10 (got %s)' % sdk)
   try:
    cert = parser.getCert()
    if not cert:
     raise ValueError('RecipeLab APK signature certificate is empty')
   except Exception as e:
    raise ValueError('RecipeLab APK signature certificate missing or invalid: %s' % e)
  os.replace(partial, path)
  partial = None
  return {'path': path, 'version': version, 'package': package, 'bytes': downloaded}
 finally:
  if partial is not None:
   os.unlink(partial)
