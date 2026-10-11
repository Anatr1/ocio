"""Tiny MessagePack encoder/decoder (subset) used when the ``msgpack`` package is not installed.

Supports nil, bool, int, float, str, bin, array, map - enough for MessagePack-RPC with the arduino-router.
"""
from __future__ import annotations

import struct


class OutOfData(Exception):
    pass


def packb(o) -> bytes:
    out = bytearray()
    _pack(o, out)
    return bytes(out)


def _pack(o, out: bytearray):
    if o is None:
        out.append(0xC0)
    elif o is True:
        out.append(0xC3)
    elif o is False:
        out.append(0xC2)
    elif isinstance(o, int):
        if 0 <= o < 0x80:
            out.append(o)
        elif -32 <= o < 0:
            out.append(o & 0xFF)
        elif 0 <= o <= 0xFF:
            out += b"\xcc" + struct.pack(">B", o)
        elif 0 <= o <= 0xFFFF:
            out += b"\xcd" + struct.pack(">H", o)
        elif 0 <= o <= 0xFFFFFFFF:
            out += b"\xce" + struct.pack(">I", o)
        elif o > 0:
            out += b"\xcf" + struct.pack(">Q", o)
        elif o >= -0x80:
            out += b"\xd0" + struct.pack(">b", o)
        elif o >= -0x8000:
            out += b"\xd1" + struct.pack(">h", o)
        elif o >= -0x80000000:
            out += b"\xd2" + struct.pack(">i", o)
        else:
            out += b"\xd3" + struct.pack(">q", o)
    elif isinstance(o, float):
        out += b"\xcb" + struct.pack(">d", o)
    elif isinstance(o, str):
        b = o.encode("utf-8")
        n = len(b)
        if n < 32:
            out.append(0xA0 | n)
        elif n <= 0xFF:
            out += b"\xd9" + struct.pack(">B", n)
        elif n <= 0xFFFF:
            out += b"\xda" + struct.pack(">H", n)
        else:
            out += b"\xdb" + struct.pack(">I", n)
        out += b
    elif isinstance(o, (bytes, bytearray, memoryview)):
        b = bytes(o)
        n = len(b)
        if n <= 0xFF:
            out += b"\xc4" + struct.pack(">B", n)
        elif n <= 0xFFFF:
            out += b"\xc5" + struct.pack(">H", n)
        else:
            out += b"\xc6" + struct.pack(">I", n)
        out += b
    elif isinstance(o, (list, tuple)):
        n = len(o)
        if n < 16:
            out.append(0x90 | n)
        elif n <= 0xFFFF:
            out += b"\xdc" + struct.pack(">H", n)
        else:
            out += b"\xdd" + struct.pack(">I", n)
        for v in o:
            _pack(v, out)
    elif isinstance(o, dict):
        n = len(o)
        if n < 16:
            out.append(0x80 | n)
        elif n <= 0xFFFF:
            out += b"\xde" + struct.pack(">H", n)
        else:
            out += b"\xdf" + struct.pack(">I", n)
        for k, v in o.items():
            _pack(k, out)
            _pack(v, out)
    else:
        raise TypeError(f"cannot pack {type(o)}")


def unpack_one(buf: bytes, i: int = 0):
    """Decode one object starting at buf[i]. Returns (obj, new_index). Raises OutOfData."""

    def need(n):
        if i + n > len(buf):
            raise OutOfData

    need(1)
    b = buf[i]
    i += 1
    if b <= 0x7F:
        return b, i
    if b >= 0xE0:
        return b - 0x100, i
    if 0xA0 <= b <= 0xBF:
        n = b & 0x1F
        need(n)
        return buf[i : i + n].decode("utf-8", "replace"), i + n
    if 0x90 <= b <= 0x9F:
        return _arr(buf, i, b & 0x0F)
    if 0x80 <= b <= 0x8F:
        return _map(buf, i, b & 0x0F)
    simple = {0xC0: None, 0xC2: False, 0xC3: True}
    if b in simple:
        return simple[b], i
    fmt = {0xCC: ">B", 0xCD: ">H", 0xCE: ">I", 0xCF: ">Q", 0xD0: ">b", 0xD1: ">h", 0xD2: ">i", 0xD3: ">q",
           0xCA: ">f", 0xCB: ">d"}
    if b in fmt:
        n = struct.calcsize(fmt[b])
        need(n)
        return struct.unpack(fmt[b], buf[i : i + n])[0], i + n
    lens = {0xD9: ">B", 0xDA: ">H", 0xDB: ">I", 0xC4: ">B", 0xC5: ">H", 0xC6: ">I"}
    if b in lens:
        n0 = struct.calcsize(lens[b])
        need(n0)
        n = struct.unpack(lens[b], buf[i : i + n0])[0]
        i += n0
        need(n)
        raw = buf[i : i + n]
        return (raw.decode("utf-8", "replace") if b in (0xD9, 0xDA, 0xDB) else bytes(raw)), i + n
    if b in (0xDC, 0xDD):
        n0 = 2 if b == 0xDC else 4
        need(n0)
        n = struct.unpack(">H" if b == 0xDC else ">I", buf[i : i + n0])[0]
        return _arr(buf, i + n0, n)
    if b in (0xDE, 0xDF):
        n0 = 2 if b == 0xDE else 4
        need(n0)
        n = struct.unpack(">H" if b == 0xDE else ">I", buf[i : i + n0])[0]
        return _map(buf, i + n0, n)
    # fixext/ext: skip
    raise ValueError(f"unsupported msgpack type 0x{b:02x}")


def _arr(buf, i, n):
    out = []
    for _ in range(n):
        v, i = unpack_one(buf, i)
        out.append(v)
    return out, i


def _map(buf, i, n):
    out = {}
    for _ in range(n):
        k, i = unpack_one(buf, i)
        v, i = unpack_one(buf, i)
        out[k] = v
    return out, i


class Unpacker:
    """Streaming decoder: feed() bytes, iterate complete objects."""

    def __init__(self):
        self.buf = b""

    def feed(self, data: bytes):
        self.buf += data

    def __iter__(self):
        while self.buf:
            try:
                obj, i = unpack_one(self.buf, 0)
            except OutOfData:
                return
            self.buf = self.buf[i:]
            yield obj
