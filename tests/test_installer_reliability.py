"""Tests for installer loop pacing, socket cleanup, ephemeral port fallback, and CameraOperationError."""
import contextlib
import io
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

repo_root = str(Path(__file__).resolve().parents[1])
if repo_root not in sys.path:
 sys.path.insert(0, repo_root)

from pmca import installer
from pmca.commands import usb
from pmca.marketserver.server import LocalMarketServer, ServerContext
from pmca.usb import MtpDeviceInfo
from pmca.usb.sony import (
 InitResponseMessage,
 RequestMessage,
 ResponseMessage,
 SonyAppInstallCamera,
 SslEndMessage,
 SslSendDataMessage,
 SslStartMessage,
)
from tests.apk_fixture import apkFixture


def _make_rest_response(code=0, message='ok'):
 import json
 body = json.dumps({'resultCode': code, 'message': message}).encode('latin1')
 return b'REST/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n' + body


def _make_rest_request(url, payload_dict):
 import json
 body = json.dumps(payload_dict).encode('latin1')
 return b'POST ' + url.encode('latin1') + b' REST/1.0\r\nContent-Type: application/json\r\n\r\n' + body


class FakeClock:
 def __init__(self, start=100.0, step=0.0):
  self.now = start
  self.step = step
  self.sleeps = []

 def monotonic(self):
  val = self.now
  self.now += self.step
  return val

 def sleep(self, seconds):
  self.sleeps.append(seconds)
  self.now += seconds


class InstallerReliabilityTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.valid_apk = apkFixture(package='com.voxivoid.recipelab', minSdk=10, signed=True)

 def setUp(self):
  usb.set_camera_busy(False)
  usb.set_last_verified_camera_status(None)

 def test_installer_loop_paces_nodata_and_times_out_when_stalled(self):
  """Verify installer.install sleeps on None receive and times out via monotonic clock instead of spinning forever."""
  clock = FakeClock(start=0.0)
  dev = Mock()
  dev.sendRequest.return_value = _make_rest_response(0, 'ok')
  dev.receive.return_value = None

  with patch.object(installer, '_monotonic', side_effect=clock.monotonic, create=True), \
       patch.object(installer, '_sleep', side_effect=clock.sleep, create=True):
   with self.assertRaises(TimeoutError) as ctx:
    installer.install(dev, '127.0.0.1', 4443, b'xpd')
  self.assertIn('timed out', str(ctx.exception).lower())
  self.assertGreater(len(clock.sleeps), 0)

 def test_installer_progress_extends_activity_deadline_without_false_timeout(self):
  """Verify legitimate slow camera installation with progress heartbeats does not hit idle timeout."""
  clock = FakeClock(start=0.0)
  dev = Mock()
  dev.sendRequest.return_value = _make_rest_response(0, 'ok')

  # 5 cycles of 10s NoData separated by progress updates (50s total > 30s idle limit), then complete
  events = []
  for pct in (20, 40, 60, 80):
   events.extend([None] * 10)
   events.append(RequestMessage(_make_rest_request('/task/progress', {
    'status': 1, 'status text': 'Installing', 'percent': pct, 'total size': 100
   })))
  events.append(RequestMessage(_make_rest_request('/task/complete', {
   'resultCode': 0, 'message': 'Successfully completed'
  })))
  dev.receive.side_effect = events

  # Advance 1.5s per sleep so 10 sleeps = 15s (< 30s idle timeout), but total = 60s
  def fake_sleep(s):
   clock.sleeps.append(s)
   clock.now += 1.5

  progress_seen = []
  with patch.object(installer, '_monotonic', side_effect=clock.monotonic, create=True), \
       patch.object(installer, '_sleep', side_effect=fake_sleep, create=True):
   res = installer.install(dev, '127.0.0.1', 4443, b'xpd', statusFunc=lambda st: progress_seen.append(st.percent))

  self.assertEqual(res.code, 0)
  self.assertEqual(progress_seen, [20, 40, 60, 80])
  dev.sendEnd.assert_called_once()

 def test_installer_handles_eof_once_uses_sendall_and_closes_socket_on_error(self):
  """Verify relay socket uses sendall, sends sendSslEnd once on EOF, and always closes sock in finally."""
  dev = Mock()
  dev.sendRequest.return_value = _make_rest_response(0, 'ok')
  dev.receive.side_effect = [
   SslStartMessage(7, 'localtest.me', 443),
   SslSendDataMessage(7, b'client-hello'),
   None, # triggers select -> server data
   None, # triggers select -> server EOF
   RuntimeError('Simulated USB disconnect mid-install'),
  ]

  fake_sock = Mock()
  # First recv returns payload, second recv returns EOF b''
  fake_sock.recv.side_effect = [b'server-hello', b'']

  with patch('socket.socket', return_value=fake_sock), \
       patch('select.select', return_value=([fake_sock], [], [])), \
       patch.object(installer, '_sleep', Mock(), create=True):
   with self.assertRaises(RuntimeError):
    installer.install(dev, '127.0.0.1', 4443, b'xpd')

  fake_sock.connect.assert_called_once_with(('127.0.0.1', 4443))
  fake_sock.sendall.assert_called_once_with(b'client-hello')
  dev.sendSslData.assert_called_once_with(7, b'server-hello')
  # EOF must trigger sendSslEnd exactly once and close the socket immediately
  dev.sendSslEnd.assert_called_once_with(7)
  self.assertGreaterEqual(fake_sock.close.call_count, 1)

 def test_local_market_server_ephemeral_port_succeeds_when_4443_is_occupied(self):
  """Verify installer LocalMarketServer(port=0) succeeds on a non-4443 ephemeral port when 4443 is occupied."""
  cert_file = str(Path(repo_root) / 'certs/localtest.me.pem')
  blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  try:
   try:
    blocker.bind(('127.0.0.1', 4443))
    blocker.listen(1)
   except OSError:
    # Port 4443 is already occupied on this host
    pass
   with ServerContext(LocalMarketServer(cert_file, host='127.0.0.1', port=0)) as server:
    bound_host, bound_port = server.server_address
    self.assertEqual(bound_host, '127.0.0.1')
    self.assertGreater(bound_port, 0)
    self.assertNotEqual(bound_port, 4443)
    self.assertIsNotNone(server.certChain)
    self.assertIsNotNone(server.privateKey)
  finally:
   blocker.close()

 def test_local_market_server_falls_back_to_ephemeral_port_when_4443_is_occupied(self):
  """Verify LocalMarketServer default port=4443 falls back to real ephemeral port 0 on EADDRINUSE."""
  import errno
  import socketserver
  cert_file = str(Path(repo_root) / 'certs/localtest.me.pem')
  real_tcp_init = socketserver.TCPServer.__init__
  attempted_addresses = []

  def fake_first_eaddrinuse(srv, server_address, RequestHandlerClass, bind_and_activate=True):
   attempted_addresses.append(server_address)
   if len(attempted_addresses) == 1:
    raise OSError(errno.EADDRINUSE, 'Address already in use')
   return real_tcp_init(srv, server_address, RequestHandlerClass, bind_and_activate=bind_and_activate)

  with patch.object(socketserver.TCPServer, '__init__', autospec=True, side_effect=fake_first_eaddrinuse):
   with ServerContext(LocalMarketServer(cert_file, host='127.0.0.1', port=4443)) as server:
    bound_host, bound_port = server.server_address
    self.assertEqual(bound_host, '127.0.0.1')
    self.assertGreater(bound_port, 0)
    self.assertIsNotNone(server.certChain)
    self.assertIsNotNone(server.privateKey)

  self.assertEqual(attempted_addresses, [('127.0.0.1', 4443), ('127.0.0.1', 0)])

 def test_local_market_server_reraises_non_eaddrinuse_os_error(self):
  """Verify LocalMarketServer re-raises non-EADDRINUSE errors such as EACCES or invalid address."""
  import errno
  cert_file = str(Path(repo_root) / 'certs/localtest.me.pem')
  with patch('socketserver.TCPServer.__init__', side_effect=OSError(errno.EACCES, 'Permission denied')):
   with self.assertRaises(OSError) as ctx:
    LocalMarketServer(cert_file, host='127.0.0.1', port=4443)
   self.assertEqual(ctx.exception.errno, errno.EACCES)

 def test_install_command_runs_check_apk_once_and_does_not_duplicate_output(self):
  """Verify installCommand validates APK once before mode switch and does not re-validate inside installApp."""
  dev = object.__new__(usb.SonyMtpAppInstallDevice)
  dev.getDeviceInfo = Mock(return_value=MtpDeviceInfo(
   'Sony Corporation', 'ILCE-7', '1234567',
   {0x9488, 0x9489, 0x948c, 0x948d}, 'sony.net/SEN_PRXY_MSG:1.0'))
  server = Mock()
  server.server_address = ('127.0.0.1', 54321)
  server.getXpd.return_value = b'xpd'
  server.getResult.return_value = {'deviceinfo': {'name': 'ILCE-7'}, 'applications': [{'name': 'RecipeLab', 'version': '1.6.2'}]}

  out = io.StringIO()
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(None)), \
       patch.object(usb, 'getDevice', return_value=dev), \
       patch.object(usb, 'LocalMarketServer', return_value=server), \
       patch.object(usb, 'ServerContext', return_value=contextlib.nullcontext(server)), \
       patch.object(usb.installer, 'install', return_value=SimpleNamespace(code=0, message='ok')), \
       contextlib.redirect_stdout(out):
   res = usb.installCommand('libusb-mtp', apkFile=io.BytesIO(self.valid_apk))

  self.assertEqual(res['deviceinfo']['name'], 'ILCE-7')
  self.assertEqual(out.getvalue().count('Analyzing apk'), 1)

 def test_install_app_rejects_corrupt_apk_before_starting_local_market_server(self):
  """Verify direct installApp call validates APK before instantiating LocalMarketServer."""
  with patch.object(usb, 'LocalMarketServer') as server_cls:
   with self.assertRaises(ValueError):
    usb.installApp(Mock(), apkFile=io.BytesIO(b'corrupt-not-an-apk'))
   server_cls.assert_not_called()

 def test_install_app_rejects_empty_apk_stream_before_server_startup(self):
  """Verify supplying an explicit empty APK stream (BytesIO(b'')) raises ValueError before starting LocalMarketServer."""
  with patch.object(usb, 'LocalMarketServer') as server_cls:
   with self.assertRaises(ValueError) as ctx:
    usb.installApp(Mock(), apkFile=io.BytesIO(b''))
   self.assertIn('APK', str(ctx.exception))
   server_cls.assert_not_called()

 def test_install_command_rejects_empty_apk_stream_before_driver_or_mode_switch(self):
  """Verify supplying an explicit empty APK stream to installCommand fails validation before opening drivers or mode switch."""
  camera = Mock()
  with patch.object(usb, 'importDriver') as driver_cls, \
       patch.object(usb, 'SonyExtCmdCamera', return_value=camera):
   with self.assertRaises(ValueError) as ctx:
    usb.installCommand('libusb-mtp', apkFile=io.BytesIO(b''))
   self.assertIn('APK', str(ctx.exception))
   driver_cls.assert_not_called()
   camera.switchToAppInstaller.assert_not_called()

 def test_install_app_missing_portal_ack_raises_camera_operation_error_outcome_unknown(self):
  """Verify missing server.getResult() acknowledgment raises CameraOperationError with outcome_unknown=True."""
  server = Mock()
  server.server_address = ('127.0.0.1', 54321)
  server.getXpd.return_value = b'xpd'
  server.getResult.side_effect = Exception('Task was not completed')

  with patch.object(usb, 'LocalMarketServer', return_value=server), \
       patch.object(usb, 'ServerContext', return_value=contextlib.nullcontext(server)), \
       patch.object(usb.installer, 'install', return_value=SimpleNamespace(code=0, message='ok')), \
       contextlib.redirect_stdout(io.StringIO()):
   with self.assertRaises(usb.CameraOperationError) as ctx:
    usb.installApp(Mock(), apkFile=io.BytesIO(self.valid_apk))

  self.assertTrue(ctx.exception.outcome_unknown)
  self.assertEqual(ctx.exception.phase, 'completion')

 def test_install_command_missing_device_and_mode_timeout_raise_camera_operation_error(self):
  """Verify missing device and mode-switch timeout raise actionable CameraOperationError with outcome_unknown=False."""
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(None)), \
       patch.object(usb, 'getDevice', return_value=None), \
       contextlib.redirect_stdout(io.StringIO()):
   with self.assertRaises(usb.CameraOperationError) as ctx:
    usb.installCommand('libusb-mtp', apkFile=io.BytesIO(self.valid_apk))
  self.assertFalse(ctx.exception.outcome_unknown)
  self.assertEqual(ctx.exception.phase, 'discovery')

  # Mode-switch timeout
  ext_dev = object.__new__(usb.SonyMtpExtCmdDevice)
  ext_dev.getDeviceInfo = Mock(return_value=MtpDeviceInfo(
   'Sony Corporation', 'ILCE-7', '1234567', {0x9280, 0x9281, 0x9282}, ''))
  camera = Mock()
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(None)), \
       patch.object(usb, 'getDevice', return_value=ext_dev), \
       patch.object(usb, 'SonyExtCmdCamera', return_value=camera), \
       patch.object(usb, 'listDevices', return_value=[]), \
       patch.object(usb.time, 'sleep'), \
       contextlib.redirect_stdout(io.StringIO()):
   with self.assertRaises(usb.CameraOperationError) as ctx:
    usb.installCommand('libusb-mtp', apkFile=io.BytesIO(self.valid_apk))
  self.assertFalse(ctx.exception.outcome_unknown)
  self.assertEqual(ctx.exception.phase, 'mode_switch')

 def test_readonly_camera_info_msc_firmware_unavailable_text_and_cold_cache_info_command(self):
  """Verify MSC read-only firmware fallback says Mass Storage (not MTP) and infoCommand updates cold cache."""
  msc_dev = object.__new__(usb.SonyMscExtCmdDevice)
  camera = Mock()
  camera.getCameraInfo.return_value = SimpleNamespace(modelName='ILCE-7', modelCode='code', serial='serial1', plist=b'')
  camera.getLensInfo.return_value = SimpleNamespace(model=0)
  camera.getGpsData.side_effect = usb.InvalidCommandException()
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(None)), \
       patch.object(usb, 'getDevice', return_value=msc_dev), \
       patch.object(usb, 'SonyExtCmdCamera', return_value=camera):
   props = usb.getReadOnlyCameraInfo('libusb')
  self.assertEqual(props['USB mode'], 'Mass Storage')
  self.assertEqual(props['Firmware version'], 'Unavailable (read-only Mass Storage)')

  # Cold cache infoCommand populates verified firmware and serial
  usb.set_last_verified_camera_status(None)
  mtp_dev = object.__new__(usb.SonyMtpExtCmdDevice)
  mtp_dev.getDeviceInfo = Mock(return_value=MtpDeviceInfo(
   'Sony Corporation', 'ILCE-7', 'transport-serial-1', {0x9280, 0x9281, 0x9282}, '', version='1.0'))
  updater = Mock()
  updater.getFirmwareVersion.return_value = ('3.20', '3.20')
  with patch.object(usb, 'importDriver', return_value=contextlib.nullcontext(None)), \
       patch.object(usb, 'getDevice', return_value=mtp_dev), \
       patch.object(usb, 'SonyExtCmdCamera', return_value=camera), \
       patch.object(usb, 'SonyUpdaterCamera', return_value=updater), \
       contextlib.redirect_stdout(io.StringIO()):
   info_props = usb.infoCommand('libusb-mtp')
  self.assertEqual(info_props['Firmware version'], '3.20')
  cached = usb.get_last_verified_camera_status()
  self.assertIsNotNone(cached)
  self.assertEqual(cached['firmware_version'], '3.20')
  self.assertEqual(cached['serial'], 'serial1')


if __name__ == '__main__':
 unittest.main()
