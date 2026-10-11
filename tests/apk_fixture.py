"""APK fixture generator for parser, validator, and installation tests."""
import base64
import io
import struct
from zipfile import ZipFile

# Base64 encoded valid PKCS7 signature block from official signed RecipeLab APK
_SAMPLE_RSA_BASE64 = (
    "MIIEjgYJKoZIhvcNAQcCoIIEfzCCBHsCAQExCzAJBgUrDgMCGgUAMAsGCSqGSIb3DQEHAaCCAvowggL2MIIB"
    "3qADAgECAgkA+rcnUAWCBDkwDQYJKoZIhvcNAQELBQAwKDERMA8GA1UEChMIdm94aXZvaWQxEzARBgNVBAMT"
    "CkdhbW1hUHJvYmUwIBcNMjYwOTA4MTQ1MjIzWhgPMjA1NDAxMjQxNDUyMjNaMCgxETAPBgNVBAoTCHZveGl2"
    "b2lkMRMwEQYDVQQDEwpHYW1tYVByb2JlMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAnvNarqAQ"
    "NkVYMUAYyRIfNRlD7myDaQb0P/h+kgFrnTE+Mc3Tv3lUuTXrKvrpgL75wTKLJIDaToBlIEogCAD1fHQISGBJ"
    "6r2/F9xG5K929mHELHvep0F2pUzQkibp61i8dy1hOmd+oyeIYW9IvODgOnet7SPpzrcR460a96PaAU2EzcK8"
    "Ue5fY4x8hcbCGK1eLF6vx4m/cdKCYX3tMYKLg3SRQ4zV4yBIduTU8LlROjICJvNFOD5N3bFYOXUqxuZQtN3u"
    "r0H3r3ITL4EGxGd9wablhY881X+6hnu5tBPy6Jytj6gW0FKLV90Q8MONy28StqNCSYTr7p9d7DGPN6LJtwID"
    "AQABoyEwHzAdBgNVHQ4EFgQULCb3+pty5w1Div6araM5DljFJ4owDQYJKoZIhvcNAQELBQADggEBAE24q0wU"
    "W8tt4Irid2spr3TUDZZyUgL/wqB+BjLyY78pRS0U13MGhvwMiWOewnpF2ouo9ODI2rMyXZZJd5scAlWD5fVE"
    "muJqV9294OChKzhEFkBvbFxkS81XoRT/S3NN3gZfZ+9fkJslUHEqrvMJ0WGrWTvecDpCYKVnwpnk0zwlWi+F"
    "uK34qQDMd6ihJ3z3qlyTqhvAh+Yp516UKthez5h0KvDeFjKwrYH3pFOmSE9oiuUEewCXQf2TboIhqlcsUQpW"
    "a8Ooe/C0yyHm7k1+LGFSgWAxbo3ukHTqYECNr3kV0CUMSTrYvM/0dfhXAEm9eZs68IRg8yHA2wA0qDmPje0x"
    "ggFcMIIBWAIBATA1MCgxETAPBgNVBAoTCHZveGl2b2lkMRMwEQYDVQQDEwpHYW1tYVByb2JlAgkA+rcnUAWC"
    "BDkwCQYFKw4DAhoFADANBgkqhkiG9w0BAQEFAASCAQCSj/UR+kdkAjEsmzyPEjndtSVgxH2ccWId8jbIjd/+"
    "QoP0w1tcOYf2hJqWY3w6LpR4fMkRaXr3CVt5OLfp+sOQnnOt0T5rcDMosxZSiQTWusn6CD+HL79IQ2RERiQ+"
    "GkFyhVN6BoYq9s9Y61wBIcM7su7V2/zsS46S84POOQFK60MKzHf9Ke0qRZFC5dYW/oe6gyFIIpMKaqSKUD+F"
    "uraaRq6GDDXdsLISxoB8vJncU7zULlCSMK1w2mkJg4y3vK+Zd21P2gCYcwV4jKLTsIM9SKCJIwp4l+5x85Fy"
    "jgCk2vCd7qhvsgK1+TMCkUVtLOjUGZB+7+rdyoiflDUq6IiG"
)


def apkFixture(package='com.voxivoid.recipelab', minSdk=10, usesSdk=True, utf8=False, signed=True, versionName='1.6.2'):
 strings = ['android', 'http://schemas.android.com/apk/res/android',
  'manifest', 'package', package, 'uses-sdk', 'minSdkVersion']
 if minSdk is not None and not isinstance(minSdk, int):
  strings.append(minSdk)
 if versionName is not None:
  strings.extend(['versionName', str(versionName)])

 data = b''
 offsets = []
 for string in strings:
  offsets.append(len(data))
  if utf8:
   encoded = string.encode('utf-8')
   char_len = len(string)
   byte_len = len(encoded)
   h = bytes([char_len]) if char_len < 0x80 else bytes([0x80 | (char_len >> 8), char_len & 0xff])
   h += bytes([byte_len]) if byte_len < 0x80 else bytes([0x80 | (byte_len >> 8), byte_len & 0xff])
   data += h + encoded + b'\0'
  else:
   encoded = string.encode('utf-16le')
   data += struct.pack('<H', len(encoded) // 2) + encoded + b'\0\0'
 data += b'\0' * (-len(data) % 4)
 start = 28 + 4 * len(strings)
 flags = 0x100 if utf8 else 0
 pool = struct.pack('<HH6I', 1, 28, start + len(data), len(strings),
  0, flags, start, 0) + struct.pack('<%dI' % len(strings), *offsets) + data

 def chunk(kind, body):
  return struct.pack('<HHIII', kind, 16, 16 + len(body), 1, 0xffffffff) + body

 def attribute(namespace, name, raw, kind, value):
  return struct.pack('<IIIHBBI', namespace, name, raw, 8, 0, kind, value)

 def startTag(name, attributes):
  return chunk(0x0102, struct.pack('<II6H', 0xffffffff, name,
   20, 20, len(attributes), 0, 0, 0) + b''.join(attributes))

 def endTag(name):
  return chunk(0x0103, struct.pack('<II', 0xffffffff, name))

 manifest_attrs = [attribute(0xffffffff, 3, 4, 3, 4)]
 if versionName is not None:
  ver_name_idx = strings.index('versionName')
  ver_val_idx = strings.index(str(versionName))
  manifest_attrs.append(attribute(1, ver_name_idx, ver_val_idx, 3, ver_val_idx))

 body = pool + chunk(0x0100, struct.pack('<II', 0, 1))
 body += startTag(2, manifest_attrs)
 if usesSdk:
  attributes = []
  if isinstance(minSdk, int):
   attributes.append(attribute(1, 6, 0xffffffff, 0x10, minSdk & 0xffffffff))
  elif minSdk is not None:
   attributes.append(attribute(1, 6, 7, 3, 7))
  body += startTag(5, attributes) + endTag(5)
 body += endTag(2) + chunk(0x0101, struct.pack('<II', 0, 1))
 manifest = struct.pack('<HHI', 3, 8, 8 + len(body)) + body
 output = io.BytesIO()
 with ZipFile(output, 'w') as archive:
  archive.writestr('AndroidManifest.xml', manifest)
  if signed:
   rsa_data = base64.b64decode(_SAMPLE_RSA_BASE64)
   archive.writestr('META-INF/PROBE.RSA', rsa_data)
 return output.getvalue()
