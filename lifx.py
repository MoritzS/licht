from collections import namedtuple
import datetime
from enum import Enum
import functools
from itertools import islice
import random
import socket
import struct
import sys


LIFX_PORT = 56700


MESSAGE_TYPES = {
    2: 'GetService',
    3: 'StateService',
    12: 'GetHostInfo',
    13: 'StateHostInfo',
    14: 'GetHostFirmware',
    15: 'StateHostFirmware',
    16: 'GetWifiInfo',
    17: 'StateWifiInfo',
    18: 'GetWifiFirmware',
    19: 'StateWifiFirmware',
    20: 'GetPower',
    21: 'SetPower',
    22: 'StatePower',
    23: 'GetLabel',
    24: 'SetLabel',
    25: 'StateLabel',
    32: 'GetVersion',
    33: 'StateVersion',
    34: 'GetInfo',
    35: 'StateInfo',
    45: 'Acknowledgement',
    48: 'GetLocation',
    50: 'StateLocation',
    51: 'GetGroup',
    53: 'StateGroup',
    58: 'EchoRequest',
    59: 'EchoResponse',
    101: 'Light:Get',
    102: 'Light:SetColor',
    107: 'Light:State',
    116: 'Light:GetPower',
    117: 'Light:SetPower',
    118: 'Light:StatePower',
}

MESSAGE_TYPES_REVERSE = {val: key for key, val in MESSAGE_TYPES.items()}


RESERVED = object()


class FieldType(Enum):
    bytes = 0
    int = 1
    uint = 2
    bool = 3
    float = 4

    def from_bytes(self, value):
        return getattr(self, 'from_bytes_{}'.format(self.name))(value)

    @staticmethod
    def from_bytes_bytes(value):
        return value

    @staticmethod
    def from_bytes_int(value):
        return int.from_bytes(value, 'little', signed=True)

    @staticmethod
    def from_bytes_uint(value):
        return int.from_bytes(value, 'little')

    @staticmethod
    def from_bytes_bool(value):
        return int.from_bytes(value, 'little') != 0

    @staticmethod
    def from_bytes_float(value):
        if len(value) == 4:
            return struct.unpack('<f', value)[0]
        elif len(value) == 8:
            return struct.unpack('<d', value)[0]
        else:
            raise ValueError('value for float must be 4 or 8 bytes')

    def to_bytes(self, value, length):
        return getattr(self, 'to_bytes_{}'.format(self.name))(value, length)

    @staticmethod
    def to_bytes_bytes(value, length):
        return value

    @staticmethod
    def to_bytes_int(value, length):
        return value.to_bytes(length, 'little', signed=True)

    @staticmethod
    def to_bytes_uint(value, length):
        return value.to_bytes(length, 'little')

    @staticmethod
    def to_bytes_bool(value, length):
        if value:
            value = 1
        else:
            value = 0
        return value.to_bytes(length, 'little')

    @staticmethod
    def to_bytes_float(value, length):
        if length == 4:
            return struct.pack('<f', value)
        elif length == 8:
            return struct.pack('<d', value)
        else:
            raise ValueError('length must be 4 or 8 for float')


def _issubclass(sub, parent):
    return isinstance(sub, type) and issubclass(sub, parent)


class Field(namedtuple('FieldBase', ('name', 'bits', 'type'))):
    def __new__(cls, name, bits=0, type=FieldType.bytes):
        if _issubclass(type, Bitfield):
            bits = type.total_bytes * 8
        elif not isinstance(type, FieldType):
            raise TypeError('type must be FieldType or Bitfield')
        if bits <= 0:
            raise ValueError('bits must be greater than 0')
        return super().__new__(cls, name, bits, type)


class BitfieldMeta(type):
    def __new__(mcs, name, bases, namespace):
        if 'fields' not in namespace:
            raise TypeError('Bitfield class needs fields attribute')

        namespace['field_key_list'] = [
            field.name for field in namespace['fields']
            if field.name is not RESERVED
        ]
        namespace['field_keys'] = set(namespace['field_key_list'])
        namespace['total_bytes'] = sum(f.bits for f in namespace['fields']) // 8

        cls = super().__new__(mcs, name, bases, namespace)

        if all(f.bits % 8 == 0 for f in namespace['fields']):
            cls.to_bytes = cls._to_bytes_simple
            cls.from_bytes = cls._from_bytes_simple
        else:
            cls.to_bytes = cls._to_bytes_full
            cls.from_bytes = cls._from_bytes_full

        return cls


class Bitfield(object, metaclass=BitfieldMeta):
    fields = []

    def __init__(self, *args, **kwargs):
        if args and kwargs:
            raise ValueError('pass either args or kwargs, not both')
        if args:
            if len(args) != len(self.field_key_list):
                raise ValueError('unexpected number of values')
            kwargs = {
                key: val for key, val in zip(self.field_key_list, args)
            }

        if set(kwargs.keys()) != self.field_keys:
            raise ValueError('unexpected keys')

        self._data = kwargs

    def __repr__(self):
        vals = (
            '{}={!r}'.format(field.name, self._data[field.name])
            for field in self.fields if field.name is not RESERVED
        )
        return '<{} {}>'.format(self.__class__.__name__, ' '.join(vals))

    def to_bytes(self):
        # gets replaced with _to_bytes_simple or _to_bytes_full by meta class
        pass

    def _get_value(self, field):
        num_bytes = (field.bits - 1) // 8 + 1
        if field.name is RESERVED:
            return b'\x00' * num_bytes
        else:
            return field.type.to_bytes(self._data[field.name], num_bytes)

    def _to_bytes_simple(self):
        return b''.join(self._get_value(field) for field in self.fields)

    def _to_bytes_full(self):
        byte_data = b''
        packed_bits = 0
        pack = []
        for field in self.fields:
            packed_bits += field.bits
            pack.append((self._get_value(field), field.bits))

            if packed_bits % 8 == 0:
                packed_val = 0
                for val, bits in pack:
                    val = int.from_bytes(val[:(bits - 1) // 8 + 1], 'little')
                    packed_val <<= bits
                    packed_val |= val & ((1 << bits) - 1)

                byte_data += packed_val.to_bytes(packed_bits // 8, 'little')
                packed_bits = 0
                pack = []

        return byte_data

    @classmethod
    def from_bytes(cls, data):
        # gets replaced with _from_bytes_simple or _from_bytes_full
        # by meta class
        pass

    @classmethod
    def _from_bytes_simple(cls, data):
        if len(data) < cls.total_bytes:
            raise ValueError('missing data')
        bytes_data = iter(bytes(data))
        bitfield_data = {}
        for field in cls.fields:
            if field.name is not RESERVED:
                field_bytes = bytes(islice(bytes_data, field.bits // 8))
                bitfield_data[field.name] = field.type.from_bytes(field_bytes)

        return cls(**bitfield_data)

    @classmethod
    def _from_bytes_full(cls, data):
        if len(data) < cls.total_bytes:
            raise ValueError('missing data')
        bytes_data = iter(bytes(data))
        bitfield_data = {}
        packed_bits = 0
        pack = []
        for field in cls.fields:
            packed_bits += field.bits
            pack.append(field)

            if packed_bits % 8 == 0:
                pack_bytes = bytes(islice(bytes_data, packed_bits // 8))
                value = int.from_bytes(pack_bytes, 'little')
                for pack_field in reversed(pack):
                    if pack_field.name is not RESERVED:
                        int_val = value & ((1 << pack_field.bits) - 1)
                        num_bytes = (pack_field.bits - 1) // 8 + 1
                        bytes_val = int_val.to_bytes(num_bytes, 'little')
                        bitfield_data[pack_field.name] = pack_field.type.from_bytes(bytes_val)

                    value >>= pack_field.bits

                packed_bits = 0
                pack = []

        return cls(**bitfield_data)

    def __bytes__(self):
        return self.to_bytes()

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        if key not in self.field_keys:
            raise ValueError('invalid key')
        self._data[key] = value


class Frame(Bitfield):
    fields = [
        Field('size', 16, FieldType.uint),
        Field('origin', 2, FieldType.uint),
        Field('tagged', 1, FieldType.bool),
        Field('addressable', 1, FieldType.bool),
        Field('protocol', 12, FieldType.uint),
        Field('source', 32, FieldType.bytes),
    ]


class FrameAddress(Bitfield):
    fields = [
        Field('target', 64, FieldType.bytes),
        Field(RESERVED, 48),
        Field(RESERVED, 6),
        Field('ack_required', 1, FieldType.bool),
        Field('res_required', 1, FieldType.bool),
        Field('sequence', 8, FieldType.uint),
    ]


class ProtocolHeader(Bitfield):
    fields = [
        Field(RESERVED, 64),
        Field('type', 16, FieldType.uint),
        Field(RESERVED, 16),
    ]

    @property
    def message_type(self):
        return MESSAGE_TYPES[self['type']]


class Header(Bitfield):
    fields = [
        Field('frame', type=Frame),
        Field('frame_address', type=FrameAddress),
        Field('protocol_header', type=ProtocolHeader),
    ]

    @property
    def message_type(self):
        return MESSAGE_TYPES[self['protocol_header']['type']]


class StateService(Bitfield):
    fields = [
        Field('service', 8, FieldType.uint),
        Field('port', 32, FieldType.uint),
    ]


class StateDeviceInfo(Bitfield):
    fields = [
        Field('signal', 32, FieldType.float),
        Field('tx', 32, FieldType.uint),
        Field('rx', 32, FieldType.uint),
        Field(RESERVED, 16),
    ]


class StateFirmware(Bitfield):
    fields = [
        Field('build', 64, FieldType.uint),
        Field(RESERVED, 64),
        Field('version', 32, FieldType.uint),
    ]


class StatePower(Bitfield):
    fields = [
        Field('level', 16, FieldType.uint),
    ]


class StateLabel(Bitfield):
    fields = [
        Field('label', 32*8, FieldType.bytes),
    ]


class StateVersion(Bitfield):
    fields = [
        Field('vendor', 32, FieldType.uint),
        Field('product', 32, FieldType.uint),
        Field('version', 32, FieldType.uint),
    ]


class StateInfo(Bitfield):
    fields = [
        Field('time', 64, FieldType.uint),
        Field('uptime', 64, FieldType.uint),
        Field('downtime', 64, FieldType.uint),
    ]


class StateLocation(Bitfield):
    fields = [
        Field('location', 16*8, FieldType.bytes),
        Field('label', 32*8, FieldType.bytes),
        Field('updated_at', 64, FieldType.uint),
    ]


class StateGroup(Bitfield):
    fields = [
        Field('group', 16*8, FieldType.bytes),
        Field('label', 32*8, FieldType.bytes),
        Field('updated_at', 64, FieldType.uint),
    ]


class EchoPacket(Bitfield):
    fields = [
        Field('payload', 64*8, FieldType.bytes),
    ]


class HSBK(Bitfield):
    fields = [
        Field('hue', 16, FieldType.uint),
        Field('saturation', 16, FieldType.uint),
        Field('brightness', 16, FieldType.uint),
        Field('kelvin', 16, FieldType.uint),
    ]


class LightSetColor(Bitfield):
    fields = [
        Field(RESERVED, 8),
        Field('color', type=HSBK),
        Field('duration', 32, FieldType.uint),
    ]


class LightState(Bitfield):
    fields = [
        Field('color', type=HSBK),
        Field(RESERVED, 16),
        Field('power', 16, FieldType.uint),
        Field('label', 32*8, FieldType.bytes),
        Field(RESERVED, 64),
    ]


def with_socket(meth):
    @functools.wraps(meth)
    def wrapper(self, *args, **kwargs):
        with self._get_socket() as sock:
            return meth(self, sock, *args, **kwargs)

    return wrapper


class Lifx(object):
    def __init__(self, source_id='pylx', timeout=3, tries=3):
        self._bulbs = []
        self.source_id = source_id
        self.timeout = 3
        self.tries = 3

    def get_bulb(self, ip_address, port=LIFX_PORT):
        addr = (ip_address, port)
        if not self._ping(addr):
            raise ValueError('bulb not found')
        return Bulb(self, addr)

    @staticmethod
    def _make_packet(source_id, target_addr, seq, msg_type, payload=None):
        if not target_addr:
            target_addr = 0
        if target_addr:
            tagged = 0
        else:
            tagged = 1
        if not isinstance(msg_type, int):
            msg_type = MESSAGE_TYPES_REVERSE[msg_type]
        if payload is None:
            payload = b''
        elif isinstance(payload, Bitfield):
            payload = payload.to_bytes()
        frame = Frame(0, 0, tagged, 1, 1024, source_id)
        faddr = FrameAddress(target_addr, 0, 0, seq)
        header = ProtocolHeader(msg_type)

        size = frame.total_bytes + faddr.total_bytes + header.total_bytes + len(payload)
        frame['size'] = size

        return frame.to_bytes() + faddr.to_bytes() + header.to_bytes() + payload

    @staticmethod
    def _convert_datetime(src_ns):
        return datetime.datetime.utcfromtimestamp(src_ns // 10**9)

    @staticmethod
    def _convert_timedelta(src_ns):
        return datetime.timedelta(microseconds=src_ns // 10**3)

    def _get_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.timeout)
        return sock

    @with_socket
    def discover(self, sock):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, True)

        broadcast_addr = ('<broadcast>', LIFX_PORT)

        bulb_addrs = set()

        for i in range(self.tries):
            sock.sendto(
                self._make_packet(self.source_id, 0, i, 'GetService'),
                broadcast_addr
            )

            while True:
                try:
                    data, (host, port) = sock.recvfrom(4096)
                except socket.timeout:
                    break
                header = Header.from_bytes(data)
                if header.message_type != 'StateService':
                    continue
                payload = data[Header.total_bytes:]
                service = StateService.from_bytes(payload)

                bulb_addrs.add((host, service['port']))

        sock.close()

        bulbs = []

        for addr in bulb_addrs:
            bulbs.append(Bulb(self, addr))

        self._bulbs = bulbs

        return len(bulbs)

    @with_socket
    def _get_state_packet(self, sock, addr, get_type, state_type, state_cls):
        for i in range(self.tries):
            sock.sendto(self._make_packet(self.source_id, 0, i, get_type), addr)
            while True:
                try:
                    data, from_addr = sock.recvfrom(4096)
                except socket.timeout:
                    break
                if from_addr != addr:
                    continue
                header = Header.from_bytes(data)
                if header.message_type != state_type:
                    continue
                payload = data[Header.total_bytes:]
                return state_cls.from_bytes(payload)

    def _get_device_info(self, addr, get, state):
        info = self._get_state_packet(addr, get, state, StateDeviceInfo)
        return info['signal'], info['tx'], info['rx']

    def _get_host_info(self, addr):
        return self._get_device_info(addr, 'GetHostInfo', 'StateHostInfo')

    def _get_wifi_info(self, addr):
        return self._get_device_info(addr, 'GetWifiInfo', 'StateWifiInfo')

    def _get_firmware(self, addr, get, state):
        firmware = self._get_state_packet(addr, get, state, StateFirmware)
        version = firmware['version']
        build = self._convert_datetime(firmware['build'])
        major = version >> 16
        minor = version & 0xff
        return build, major, minor

    def _get_host_firmware(self, addr):
        return self._get_firmware(addr, 'GetHostFirmware', 'StateHostFirmware')

    def _get_wifi_firmware(self, addr):
        return self._get_firmware(addr, 'GetWifiFirmware', 'StateWifiFirmware')

    def _get_power(self, addr):
        power = self._get_state_packet(addr, 'GetPower', 'StatePower', StatePower)
        return power['level']

    def _get_label(self, addr):
        label = self._get_state_packet(addr, 'GetLabel', 'StateLabel', StateLabel)
        return self._convert_string(label['label'])

    def _get_version(self, addr):
        version = self._get_state_packet(addr, 'GetVersion', 'StateVersion', StateVersion)
        return version['vendor'], version['product'], version['version']

    def _get_info(self, addr):
        info = self._get_state_packet(addr, 'GetInfo', 'StateInfo', StateInfo)
        time = self._convert_datetime(info['time'])
        uptime = self._convert_timedelta(info['uptime'])
        downtime = self._convert_timedelta(info['downtime'])
        return time, uptime, downtime

    def _get_location(self, addr):
        loc = self._get_state_packet(addr, 'GetLocation', 'StateLocation', StateLocation)
        label = self._convert_string(loc['label'])
        updated_at = self._convert_datetime(loc['updated_at'])
        return loc['location'], label, updated_at

    def _get_group(self, addr):
        group = self._get_state_packet(addr, 'GetGroup', 'StateGroup', StateGroup)
        label = self._convert_string(group['label'])
        updated_at = self._convert_datetime(group['updated_at'])
        return group['group'], label, updated_at

    @with_socket
    def _ping(self, sock, addr):
        payload = bytes([random.getrandbits(8) for _ in range(EchoPacket.total_bytes)])

        for i in range(self.tries):
            packet = EchoPacket(payload=payload)
            sock.sendto(self._make_packet(self.source_id, 0, i, 'EchoRequest', packet), addr)
            while True:
                try:
                    data, from_addr = sock.recvfrom(4096)
                except socket.timeout:
                    break
                if from_addr != addr:
                    continue
                header = Header.from_bytes(data)
                if header.message_type != 'EchoResponse':
                    continue
                response = EchoPacket.from_bytes(data[Header.total_bytes:])
                if response['payload'] == payload:
                    return True

        return False

    def _get_light_state(self, addr):
        state = self._get_state_packet(addr, 'Light:Get', 'Light:State', LightState)
        return state


# don't need with_socket anymore
del with_socket


def cached_attr(name):
    def decorator(meth):
        @functools.wraps(meth)
        def wrapper(self):
            if name not in self._cached_attrs:
                self._cached_attrs[name] = meth(self)
            return self._cached_attrs[name]
        return wrapper
    return decorator


class Bulb(object):
    def __init__(self, lifx_obj, addr):
        self._l = lifx_obj
        self._addr = addr
        self._cached_attrs = {}

    def __repr__(self):
        return '<Bulb: {}.get_bulb({!r}, {!r})>' \
            .format(self._l.__class__.__name__, *self._addr)

    def get_host_info(self):
        return self._l._get_host_info(self._addr)

    @cached_attr('host_firmware')
    def get_host_firmware(self):
        return self._l._get_host_firmware(self._addr)

    def get_wifi_info(self):
        return self._l._get_wifi_info(self._addr)

    @cached_attr('wifi_firmware')
    def get_wifi_firmware(self):
        return self._l._get_wifi_firmware(self._addr)

    def get_power(self):
        return self._l._get_power(self._addr)

    @cached_attr('label')
    def get_label(self):
        return self._l._get_label(self._addr)

    @cached_attr('version')
    def get_version(self):
        return self._l._get_version(self._addr)

    def get_times(self):
        return self._l._get_info(self._addr)

    @cached_attr('location')
    def get_location(self):
        return self._l._get_location(self._addr)

    @cached_attr('group')
    def get_group(self):
        return self._l._get_group(self._addr)

    def ping(self):
        return self._l._ping(self._addr)

    def get_light_state(self):
        return self._l._get_light_state(self._addr)


# don't need cached_attr anymore
del cached_attr
