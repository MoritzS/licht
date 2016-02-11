import datetime
import functools
import random
import socket
from enum import IntEnum

from .base import Backend, Light, LightColor, LightPower, LightWhite
from .exceptions import LichtTimeoutError
from .utils import RESERVED, Bitfield, Field, FieldType


LIFX_PORT = 56700


class MessageType(IntEnum):
    GetService = 2
    StateService = 3
    GetHostInfo = 12
    StateHostInfo = 13
    GetHostFirmware = 14
    StateHostFirmware = 15
    GetWifiInfo = 16
    StateWifiInfo = 17
    GetWifiFirmware = 18
    StateWifiFirmware = 19
    GetPower = 20
    SetPower = 21
    StatePower = 22
    GetLabel = 23
    SetLabel = 24
    StateLabel = 25
    GetVersion = 32
    StateVersion = 33
    GetInfo = 34
    StateInfo = 35
    Acknowledgement = 45
    GetLocation = 48
    StateLocation = 50
    GetGroup = 51
    StateGroup = 53
    EchoRequest = 58
    EchoResponse = 59
    LightGet = 101
    LightSetColor = 102
    LightState = 107
    LightGetPower = 116
    LightSetPower = 117
    LightStatePower = 118

    def register(self, cls):
        cls.message_type = self
        self._bitfields[self] = cls
        return cls

    def get_bitfield(self):
        return self._bitfields.get(self)


MessageType._bitfields = {}


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
    def payload_type(self):
        ptype = self['type']
        try:
            return MessageType(ptype)
        except ValueError:
            return None


class Header(Bitfield):
    fields = [
        Field('frame', type=Frame),
        Field('frame_address', type=FrameAddress),
        Field('protocol_header', type=ProtocolHeader),
    ]

    @property
    def payload_type(self):
        return self['protocol_header'].payload_type


@MessageType.StateService.register
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


@MessageType.StateHostInfo.register
class StateHostInfo(StateDeviceInfo):
    pass


@MessageType.StateWifiInfo.register
class StateWifiInfo(StateDeviceInfo):
    pass


class StateFirmware(Bitfield):
    fields = [
        Field('build', 64, FieldType.uint),
        Field(RESERVED, 64),
        Field('version', 32, FieldType.uint),
    ]


@MessageType.StateHostFirmware.register
class StateHostFirmware(StateFirmware):
    pass


@MessageType.StateWifiFirmware.register
class StateWifiFirmware(StateFirmware):
    pass


@MessageType.SetPower.register
class SetPower(Bitfield):
    fields = [
        Field('level', 16, FieldType.uint),
    ]


@MessageType.StatePower.register
class StatePower(Bitfield):
    fields = [
        Field('level', 16, FieldType.uint),
    ]


@MessageType.StateLabel.register
class StateLabel(Bitfield):
    fields = [
        Field('label', 32 * 8, FieldType.bytes),
    ]


@MessageType.StateVersion.register
class StateVersion(Bitfield):
    fields = [
        Field('vendor', 32, FieldType.uint),
        Field('product', 32, FieldType.uint),
        Field('version', 32, FieldType.uint),
    ]


@MessageType.StateInfo.register
class StateInfo(Bitfield):
    fields = [
        Field('time', 64, FieldType.uint),
        Field('uptime', 64, FieldType.uint),
        Field('downtime', 64, FieldType.uint),
    ]


@MessageType.StateLocation.register
class StateLocation(Bitfield):
    fields = [
        Field('location', 16 * 8, FieldType.bytes),
        Field('label', 32 * 8, FieldType.bytes),
        Field('updated_at', 64, FieldType.uint),
    ]


@MessageType.StateGroup.register
class StateGroup(Bitfield):
    fields = [
        Field('group', 16 * 8, FieldType.bytes),
        Field('label', 32 * 8, FieldType.bytes),
        Field('updated_at', 64, FieldType.uint),
    ]


class EchoPacket(Bitfield):
    fields = [
        Field('payload', 64 * 8, FieldType.bytes),
    ]


@MessageType.EchoRequest.register
class EchoRequest(EchoPacket):
    pass


@MessageType.EchoResponse.register
class EchoResponse(EchoPacket):
    pass


class HSBK(Bitfield):
    fields = [
        Field('hue', 16, FieldType.uint),
        Field('saturation', 16, FieldType.uint),
        Field('brightness', 16, FieldType.uint),
        Field('kelvin', 16, FieldType.uint),
    ]


@MessageType.LightSetColor.register
class LightSetColor(Bitfield):
    fields = [
        Field(RESERVED, 8),
        Field('color', type=HSBK),
        Field('duration', 32, FieldType.uint),
    ]


@MessageType.LightState.register
class LightState(Bitfield):
    fields = [
        Field('color', type=HSBK),
        Field(RESERVED, 16),
        Field('power', 16, FieldType.uint),
        Field('label', 32 * 8, FieldType.bytes),
        Field(RESERVED, 64),
    ]


def with_socket(meth):
    @functools.wraps(meth)
    def wrapper(self, *args, **kwargs):
        with self._get_socket() as sock:
            return meth(self, sock, *args, **kwargs)

    return wrapper


class LifxBackend(Backend):
    def __init__(self, source_id=b'lcht', timeout=3, tries=3):
        self.source_id = source_id
        self.timeout = 3
        self.tries = 3

    @staticmethod
    def _make_packet(source_id, target_addr, seq, payload, ack=False, res=False):
        if target_addr is None:
            target_addr = b'\x00'
            tagged = 1
        else:
            tagged = 0
        if isinstance(payload, MessageType):
            msg_type = payload
            payload = b''
        elif isinstance(payload, Bitfield):
            msg_type = payload.message_type
            payload = payload.to_bytes()
        else:
            raise ValueError('payload must be MessageType or Bitfield')
        frame = Frame(0, 0, tagged, 1, 1024, source_id)
        faddr = FrameAddress(target_addr, int(ack), int(res), seq)
        header = ProtocolHeader(int(msg_type))

        size = frame.total_bytes + faddr.total_bytes + header.total_bytes + len(payload)
        frame['size'] = size

        return frame.to_bytes() + faddr.to_bytes() + header.to_bytes() + payload

    @staticmethod
    def _parse_response(data, expected_type):
        header = Header.from_bytes(data)
        if header.payload_type is not expected_type:
            return None
        response = data[Header.total_bytes:]
        try:
            return header, expected_type.get_bitfield().from_bytes(response)
        except ValueError:
            return None

    @staticmethod
    def _convert_datetime(src_ns):
        return datetime.datetime.utcfromtimestamp(src_ns // 10**9)

    @staticmethod
    def _convert_timedelta(src_ns):
        return datetime.timedelta(microseconds=src_ns // 10**3)

    @staticmethod
    def _convert_string(bytestring):
        return bytestring.rstrip(b'\x00').decode('utf-8')

    @staticmethod
    def _to_color(hsbk):
        s, b = hsbk['saturation'], hsbk['brightness']
        if s == 0:
            b = b / 65535
            k = hsbk['kelvin']
            return LightWhite(b, k)
        else:
            h = hsbk['hue']
            h = 360 * h / 65535
            s = s / 65535
            b = b / 65535
            return LightColor(h, s, b)

    def _get_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.timeout)
        return sock

    def discover_lights(self):
        with self._get_socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, True)
            sock.bind(('0.0.0.0', LIFX_PORT))

            broadcast_addr = ('<broadcast>', LIFX_PORT)

            light_addrs = set()

            for i in range(self.tries):
                sock.sendto(
                    self._make_packet(self.source_id, None, i, MessageType.GetService),
                    broadcast_addr
                )

                while True:
                    try:
                        data, (host, port) = sock.recvfrom(4096)
                    except socket.timeout:
                        break
                    response = self._parse_response(data, MessageType.StateService)
                    if response is not None:
                        header, service = response
                        addr = (host, service['port'], header['frame_address']['target'])
                        if addr not in light_addrs:
                            light_addrs.add(addr)
                            yield LifxLight(self, addr)

    @with_socket
    def _get_state_response(self, sock, addr, get_type, state_type):
        host, port, target_addr = addr
        for i in range(self.tries):
            sock.sendto(self._make_packet(self.source_id, target_addr, i, get_type), (host, port))
            while True:
                try:
                    data, from_addr = sock.recvfrom(4096)
                except socket.timeout:
                    break
                if from_addr != (host, port):
                    continue
                response = self._parse_response(data, state_type)
                if response is not None:
                    return response

        raise LichtTimeoutError()

    def get_light(self, host, port=LIFX_PORT, target_addr=None):
        if target_addr is None:
            header, service = self._get_state_response(
                (host, port, None), MessageType.GetService, MessageType.StateService
            )
            addr = host, service['port'], header['frame_address']['target']
        else:
            addr = host, port, target_addr
            if not self._ping(addr):
                raise ValueError('light not found')
        return LifxLight(self, addr)

    def _get_state_packet(self, addr, get_type, state_type):
        return self._get_state_response(addr, get_type, state_type)[1]

    def _get_device_info(self, addr, get, state):
        info = self._get_state_packet(addr, get, state)
        return info['signal'], info['tx'], info['rx']

    def _get_host_info(self, addr):
        return self._get_device_info(addr, MessageType.GetHostInfo, MessageType.StateHostInfo)

    def _get_wifi_info(self, addr):
        return self._get_device_info(addr, MessageType.GetWifiInfo, MessageType.StateWifiInfo)

    def _get_firmware(self, addr, get, state):
        firmware = self._get_state_packet(addr, get, state)
        version = firmware['version']
        build = self._convert_datetime(firmware['build'])
        major = version >> 16
        minor = version & 0xff
        return build, major, minor

    def _get_host_firmware(self, addr):
        return self._get_firmware(addr, MessageType.GetHostFirmware, MessageType.StateHostFirmware)

    def _get_wifi_firmware(self, addr):
        return self._get_firmware(addr, MessageType.GetWifiFirmware, MessageType.StateWifiFirmware)

    def _get_power(self, addr):
        power = self._get_state_packet(addr, MessageType.GetPower, MessageType.StatePower)
        return power['level']

    def _get_version(self, addr):
        version = self._get_state_packet(addr, MessageType.GetVersion, MessageType.StateVersion)
        return version['vendor'], version['product'], version['version']

    def _get_info(self, addr):
        info = self._get_state_packet(addr, MessageType.GetInfo, MessageType.StateInfo)
        time = self._convert_datetime(info['time'])
        uptime = self._convert_timedelta(info['uptime'])
        downtime = self._convert_timedelta(info['downtime'])
        return time, uptime, downtime

    def _get_location(self, addr):
        loc = self._get_state_packet(addr, MessageType.GetLocation, MessageType.StateLocation)
        label = self._convert_string(loc['label'])
        updated_at = self._convert_datetime(loc['updated_at'])
        return loc['location'], label, updated_at

    def _get_group(self, addr):
        group = self._get_state_packet(addr, MessageType.GetGroup, MessageType.StateGroup)
        label = self._convert_string(group['label'])
        updated_at = self._convert_datetime(group['updated_at'])
        return group['group'], label, updated_at

    def _get_light_state(self, addr):
        state = self._get_state_packet(addr, MessageType.LightGet, MessageType.LightState)
        return state

    @with_socket
    def _ping(self, sock, addr):
        host, port, target_addr = addr
        payload = bytes([random.getrandbits(8) for _ in range(EchoRequest.total_bytes)])

        for i in range(self.tries):
            packet = EchoRequest(payload=payload)
            sock.sendto(self._make_packet(self.source_id, target_addr, i, packet), (host, port))
            while True:
                try:
                    data, from_addr = sock.recvfrom(4096)
                except socket.timeout:
                    break
                if from_addr != (host, port):
                    continue
                response = self._parse_response(data, MessageType.EchoResponse)
                if response is not None and response[1]['payload'] == payload:
                    return True

        return False

    @with_socket
    def _get_set_packet(self, sock, addr, set_packet, state_type=None):
        host, port, target_addr = addr
        if state_type is None:
            res = False
        else:
            res = True

        ack = False
        response = None

        for i in range(self.tries):
            packet = self._make_packet(self.source_id, target_addr, i, set_packet, True, res)
            sock.sendto(packet, (host, port))
            while True:
                try:
                    data, from_addr = sock.recvfrom(4096)
                except socket.timeout:
                    break
                if from_addr != (host, port):
                    continue
                header = Header.from_bytes(data)
                if header.payload_type is MessageType.Acknowledgement:
                    ack = True
                elif res and header.payload_type is state_type:
                    response_data = data[Header.total_bytes:]
                    response = state_type.get_bitfield().from_bytes(response_data)

                if ack and (not res or response is not None):
                    return response

        return LichtTimeoutError()

    def _set_power(self, addr, level):
        packet = SetPower(level)
        return self._get_set_packet(addr, packet, MessageType.StatePower)

    def _set_color(self, addr, h, s, b, k, ms):
        packet = LightSetColor(HSBK(h, s, b, k), ms)
        return self._get_set_packet(addr, packet, MessageType.LightState)

    def get_label(self, light):
        label = self._get_state_packet(light.addr, MessageType.GetLabel, MessageType.StateLabel)
        return self._convert_string(label['label'])

    def get_power(self, light):
        power = self._get_power(light.addr)
        if power == 0:
            return LightPower.OFF
        else:
            return LightPower.ON

    def set_power(self, light, power):
        if power is LightPower.OFF:
            level = 0
        else:
            level = 65535
        power = self._set_power(light.addr, level)
        if power['level'] == 0:
            return LightPower.OFF
        else:
            return LightPower.ON

    def get_color(self, light):
        hsbk = self._get_light_state(light.addr)['color']
        return self._to_color(hsbk)

    def fade_color(self, light, color, ms):
        if isinstance(color, LightColor):
            h, s, b = color
            h = int(h * 65535 / 360)
            s = int(s * 65535)
            b = int(b * 65535)
            state = self._set_color(light.addr, h, s, b, 3500, ms)
        else:
            b, k = color
            b = int(b * 65535)
            state = self._set_color(light.addr, 0, 0, b, k, ms)
        return self._to_color(state['color'])


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


class LifxLight(Light):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cached_attrs = {}

    def get_host_info(self):
        return self.backend._get_host_info(self.addr)

    @cached_attr('host_firmware')
    def get_host_firmware(self):
        return self.backend._get_host_firmware(self.addr)

    def get_wifi_info(self):
        return self.backend._get_wifi_info(self.addr)

    @cached_attr('wifi_firmware')
    def get_wifi_firmware(self):
        return self.backend._get_wifi_firmware(self.addr)

    @cached_attr('version')
    def get_version(self):
        return self.backend._get_version(self.addr)

    def get_times(self):
        return self.backend._get_info(self.addr)

    @cached_attr('location')
    def get_location(self):
        return self.backend._get_location(self.addr)

    @cached_attr('group')
    def get_group(self):
        return self.backend._get_group(self.addr)

    def ping(self):
        return self.backend._ping(self.addr)

    def get_light_state(self):
        return self.backend._get_light_state(self.addr)


# don't need cached_attr anymore
del cached_attr
