"""Some methods to make HTTP requests"""

from collections import namedtuple
from urllib.parse import *
from urllib.request import *

class DownloadCancelledError(Exception):
 """Raised when an in-flight download operation is cancelled."""
 pass

HttpResponse = namedtuple('HttpResponse', 'url, data, raw_data, headers')

DEFAULT_TIMEOUT = 15

def get(url, data={}, headers={}, cookies={}, auth=None, timeout=DEFAULT_TIMEOUT):
 if data:
  url += '?' + urlencode(data)
 return request(url, None, headers, cookies, auth, timeout=timeout)

def post(url, data, headers={}, cookies={}, auth=None, timeout=DEFAULT_TIMEOUT):
 return request(url, data, headers, cookies, auth, timeout=timeout)

def request(url, data=None, headers={}, cookies={}, auth=None, timeout=DEFAULT_TIMEOUT):
 if cookies:
  headers['Cookie'] = '; '.join(quote(k) + '=' + quote(v) for (k, v) in cookies.items())
 if 'User-Agent' not in headers:
  headers['User-Agent'] = 'Sony-A7-PMCA'
 req = Request(str(url), data, headers)
 manager = HTTPPasswordMgrWithDefaultRealm()
 if auth:
  manager.add_password(None, req.get_full_url(), auth[0], auth[1])
 handlers = [HTTPBasicAuthHandler(manager), HTTPDigestAuthHandler(manager)]
 try:
  import certifi, ssl
  handlers.append(HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
 except:
  # App engine
  pass
 response = build_opener(*handlers).open(req, timeout=timeout)
 headers = dict(response.headers)
 raw_contents = response.read()
 contents = raw_contents.decode(headers.get('charset', 'latin1'))
 return HttpResponse(urlparse(response.geturl()), contents, raw_contents, headers)
