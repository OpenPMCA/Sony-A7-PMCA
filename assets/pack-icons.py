"""Package PNG representations into a modern macOS ICNS container."""
from pathlib import Path
import struct
import sys

root = Path(sys.argv[1])
iconset = root / 'build/sony-open-pmca.iconset'
representations = [
 (b'icp4', 'icon_16x16.png', 16),
 (b'icp5', 'icon_32x32.png', 32),
 (b'icp6', 'icon_32x32@2x.png', 64),
 (b'ic07', 'icon_128x128.png', 128),
 (b'ic08', 'icon_256x256.png', 256),
 (b'ic09', 'icon_512x512.png', 512),
 (b'ic10', 'icon_512x512@2x.png', 1024),
 (b'ic11', 'icon_16x16@2x.png', 32),
 (b'ic12', 'icon_32x32@2x.png', 64),
 (b'ic13', 'icon_128x128@2x.png', 256),
 (b'ic14', 'icon_256x256@2x.png', 512),
]
chunks = []
for kind, filename, size in representations:
 data = (iconset / filename).read_bytes()
 if data[:8] != b'\x89PNG\r\n\x1a\n' or struct.unpack('>II', data[16:24]) != (size, size):
  raise ValueError('Invalid icon representation: %s' % filename)
 chunks.append(kind + struct.pack('>I', len(data) + 8) + data)
payload = b''.join(chunks)
(root / 'assets/sony-open-pmca.icns').write_bytes(b'icns' + struct.pack('>I', len(payload) + 8) + payload)
print('Created ICNS with %d PNG representations' % len(chunks))
