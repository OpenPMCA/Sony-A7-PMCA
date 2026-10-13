import errno
import sys
import contextlib
from http.server import BaseHTTPRequestHandler
import inspect
from socketserver import TCPServer
from threading import Thread
import tlslite

# Protect tlslite against None code_context in frozen PyInstaller
# tlslite-ng 0.8.2 wraps Rijndael.__init__ with @deprecated_class_name('rijndael').
# In frozen runtimes (PyInstaller bytecode without source files), inspect.getframeinfo().code_context
# returns None, causing tlslite/utils/deprecations.py to fail with TypeError iterating None.
# Unwrapping Rijndael.__init__ strips the deprecation wrapper cleanly while preserving crypto.
try:
 import tlslite.utils.rijndael as _rijndael_mod
 if hasattr(_rijndael_mod, 'Rijndael'):
  _rijndael_mod.Rijndael.__init__ = inspect.unwrap(_rijndael_mod.Rijndael.__init__)
  _rijndael_mod.rijndael = _rijndael_mod.Rijndael
except Exception:
 pass


from . import *
from .. import spk


class HttpHandler(BaseHTTPRequestHandler):
 rbufsize = -1
 wbufsize = -1

 def log_request(self, code='-', size='-'):
  pass

 def output(self, mimeType, data, filename=None):
  self.send_response(200)
  self.send_header('Connection', 'Keep-Alive')
  self.send_header('Content-Type', mimeType)
  self.send_header('Content-Length', len(data))
  if filename:
   self.send_header('Content-Disposition', 'attachment;filename="%s"' % filename)
  self.end_headers()
  self.wfile.write(data)

 def do_POST(self):
  self.server.handlePost(self, self.rfile.read(int(self.headers['Content-Length'])))

 def do_GET(self):
  self.server.handleGet(self)


class TLSConnection(tlslite.TLSConnection):
 def recv_into(self, b):
  return super(TLSConnection, self).recv_into(b) or 0


class LocalMarketServer(TCPServer):
 """A local https server to communicate with the camera"""
 allow_reuse_address = True

 def __init__(self, certFile, host='127.0.0.1', port=4443):
  try:
   super(LocalMarketServer, self).__init__((host, port), HttpHandler)
  except OSError as e:
   if e.errno != errno.EADDRINUSE or port == 0:
    raise
   super(LocalMarketServer, self).__init__((host, 0), HttpHandler)
  self.url = 'https://' + host + '/'
  self.apk = None
  self.result = None

  with open(certFile) as f:
   cert = f.read()
  self.certChain = tlslite.X509CertChain()
  self.certChain.parsePemList(cert)
  self.privateKey = tlslite.parsePEMKey(cert, private=True)

 def finish_request(self, sock, client_address):
  tls_sock = TLSConnection(sock)
  try:
   tls_sock.handshakeServer(certChain=self.certChain, privateKey=self.privateKey)
   super(LocalMarketServer, self).finish_request(tls_sock, client_address)
  except (ConnectionResetError, BrokenPipeError, tlslite.errors.TLSError):
   pass
  finally:
   try:
    tls_sock.close()
   except Exception:
    pass
   try:
    sock.close()
   except Exception:
    pass

 def startup(self):
  """Start the local server"""
  self._thread = Thread(target=self.serve_forever)
  self._thread.daemon = True
  self._thread.start()

 def close(self):
  """Shutdown server loop and close listening socket"""
  self.shutdown()
  self.server_close()

 def setApk(self, apkData):
  self.apk = apkData

 def getXpd(self):
  """Return the xpd contents"""
  return getXpdResponse('0', constants.baseUrl)

 def getResult(self):
  """Return the result sent from the camera"""
  if not self.result:
   raise Exception('Task was not completed')
  return self.result

 def handlePost(self, handler, body):
  """Handle POST requests to the server"""
  if not self.result and self.apk:
   # Tell the camera to download and install an app
   response = getJsonInstallResponse('app', self.url)
  else:
   response = getJsonResponse()

  self.result = parsePostData(body)# Save the result sent by the camera
  handler.output(constants.jsonMimeType, response)

 def handleGet(self, handler):
  """Handle GET requests to the server"""
  # Send the spk file to the camera
  handler.output(spk.constants.mimeType, spk.dump(self.apk), 'app%s' % spk.constants.extension)


class ServerContext(contextlib.AbstractContextManager):
 """Use this in a with statement"""
 def __init__(self, server):
  self._server = server

 def __enter__(self):
  self._server.startup()
  return self._server

 def __exit__(self, type, value, traceback):
  self._server.shutdown()
  self._server.server_close()


def verify_tls_handshake(certFile=None, host='127.0.0.1', timeout=5):
 """Perform a self-contained local TLS handshake and record exchange to verify cipher and runtime integrity."""
 import os
 import socket
 import ssl
 if not certFile:
  base_dir = getattr(sys, '_MEIPASS', os.path.dirname(__file__) + '/../..')
  certFile = os.path.join(base_dir, 'certs/localtest.me.pem')
 server = LocalMarketServer(certFile, host=host, port=0)
 server.setApk(b'mock runtime verification payload')
 port = server.server_address[1]
 try:
  with ServerContext(server):
   ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
   ctx.check_hostname = False
   ctx.verify_mode = ssl.CERT_NONE
   ctx.maximum_version = ssl.TLSVersion.TLSv1_2
   ctx.set_ciphers('AES128-SHA:AES256-SHA:DEFAULT:@SECLEVEL=0')
   with socket.create_connection((host, port), timeout=timeout) as sock:
    with ctx.wrap_socket(sock, server_hostname=host) as ssock:
     cipher = ssock.cipher()
     ssock.sendall(b"GET / HTTP/1.1\r\nHost: " + host.encode('ascii') + b"\r\nConnection: close\r\n\r\n")
     resp = ssock.recv(1024)
     return {
      'success': resp.startswith(b'HTTP/1.0 200 OK'),
      'cipher': cipher[0] if cipher else None,
      'version': ssock.version(),
      'port': port,
     }
 except Exception as e:
  return {
   'success': False,
   'error': str(e),
   'cipher': None,
   'version': None,
   'port': port if 'port' in locals() else None,
  }
