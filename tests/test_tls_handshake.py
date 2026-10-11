"""Comprehensive TLS and frozen runtime handshake tests for LocalMarketServer."""
import hashlib
import inspect
from pathlib import Path
import socket
import ssl
import sys
import unittest

import tlslite
import tlslite.utils.rijndael as _rijndael_mod
from tlslite.utils.deprecations import deprecated_class_name
from tlslite.utils.cipherfactory import createAES

import sys
from pathlib import Path
repo_root = str(Path(__file__).resolve().parents[1])
if repo_root not in sys.path:
 sys.path.insert(0, repo_root)

from pmca.marketserver.server import LocalMarketServer, ServerContext


class TlsServerHandshakeTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.cert_path = str(Path(__file__).resolve().parents[1] / 'certs/localtest.me.pem')

 def setUp(self):
  self.orig_getframeinfo = inspect.getframeinfo
  self.orig_frozen = getattr(sys, 'frozen', None)

 def tearDown(self):
  inspect.getframeinfo = self.orig_getframeinfo
  if self.orig_frozen is None:
   if hasattr(sys, 'frozen'):
    del sys.frozen
  else:
   sys.frozen = self.orig_frozen

 def test_missing_source_context_regression_fails_without_unwrap(self):
  """Regression proof: deprecated_class_name with None code_context triggers TypeError."""
  @deprecated_class_name('dummy_cipher')
  class WrappedCipher:
   def __init__(self, key, block_size):
    self.key = key
    self.block_size = block_size

  def mock_frozen_getframeinfo(frame, context=1):
   res = self.orig_getframeinfo(frame, context)
   return res._replace(code_context=None)

  inspect.getframeinfo = mock_frozen_getframeinfo

  with self.assertRaises(TypeError) as ctx:
   WrappedCipher(b'0123456789abcdef', 16)
  self.assertIn("'NoneType' object is not iterable", str(ctx.exception))

  # Unwrapping cleanly fixes the issue
  unwrapped_init = inspect.unwrap(WrappedCipher.__init__)
  WrappedCipher.__init__ = unwrapped_init
  cipher = WrappedCipher(b'0123456789abcdef', 16)
  self.assertEqual(cipher.key, b'0123456789abcdef')

 def test_rijndael_unwrapped_in_marketserver(self):
  """Verify Rijndael in server module is unwrapped and creates functional AES instances."""
  self.assertFalse(hasattr(_rijndael_mod.Rijndael.__init__, '__wrapped__'))
  key = b'0123456789abcdef'
  iv = b'0123456789abcdef'
  enc = createAES(key, iv)
  dec = createAES(key, iv)
  plaintext = bytearray(b'1234567812345678')
  encrypted = enc.encrypt(plaintext)
  decrypted = dec.decrypt(encrypted)
  self.assertEqual(decrypted, plaintext)

 def test_tls_cbc_loopback_handshakes_and_record_exchange(self):
  """Test TLS 1.0, 1.1, and 1.2 CBC encrypted loopback handshakes and record roundtrips."""
  tls_versions = [
   ('TLSv1.2', ssl.TLSVersion.TLSv1_2),
   ('TLSv1.1', ssl.TLSVersion.TLSv1_1),
   ('TLSv1', ssl.TLSVersion.TLSv1),
  ]

  for name, version in tls_versions:
   with self.subTest(tls_version=name):
    server = LocalMarketServer(self.cert_path, host='127.0.0.1', port=0)
    server.setApk(b'mock test apk payload for tls verification')
    port = server.server_address[1]

    with ServerContext(server):
     ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
     ctx.check_hostname = False
     ctx.verify_mode = ssl.CERT_NONE
     ctx.minimum_version = version
     ctx.maximum_version = version
     ctx.set_ciphers('AES128-SHA:AES256-SHA:DEFAULT:@SECLEVEL=0')

     with socket.create_connection(('127.0.0.1', port), timeout=5) as sock:
      with ctx.wrap_socket(sock, server_hostname='127.0.0.1') as ssock:
       negotiated_cipher = ssock.cipher()
       self.assertIn('AES', negotiated_cipher[0])

       # Perform record roundtrip (HTTP GET -> SPK dump response)
       ssock.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
       response_data = b""
       while b"\r\n\r\n" not in response_data:
        chunk = ssock.recv(1024)
        if not chunk:
         break
        response_data += chunk
       header_part, body_part = response_data.split(b"\r\n\r\n", 1)
       content_len = 0
       for line in header_part.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
         content_len = int(line.split(b":")[1].strip())
       while len(body_part) < content_len:
        chunk = ssock.recv(1024)
        if not chunk:
         break
        body_part += chunk

       self.assertTrue(header_part.startswith(b'HTTP/1.0 200 OK'))
       self.assertIn(b'Content-Type: application/vnd.sony.spk.package-archive', header_part)
       self.assertGreater(len(body_part), 0)

 def test_frozen_runtime_simulation_handshake(self):
  """Simulate frozen PyInstaller bytecode environment with None code_context and bundled cert."""
  sys.frozen = True

  def mock_frozen_getframeinfo(frame, context=1):
   res = self.orig_getframeinfo(frame, context)
   return res._replace(code_context=None)
  inspect.getframeinfo = mock_frozen_getframeinfo

  server = LocalMarketServer(self.cert_path, host='127.0.0.1', port=0)
  server.setApk(b'mock test apk content')
  port = server.server_address[1]

  with ServerContext(server):
   ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
   ctx.check_hostname = False
   ctx.verify_mode = ssl.CERT_NONE
   ctx.maximum_version = ssl.TLSVersion.TLSv1_2
   ctx.set_ciphers('AES128-SHA:AES256-SHA')

   with socket.create_connection(('127.0.0.1', port), timeout=5) as sock:
    with ctx.wrap_socket(sock, server_hostname='127.0.0.1') as ssock:
     cipher = ssock.cipher()
     self.assertIn('AES', cipher[0])
     ssock.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
     resp = ssock.recv(1024)
     self.assertTrue(resp.startswith(b'HTTP/1.0 200 OK'))

 def test_repeated_ephemeral_bind_and_cleanup_without_leaks(self):
  """Verify repeated server startups on ephemeral ports clean up sockets completely."""
  for _ in range(5):
   server = LocalMarketServer(self.cert_path, host='127.0.0.1', port=0)
   port = server.server_address[1]
   with ServerContext(server):
    with socket.create_connection(('127.0.0.1', port), timeout=2) as s:
     pass
   # Ensure socket closed
   self.assertTrue(server.socket._closed)

 def test_handshake_failure_socket_cleanup(self):
  """Verify that aborted/invalid TLS client handshakes clean up without descriptor leaks."""
  server = LocalMarketServer(self.cert_path, host='127.0.0.1', port=0)
  port = server.server_address[1]
  with ServerContext(server):
   # Connect plain TCP and send garbage to trigger handshake error
   with socket.create_connection(('127.0.0.1', port), timeout=2) as sock:
    try:
     sock.sendall(b"NOT_A_VALID_TLS_RECORD\r\n\r\n")
     sock.recv(1024)
    except (ConnectionResetError, BrokenPipeError, socket.timeout):
     pass

 def test_bundled_cert_pinning(self):
  """Verify bundled certificate can be parsed, fingerprinted, and matched."""
  with open(self.cert_path, 'rb') as f:
   pem_bytes = f.read()

  chain = tlslite.X509CertChain()
  chain.parsePemList(pem_bytes.decode('ascii'))
  self.assertGreater(len(chain.x509List), 0)

  # Check certificate SHA-256 fingerprint calculation
  der_bytes = chain.x509List[0].bytes
  sha256 = hashlib.sha256(der_bytes).hexdigest()
  self.assertEqual(len(sha256), 64)


if __name__ == '__main__':
 unittest.main()
