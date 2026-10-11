from axmlparserpy.axmlprinter import AXMLPrinter
import axmlparserpy.stringblock
from axmlparserpy.bytecode import SV
from asn1crypto.cms import ContentInfo
from xml.dom import minidom
from zipfile import ZipFile

# Transparently patch StringBlock to handle both UTF-8 (flags 0x100) and UTF-16 string pools
def _patched_string_block_init(self, buff):
 buff.read(4)
 self.chunkSize = SV('<L', buff.read(4))
 self.stringCount = SV('<L', buff.read(4))
 self.styleOffsetCount = SV('<L', buff.read(4))
 self.flags = SV('<L', buff.read(4))
 self.stringsOffset = SV('<L', buff.read(4))
 self.stylesOffset = SV('<L', buff.read(4))

 self.is_utf8 = bool(self.flags.get_value() & 0x100)

 self.m_stringOffsets = []
 self.m_stylesOffsets = []
 self.m_strings = []
 self.m_styles = []

 for i in range(0, self.stringCount.get_value()):
  self.m_stringOffsets.append(SV('<L', buff.read(4)))

 for i in range(0, self.styleOffsetCount.get_value()):
  self.m_stylesOffsets.append(SV('<L', buff.read(4)))

 size = self.chunkSize.get_value() - self.stringsOffset.get_value()
 if self.stylesOffset.get_value() != 0:
  size = self.stylesOffset.get_value() - self.stringsOffset.get_value()

 self.raw_strings_bytes = buff.read(size)

 if not self.is_utf8:
  for i in range(0, int(size / 4)):
   self.m_strings.append(SV('=L', self.raw_strings_bytes[i*4 : (i+1)*4]))

 if self.stylesOffset.get_value() != 0:
  size = self.chunkSize.get_value() - self.stringsOffset.get_value()
  for i in range(0, int(size / 4)):
   self.m_styles.append(SV('=L', buff.read(4)))

def _patched_string_block_get_raw(self, idx):
 if idx < 0 or not self.m_stringOffsets or idx >= len(self.m_stringOffsets):
  return None
 offset = self.m_stringOffsets[idx].get_value()
 if getattr(self, 'is_utf8', False):
  raw = self.raw_strings_bytes
  if offset >= len(raw):
   return ""
  pos = offset
  u16len = raw[pos]
  if u16len & 0x80:
   if pos + 1 < len(raw):
    u16len = ((u16len & 0x7F) << 8) | raw[pos + 1]
    pos += 2
   else:
    return ""
  else:
   pos += 1
  if pos >= len(raw):
   return ""
  u8len = raw[pos]
  if u8len & 0x80:
   if pos + 1 < len(raw):
    u8len = ((u8len & 0x7F) << 8) | raw[pos + 1]
    pos += 2
   else:
    return ""
  else:
   pos += 1
  data_bytes = raw[pos : pos + u8len]
  data = data_bytes.decode('utf-8', 'replace')
  if data.endswith('&'):
   data = data[:-1]
  return data
 else:
  length = self.getShort(self.m_strings, offset)
  data = ""
  while length > 0:
   offset += 2
   data += chr(self.getShort(self.m_strings, offset))
   if data and data[-1] == "&":
    data = data[:-1]
   length -= 1
  return data

axmlparserpy.stringblock.StringBlock.__init__ = _patched_string_block_init
axmlparserpy.stringblock.StringBlock.getRaw = _patched_string_block_get_raw


class ApkParser:
 def __init__(self, file):
  self._file = ZipFile(file)

 def getManifest(self):
  return minidom.parseString(AXMLPrinter(self._file.read('AndroidManifest.xml')).getBuff())

 def getPackageName(self):
  return self.getManifest().documentElement.getAttribute('package')

 def getVersionCode(self):
  return int(self.getManifest().documentElement.getAttribute('android:versionCode'))

 def getVersionName(self):
  return self.getManifest().documentElement.getAttribute('android:versionName')

 def getMinSdkVersion(self):
  nodes = self.getManifest().documentElement.getElementsByTagName('uses-sdk')
  namespace = 'http://schemas.android.com/apk/res/android'
  if not nodes or not nodes[0].hasAttributeNS(namespace, 'minSdkVersion'):
   return 1
  return int(nodes[0].getAttributeNS(namespace, 'minSdkVersion'))

 def _getCerts(self):
  for info in self._file.infolist():
   if info.filename.startswith('META-INF/') and info.filename.endswith('.RSA'):
    for cert in ContentInfo.load(self._file.read(info))['content']['certificates']:
     yield cert.dump()

 def getCert(self):
  certs = list(self._getCerts())
  if len(certs) != 1:
   raise Exception('Cannot read certificate')
  return certs[0]
