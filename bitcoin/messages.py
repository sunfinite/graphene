"""
Created on Jul 13, 2012

@author: cdecker
"""
from time import time
import six
import struct
import socket
from io import BytesIO
from bitarray import bitarray
import codecs

from bitcoin.utils import decodeVarLength, decodeVarString, encodeVarLength, \
    encodeVarString, doubleSha256


PROTOCOL_VERSION = 70001
MIN_PROTOCOL_VERSION = 60001
IPV4_PREFIX = codecs.decode("00000000000000000000FFFF", "hex")
USER_AGENT = "/Snoopy:0.2.1/"
PROTOCOL_SERVICES = 9


WITNESS_FLAG = 1 << 30
INV_TX = 1
INV_BLOCK = 2
INV_WITNESS_TX = INV_TX | WITNESS_FLAG
INV_WITNESS_BLOCK = INV_BLOCK | WITNESS_FLAG
NODE_WITNESS = (1 << 3)

def get_opt(opts, key, default):
    if opts is None or key not in opts:
        return default
    else:
        return opts[key]

class Packet(object):
    """Superclass of all packets that are sent/received by bitcoin."""
    type = None

    def parse(self, payload, opts):
        """
        This should be implemented by each packet in order to parse the
        contents of a message
        """

    def toWire(self, buf, opts):
        """
        This should be implemented by the subclasses
        Writes the packet to the buffer
        """

    def __len__(self):
        buf = six.BytesIO()
        self.toWire(buf, None)
        return len(buf.getvalue())


class Address(Packet):
    """
    Not really a packet on its own but as it is serialized on several occasions
    we just implement it as such.
    """
    type = None

    def __init__(self, ip=None, isIPv4=True, port=8333,
                 services=PROTOCOL_SERVICES, timestamp=None):
        self.isIPv4 = isIPv4
        if ip:
            self.ip = socket.gethostbyname(ip)
        else:
            self.ip = None
        self.timestamp = timestamp
        self.port = port
        self.services = services

    def parse(self, payload, opts):
        Packet.parse(self, payload, opts)
        if get_opt(opts, 'version', PROTOCOL_VERSION) >= 31402:
            self.timestamp, = struct.unpack_from("<I", payload.read(4))
        self.services, ip, = struct.unpack_from("<Q16s", payload.read(24))
        self.port, = struct.unpack_from(">H", payload.read(2))
        if ip[:12] == IPV4_PREFIX:
            self.isIPv4 = True
            self.ip = socket.inet_ntop(socket.AF_INET, ip[12:])
        else:
            self.isIPv4 = False
            self.ip = socket.inet_ntop(socket.AF_INET6, ip)

    def toWire(self, buf, opts):
        Packet.toWire(self, buf, opts)
        if get_opt(opts, 'version', 70001) >= 31402:
            buf.write(struct.pack("<i", int(self.timestamp)))
        buf.write(struct.pack("<Q", self.services))
        if self.isIPv4:
            buf.write(IPV4_PREFIX)
            buf.write(socket.inet_pton(socket.AF_INET, self.ip))
        else:
            buf.write(socket.inet_pton(socket.AF_INET6, self.ip))
        buf.write(struct.pack(">H", self.port))


class VersionPacket(Packet):
    type = "version"

    def __init__(self):
        self.timestamp = int(time())
        self.services = PROTOCOL_SERVICES
        self.version = PROTOCOL_VERSION
        self.nonce = b"__ETHZ__"
        self.user_agent = USER_AGENT
        self.best_height = 0
        self.relay = True
        self.addr_from = None
        self.addr_recv = None

    def is_segwit(self):
        return self.services & NODE_WITNESS != 0

    def parse(self, payload, opts=None):
        Packet.parse(self, payload, opts)
        self.version, self.services, self.timestamp = struct.unpack(
            "<IQQ", payload.read(20))

        if self.version >= 106:
            # Pretend to be version 0, this doesn't include timestamps yet.
            self.addr_recv = Address()
            self.addr_recv.parse(payload, {'version': 0})
            self.addr_from = Address()
            self.addr_from.parse(payload, {'version': 0})
            self.nonce = payload.read(8)
            self.user_agent = decodeVarString(payload)
            self.best_height, = struct.unpack("<I", payload.read(4))
        if self.version >= 70001:
            relay_flag = payload.read(1)
            # Some clients advertise 70001 but then do not include a relay_flag
            if len(relay_flag):
                self.relay = bool(struct.unpack('B', relay_flag)[0] & 1)

    def toWire(self, buf, opts=None):
        Packet.toWire(self, buf, opts)
        buf.write(struct.pack("<IQQ", self.version, self.services,
                              self.timestamp))
        self.addr_recv.toWire(buf, {'version': 0})
        self.addr_from.toWire(buf, {'version': 0})
        buf.write(self.nonce)
        buf.write(encodeVarString(self.user_agent))
        buf.write(struct.pack("<I", self.best_height))
        if self.version >= 70001:
            buf.write(struct.pack('B', 1 if self.relay else 0))

class InvPacket(Packet):
    type = "inv"

    def __init__(self):
        self.hashes = []

    def parse(self, payload, opts):
        length = decodeVarLength(payload)
        while len(self.hashes) < length:
            t, = struct.unpack("<I", payload.read(4))
            h = payload.read(32)[::-1]
            if t == 5 and self.type == "getdata":
                m, = struct.unpack("<I", payload.read(4))
                self.hashes.append((t, h, m))
            else:
                self.hashes.append((t, h))

    def toWire(self, buf, opts):
        buf.write(encodeVarLength(len(self.hashes)))
        for h in self.hashes:
            buf.write(struct.pack("<I", h[0]))
            buf.write(h[1][::-1])
            if h[0] == 5 and self.type == "getdata":
                buf.write(struct.pack("<I", h[2]))


class GetDataPacket(InvPacket):
    type = 'getdata'

    def convertToWitness(self):
        for i in xrange(len(self.hashes)):
            h = self.hashes[i]
            self.hashes[i] = (h[0] | WITNESS_FLAG, h[1])

class PingPacket(Packet):
    type = 'ping'

    def __init__(self):
        self.nonce = None

    def parse(self, payload, opts):
        if payload:
            self.nonce = payload

    def toWire(self, buf, opts):
        if self.nonce:
            buf.write(self.nonce)


class PongPacket(PingPacket):
    """Response to ping."""
    type = 'pong'

class TxPacket(Packet):
    type = "tx"

    def __init__(self):
        self._hash = None
        self.inputs = []
        self.outputs = []
        self.lock_time = 0
        self.version = 1
        self.witnesses = []
        self.is_segwit = False

    def parseSegwit(self, payload, opts):
        if decodeVarLength(payload) == 0:
            return False

        self.is_segwit = True
        txInputCount = decodeVarLength(payload)
        for _i in range(0, txInputCount):
            prev_out = (
                payload.read(32)[::-1],
                struct.unpack("<I", payload.read(4))[0]
            )
            script_length = decodeVarLength(payload)
            script = payload.read(script_length)
            sequence, = struct.unpack("<I", payload.read(4))
            self.inputs.append((prev_out, script, sequence))

        txOutputCount = decodeVarLength(payload)
        for _i in range(0, txOutputCount):
            value, = struct.unpack("<Q", payload.read(8))
            script = decodeVarString(payload)
            self.outputs.append((value, script))

        for i in range(0, txInputCount):
            nelements = decodeVarLength(payload)
            self.witnesses.append([decodeVarString(payload) for _ in range(nelements)])
        self.lock_time, = struct.unpack("<I", payload.read(4))
        return True

    def parse(self, payload, opts):
        Packet.parse(self, payload, opts)

        self.version, = struct.unpack("<I", payload.read(4))
        txInputCount = decodeVarLength(payload)
        if txInputCount == 0:
            return self.parseSegwit(payload, opts)

        for _i in range(0, txInputCount):
            prev_out = (
                payload.read(32)[::-1],
                struct.unpack("<I", payload.read(4))[0]
            )
            script_length = decodeVarLength(payload)
            script = payload.read(script_length)
            sequence, = struct.unpack("<I", payload.read(4))
            self.inputs.append((prev_out, script, sequence))

        txOutputCount = decodeVarLength(payload)
        for _i in range(0, txOutputCount):
            value, = struct.unpack("<Q", payload.read(8))
            script = decodeVarString(payload)
            self.outputs.append((value, script))
        self.lock_time, = struct.unpack("<I", payload.read(4))
        return True

    def toWire(self, buf, opts=None):
        Packet.toWire(self, buf, opts)
        buf.write(struct.pack("<I", self.version))

        if get_opt(opts, 'segwit', False):
            buf.write("\x00\x01")

        buf.write(encodeVarLength(len(self.inputs)))
        for i in self.inputs:
            prev_out, script, sequence = i
            buf.write(prev_out[0][::-1])
            buf.write(struct.pack("<I", prev_out[1]))
            buf.write(encodeVarString(script))
            buf.write(struct.pack("<I", sequence))

        buf.write(encodeVarLength(len(self.outputs)))
        for o in self.outputs:
            value, script = o
            buf.write(struct.pack("<Q", value))
            buf.write(encodeVarString(script))

        if get_opt(opts, 'segwit', False):
            for w in self.witnesses:
                buf.write(encodeVarLength(len(w)))
                for e in w:
                    buf.write(encodeVarString(e))

        buf.write(struct.pack("<I", self.lock_time))

    def hash(self):
        """
        If we have the hash saved from a parsing action we just return it
        otherwise we serialize this transaction and calculate the 2xSha256.
        If the hash is derived from a serialization we do not cache the result
        should happen rarely though.
        """
        buf = BytesIO()
        self.toWire(buf, {'segwit': False})
        return doubleSha256(buf.getvalue())[::-1]

    def whash(self):
        if self.is_coinbase():
            return "\x00"*32
        buf = BytesIO()
        self.toWire(buf, {'segwit': self.is_segwit})
        return doubleSha256(buf.getvalue())[::-1]

    def is_coinbase(self):
        return (len(self.inputs) == 1 and
                self.inputs[0][0][0] == '\0'*32 and
                self.inputs[0][0][1] == 4294967295)

    def normalized_hash(self):
        if self.is_coinbase():
            return self.hash()
        else:
            copy = TxPacket()
            buf = BytesIO()
            self.toWire(buf, None)
            copy.parse(BytesIO(buf.getvalue()), None)

            for pos, iput in enumerate(copy.inputs):
                copy.inputs[pos] = (iput[0], "", iput[2])
            buf = BytesIO()
            copy.toWire(buf, None)
            buf.write(struct.pack('<I', 1))
            return doubleSha256(buf.getvalue())[::-1]

class GraphenePacket(Packet):
    type = "graphene"

    def __init__(self):
        self.bloom_filter = None
        # FIXME: this can be removed once the block header is sent, it has the number of txs in the block
        self.bloom_filter_capacity = 0
        self.fpr = 0
        self.fpr_mul = 10 ** 4
        self.iblt = None

    def to_bitarray(self, s):
        b = bitarray()
        b.frombytes(s)
        return b

    def parse(self, payload, opts):
        Packet.parse(self, payload, opts)
        self.bloom_filter_capacity, = struct.unpack('<I', payload.read(4))
        self.fpr, = struct.unpack('<I', payload.read(4))
        self.fpr /= self.fpr_mul
        self.bloom_filter = decodeVarString(payload)

        self.iblt_m, = struct.unpack('<I', payload.read(4))
        self.iblt_T = []
        for i in range(self.iblt_m):
            count, = struct.unpack('<I', payload.read(4))
            key_sum, = struct.unpack('<32s', payload.read(32))
            # value_sum, = struct.unpack('<32s', payload.read(32))
            value_sum = b''
            key_hash_sum, = struct.unpack('<10s', payload.read(10))
            self.iblt_T.append([count, self.to_bitarray(key_sum), 
                self.to_bitarray(value_sum), self.to_bitarray(key_hash_sum)])

    def toWire(self, buf, opts):
        Packet.toWire(self, buf, opts)
        buf.write(struct.pack('<I', self.bloom_filter_capacity))
        buf.write(struct.pack('<I', int(self.fpr * self.fpr_mul)))
        buf.write(encodeVarString(self.bloom_filter.tobytes()))

        buf.write(struct.pack('<I', self.iblt.m))
        for cell in self.iblt.T:
            buf.write(struct.pack('<I', cell[0]))
            buf.write(struct.pack('<32s', cell[1].tobytes()))
            # buf.write(struct.pack('<32s', cell[2].tobytes()))
            buf.write(struct.pack('<10s', cell[3].tobytes()))

class BlockPacket(Packet):
    type = "block"

    def __init__(self):
        self._hash = None
        self.version = 1
        self.prev_block = None
        self.merkle_root = None
        self.timestamp = int(time())
        self.bits = None
        self.nonce = None
        self.transactions = []

    def parse(self, payload, opts):
        Packet.parse(self, payload, opts)

        self.version, self.prev_block, self.merkle_root = struct.unpack(
            '<I32s32s', payload.read(68))
        self.prev_block = self.prev_block[::-1]
        self.merkle_root = self.merkle_root[::-1]
        self.timestamp, self.bits, self.nonce = struct.unpack(
            '<III', payload.read(12))
        transactionCount = decodeVarLength(payload)
        while len(self.transactions) < transactionCount:
            t = TxPacket()
            t.parse(payload, opts)
            self.transactions.append(t)
        self._hash = doubleSha256(payload.getvalue()[:80])[::-1]

    def toWire(self, buf, opts):
        Packet.toWire(self, buf, opts)
        buf.write(struct.pack("<I32s32sIII",
                              self.version,
                              self.prev_block[::-1],
                              self.merkle_root[::-1],
                              self.timestamp,
                              self.bits,
                              self.nonce))
        buf.write(encodeVarLength(len(self.transactions)))
        for t in self.transactions:
            t.toWire(buf, opts)

    def hash(self):
        """
        If we have the hash saved from a parsing action we just return it
        otherwise we serialize this transaction and calculate the 2xSha256.
        If the hash is derived from a serialization we do not cache the result
        should happen rarely though.
        """
        if self._hash:
            return self._hash
        else:
            buf = BytesIO()
            self.toWire(buf, {'segwit': False, 'version': PROTOCOL_VERSION})
            return doubleSha256(buf.getvalue()[:80])[::-1]

class GetaddrPacket(Packet):
    type = 'getaddr'


class AddrPacket(Packet):
    type = "addr"

    def __init__(self):
        self.addresses = []

    def parse(self, payload, opts):
        l = decodeVarLength(payload)
        for _ in range(0, l):
            a = Address()
            a.parse(payload, opts)
            self.addresses.append(a)

    def toWire(self, buf, opts):
        buf.write(encodeVarLength(len(self.addresses)))
        for a in self.addresses:
            a.toWire(buf, opts)


class VerackMessage(Packet):
    type = 'verack'


class DummyPacket(Packet):
    """ Class of packets that are not really parsed.

    This is just until we implement the actual parsing. It reads/writes the
    packet's binary representation.

    If you need to parse a subclass of DummyPacket, i.e., the packets below
    feel free to implement and send us a pull request :-)
    """
    def __init__(self):
        self.type = None
        self.binrep = ""

    def parse(self, payload, opts):
        self.binrep = payload.getvalue()

    def toWire(self, buf, opts):
        buf.write(self.binrep)

    def __str__(self):
        return "<DummyPacket[%s]>" % (self.type)


class FilterloadPacket(DummyPacket):
    type = 'filterload'


class FilteraddPacket(DummyPacket):
    type = 'filteradd'


class FilterclearPacket(DummyPacket):
    type = 'filterclear'


class MerkleblockPacket(DummyPacket):
    type = 'merkleblock'


class GetheadersPacket(DummyPacket):
    type = 'getheaders'


parsers = {
    AddrPacket.type: AddrPacket,
    TxPacket.type: TxPacket,
    PongPacket.type: PongPacket,
    PingPacket.type: PingPacket,
    InvPacket.type: InvPacket,
    GetDataPacket.type: GetDataPacket,
    BlockPacket.type: BlockPacket,
    VersionPacket.type: VersionPacket,
    VerackMessage.type: VerackMessage,
    FilterloadPacket.type: FilterloadPacket,
    FilteraddPacket.type: FilteraddPacket,
    FilterclearPacket.type: FilterclearPacket,
    MerkleblockPacket.type: MerkleblockPacket,
    GetheadersPacket.type: GetheadersPacket,
    GetaddrPacket.type: GetaddrPacket,
    GraphenePacket.type: GraphenePacket
}
