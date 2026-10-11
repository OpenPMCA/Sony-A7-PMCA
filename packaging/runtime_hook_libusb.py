"""Resolve frozen libusb from the bundle, without requiring system linker tools."""
import ctypes.util
from pathlib import Path
import sys


def find_bundled_library(name, directory):
 if name not in ('usb-1.0', 'libusb-1.0', 'usb'):
  return None
 root = Path(directory)
 for filename in ('libusb-1.0.dll', 'libusb-1.0.so.0', 'libusb-1.0.so', 'libusb-1.0.dylib'):
  path = root / filename
  if path.is_file():
   return str(path)
 for path in sorted(root.glob('libusb-1.0.so.*')):
  if path.is_file():
   return str(path)
 return None


if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
 from usb.backend import libusb1
 _load_library = libusb1._load_library

 def _bundle_find(name):
  return find_bundled_library(name, sys._MEIPASS) or ctypes.util.find_library(name)

 def _load_bundled_libusb(find_library=None):
  return _load_library(find_library=find_library or _bundle_find)

 libusb1._load_library = _load_bundled_libusb
