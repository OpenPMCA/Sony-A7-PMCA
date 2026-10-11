"""Behavior regressions for standalone native desktop dependencies."""
import importlib.util
import os
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(path, name):
 spec = importlib.util.spec_from_file_location(name, path)
 result = importlib.util.module_from_spec(spec)
 spec.loader.exec_module(result)
 return result


class StandaloneLibraryTest(unittest.TestCase):
 def test_windows_legacy_libusb_does_not_satisfy_libusb1_dependency(self):
  build = module(ROOT / 'packaging/build.py', 'packaging_build_test')
  with TemporaryDirectory() as directory:
   (Path(directory) / 'libusb0.dll').write_bytes(b'legacy API 0.1')
   with patch.dict('sys.modules', {'libusb_package': None}), \
        patch.object(build.ctypes.util, 'find_library', return_value=None), \
        patch.dict(os.environ, {'PATH': directory}):
    with self.assertRaisesRegex(RuntimeError, 'libusb'):
     build.find_libusb('win32')

 def test_bundle_library_resolver_works_without_system_lookup(self):
  path = ROOT / 'packaging/runtime_hook_libusb.py'
  self.assertTrue(path.exists(), 'A frozen USB resolver must load bundled libusb without ldconfig/gcc')
  hook = module(path, 'libusb_hook_test')
  with TemporaryDirectory() as directory:
   expected = Path(directory) / 'libusb-1.0.so.0'
   expected.write_bytes(b'library path fixture')
   self.assertEqual(hook.find_bundled_library('usb-1.0', directory), str(expected))
   self.assertIsNone(hook.find_bundled_library('unrelated', directory))

 def test_bundle_library_resolver_ignores_legacy_windows_dll(self):
  path = ROOT / 'packaging/runtime_hook_libusb.py'
  self.assertTrue(path.exists(), 'A frozen USB resolver must reject API 0.1 DLLs')
  hook = module(path, 'libusb_hook_legacy_test')
  with TemporaryDirectory() as directory:
   (Path(directory) / 'libusb0.dll').write_bytes(b'legacy API 0.1')
   self.assertIsNone(hook.find_bundled_library('usb-1.0', directory))

 def test_desktop_analysis_installs_bundle_usb_hook(self):
  analyses = []
  def analysis(*args, **kwargs):
   analyses.append(kwargs)
   return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])
  with TemporaryDirectory() as directory:
   library = Path(directory) / 'libusb-1.0.so.0'
   library.write_bytes(b'library path fixture')
   with patch('sys.platform', 'linux'), \
        patch('ctypes.util.find_library', return_value=str(library)):
    runpy.run_path(str(ROOT / 'packaging/desktop.spec'), init_globals={
     'SPECPATH': str(ROOT / 'packaging'), 'Analysis': analysis,
     'PYZ': lambda *args, **kwargs: None,
     'EXE': lambda *args, **kwargs: None,
     'COLLECT': lambda *args, **kwargs: None,
    })
  self.assertEqual(len(analyses), 1)
  self.assertIn(str(ROOT / 'packaging/runtime_hook_libusb.py'), analyses[0].get('runtime_hooks', []))


 def test_runtime_hook_loads_bundled_path_and_respects_explicit_finder(self):
  hook_path = ROOT / 'packaging/runtime_hook_libusb.py'
  calls = []
  fake = SimpleNamespace(_load_library=lambda find_library=None: calls.append(find_library('usb-1.0')) or calls[-1])
  with TemporaryDirectory() as directory:
   library = Path(directory) / 'libusb-1.0.so.0.3.0'
   library.write_bytes(b'library path fixture')
   with patch('sys.frozen', True, create=True), patch('sys._MEIPASS', directory, create=True), \
        patch.dict('sys.modules', {'usb.backend.libusb1': fake}), \
        patch('usb.backend.libusb1', fake, create=True), \
        patch('ctypes.util.find_library', side_effect=AssertionError('System lookup is unavailable')):
    runpy.run_path(str(hook_path))
    self.assertEqual(fake._load_library(), str(library))
    self.assertEqual(fake._load_library(find_library=lambda name: 'explicit user backend'), 'explicit user backend')

 def test_mac_minimum_comes_from_highest_dependency_not_bootloader(self):
  build = module(ROOT / 'packaging/build.py', 'mac_minimum_test')
  with TemporaryDirectory() as directory:
   app = Path(directory)
   binary = app / 'Contents/MacOS/Sony Open PMCA'
   library = app / 'Contents/Frameworks/libtcl9.1.dylib'
   binary.parent.mkdir(parents=True); library.parent.mkdir(parents=True)
   binary.write_bytes(b'bootloader'); library.write_bytes(b'framework')
   def otool(args, **kwargs):
    value = '27.0' if args[-1] == str(library) else '11.0'
    return ('cmd LC_BUILD_VERSION\n platform 1\n minos ' + value + '\n sdk 27.0\nLoad command 8\n cmd LC_ID_DYLIB\n version 27037.1\n').encode()
   self.assertTrue(hasattr(build, 'get_macos_minimum'), 'Package minimum OS must include bundled frameworks')
   with patch.object(build.subprocess, 'check_output', side_effect=otool):
    self.assertEqual(build.get_macos_minimum(app), '27.0')

 def test_cask_rejects_macos_older_than_its_frameworks(self):
  build = module(ROOT / 'packaging/build.py', 'mac_cask_minimum_test')
  import inspect
  self.assertIn('min_macos', inspect.signature(build.render_cask).parameters)
  content = build.render_cask(version='1.0.0', sha256_hex='a' * 64, min_macos='27.0')
  self.assertIn('depends_on macos: :golden_gate', content)


if __name__ == '__main__':
 unittest.main()
