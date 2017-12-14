'''
Created on Jul 13, 2012

@author: cdecker
'''
import hashlib
import struct


def encodeVarLength(length):
    if 0xfd > length:
        return struct.pack("<B", length)
    elif 0xffff > length:
        return b"\xFD" + struct.pack("<H", length)
    elif 0xffffffff > length:
        return b"\xFE" + struct.pack("<I", length)
    else:
        return b"\xFF" + struct.pack("<Q", length)


def decodeVarLength(i):
    l, = struct.unpack_from("<B", i.read(1))
    if l == 255:
        l, = struct.unpack_from("<Q", i.read(8))
    elif l == 254:
        l, = struct.unpack_from("<I", i.read(4))
    elif l == 253:
        l, = struct.unpack_from("<H", i.read(2))
    return l


def decodeVarString(inp):
    length = decodeVarLength(inp)
    return inp.read(length)


def encodeVarString(s):
    if isinstance(s, str):
        s = s.encode('utf-8')
    return encodeVarLength(len(s)) + s


def checksum(payload):
    return doubleSha256(payload)[:4]


def doubleSha256(b):
    if type(b) != bytes:
        b = b.encode('utf-8')
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()
