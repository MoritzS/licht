import asyncio
import datetime
import random
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


class LifxProtocol(asyncio.DatagramProtocol):
    def __init__(self, backend):
        self.backend = backend
        self._lights = set()
        self._message_futures = {}
        self._ack_futures = {}
        self._seq_futures = {}

    @staticmethod
    def _parse_response(data):
        header = Header.from_bytes(data)
        if header.payload_type is None:
            return None
        response = data[Header.total_bytes:header['frame']['size']]
        return header, response

    def datagram_received(self, data, addr):
        host, port = addr
        response = self._parse_response(data)
        if response is not None:
            header = response[0]
            target = header['frame_address']['target']
            message_type = header.payload_type
            if message_type == MessageType.Acknowledgement:
                seq = header['frame_address']['sequence']
                key = ((host, port, target), seq)
                if key in self._seq_futures:
                    self._seq_futures[key].set_result(True)
            else:
                try_keys = [
                    message_type,
                    (host, port, target, message_type),
                    (host, port, None, message_type),
                ]
                for key in try_keys:
                    if key in self._message_futures:
                        future = self._message_futures.pop(key)
                        future.set_result((addr, response))
                        break

    def connection_lost(self, exc):
        for future in self._message_futures.values():
            future.cancel()
        self._message_futures = {}

    def _get_response(self, key):
        if key in self._message_futures:
            raise ValueError('two coroutines waiting for the same response')
        future = self.backend.loop.create_future()
        self._message_futures[key] = future
        return future

    def get_response(self, addr, message_type):
        host, port, target = addr
        key = (host, port, target, message_type)
        return self._get_response(key)

    def cancel_response(self, addr, message_type):
        host, port, target = addr
        key = (host, port, target, message_type)
        try:
            future = self._message_futures.pop(key)
        except KeyError:
            pass
        else:
            future.cancel()

    def get_response_all(self, message_type):
        return self._get_response(message_type)

    def cancel_response_all(self, message_type):
        try:
            future = self._message_futures.pop(message_type)
        except KeyError:
            pass
        else:
            future.cancel()

    def get_ack(self):
        future = self.backend.loop.create_future()
        self._ack_futures[future] = []
        return future

    def _remove_ack(self, ack):
        if ack in self._ack_futures:
            for key in self._ack_futures[ack]:
                if key in self._seq_futures:
                    del self._seq_futures[key]
            del self._ack_futures[ack]

    async def wait_ack(self, ack):
        if ack not in self._ack_futures:
            raise ValueError('invalid ack')
        try:
            await ack
        finally:
            self._remove_ack(ack)

    def register_ack_seq(self, ack, addr, seq):
        if ack not in self._ack_futures:
            return
        key = (addr, seq)
        if key in self._seq_futures:
            raise ValueError('already registered')
        self._ack_futures[ack].append(key)
        self._seq_futures[key] = ack

    def cancel_ack(self, ack):
        ack.cancel()
        self._remove_ack(ack)


class LifxBackend(Backend):
    def __init__(self, source_id=b'lcht', timeout=3, tries=3, *, loop=None):
        self.source_id = source_id
        self.timeout = 3
        self.tries = 3
        if loop is None:
            loop = asyncio.get_event_loop()
        self.loop = loop
        self._endpoint = None
        self._seq = random.randint(0, 255)

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

    def _get_seq(self):
        seq = self._seq
        self._seq = (self._seq + 1) & 255
        return seq

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

    def _get_endpoint(self):
        if self._endpoint is None:
            self._endpoint = asyncio.ensure_future(
                self.loop.create_datagram_endpoint(
                    lambda: LifxProtocol(self),
                    local_addr=('0.0.0.0', LIFX_PORT),
                    allow_broadcast=True
                ), loop=self.loop
            )
        return self._endpoint

    async def _send_discover_packets(self):
        transport, protocol = await self._get_endpoint()
        for i in range(self.tries):
            transport.sendto(
                self._make_packet(self.source_id, None, self._get_seq(), MessageType.GetService),
                ('<broadcast>', LIFX_PORT)
            )
            await asyncio.sleep(self.timeout / self.tries)
        protocol.cancel_response_all(MessageType.StateService)

    async def discover_lights(self):
        transport, protocol = await self._get_endpoint()
        sender = asyncio.ensure_future(self._send_discover_packets(), loop=self.loop)
        discovered_lights = set()
        while True:
            response_future = asyncio.ensure_future(
                protocol.get_response_all(MessageType.StateService), loop=self.loop
            )
            await asyncio.wait(
                [sender, response_future], loop=self.loop, return_when=asyncio.FIRST_COMPLETED
            )
            if sender.done():
                try:
                    await response_future
                except asyncio.CancelledError:
                    pass
                break
            response = response_future.result()
            (host, port), (header, data) = response
            service = StateService.from_bytes(data)
            addr = (host, service['port'], header['frame_address']['target'])
            if addr not in discovered_lights:
                discovered_lights.add(addr)
                yield LifxLight(self, addr)
        await sender

    async def _get_packet_response(self, addr, get_packet, response_type):
        transport, protocol = await self._get_endpoint()
        host, port, target_addr = addr
        for i in range(self.tries):
            transport.sendto(get_packet(i), (host, port))
            try:
                await asyncio.sleep(self.timeout / self.tries)
            except asyncio.CancelledError:
                break
        protocol.cancel_response(addr, response_type)

    def _send_state_request(self, addr, get_type, state_type):
        host, port, target_addr = addr
        def get_packet(i):
            return self._make_packet(self.source_id, target_addr, self._get_seq(), get_type)
        return self._get_packet_response(addr, get_packet, state_type)

    async def _wait_sender_receiver(self, sender, receiver):
        sender = asyncio.ensure_future(sender, loop=self.loop)
        receiver = asyncio.ensure_future(receiver, loop=self.loop)
        await asyncio.wait(
            [sender, receiver], loop=self.loop, return_when=asyncio.FIRST_COMPLETED
        )
        if not sender.done():
            sender.cancel()
        try:
            await sender
        except asyncio.CancelledError:
            pass
        try:
            return await receiver
        except asyncio.CancelledError:
            raise LichtTimeoutError

    async def _get_state_response(self, addr, get_type, state_type):
        transport, protocol = await self._get_endpoint()
        response = await self._wait_sender_receiver(
            self._send_state_request(addr, get_type, state_type),
            protocol.get_response(addr, state_type)
        )
        header, data = response[1]
        return header, state_type.get_bitfield().from_bytes(data)

    async def get_light(self, host, port=LIFX_PORT, target_addr=None):
        if target_addr is None:
            header, service = await self._get_state_response(
                (host, port, None), MessageType.GetService, MessageType.StateService
            )
            addr = host, service['port'], header['frame_address']['target']
        else:
            addr = host, port, target_addr
            await self._ping(addr)
        return LifxLight(self, addr)

    async def _get_state_packet(self, addr, get_type, state_type):
        header, response = await self._get_state_response(addr, get_type, state_type)
        return response

    async def _get_device_info(self, addr, get, state):
        info = await self._get_state_packet(addr, get, state)
        return info['signal'], info['tx'], info['rx']

    def _get_host_info(self, addr):
        return self._get_device_info(addr, MessageType.GetHostInfo, MessageType.StateHostInfo)

    def _get_wifi_info(self, addr):
        return self._get_device_info(addr, MessageType.GetWifiInfo, MessageType.StateWifiInfo)

    async def _get_firmware(self, addr, get, state):
        firmware = await self._get_state_packet(addr, get, state)
        version = firmware['version']
        build = self._convert_datetime(firmware['build'])
        major = version >> 16
        minor = version & 0xff
        return build, major, minor

    def _get_host_firmware(self, addr):
        return self._get_firmware(addr, MessageType.GetHostFirmware, MessageType.StateHostFirmware)

    def _get_wifi_firmware(self, addr):
        return self._get_firmware(addr, MessageType.GetWifiFirmware, MessageType.StateWifiFirmware)

    async def _get_power(self, addr):
        power = await self._get_state_packet(addr, MessageType.GetPower, MessageType.StatePower)
        return power['level']

    async def _get_version(self, addr):
        version = await self._get_state_packet(
            addr, MessageType.GetVersion, MessageType.StateVersion
        )
        return version['vendor'], version['product'], version['version']

    async def _get_info(self, addr):
        info = await self._get_state_packet(addr, MessageType.GetInfo, MessageType.StateInfo)
        time = self._convert_datetime(info['time'])
        uptime = self._convert_timedelta(info['uptime'])
        downtime = self._convert_timedelta(info['downtime'])
        return time, uptime, downtime

    async def _get_location(self, addr):
        loc = await self._get_state_packet(
            addr, MessageType.GetLocation, MessageType.StateLocation
        )
        label = self._convert_string(loc['label'])
        updated_at = self._convert_datetime(loc['updated_at'])
        return loc['location'], label, updated_at

    async def _get_group(self, addr):
        group = await self._get_state_packet(addr, MessageType.GetGroup, MessageType.StateGroup)
        label = self._convert_string(group['label'])
        updated_at = self._convert_datetime(group['updated_at'])
        return group['group'], label, updated_at

    def _get_light_state(self, addr):
        return self._get_state_packet(addr, MessageType.LightGet, MessageType.LightState)

    async def _ping(self, addr):
        host, port, target_addr = addr
        payload = bytes([random.getrandbits(8) for _ in range(EchoRequest.total_bytes)])
        packet = self._make_packet(
            self.source_id, target_addr, self._get_seq(), EchoRequest(payload=payload)
        )
        transport, protocol = await self._get_endpoint()
        await self._wait_sender_receiver(
            self._get_packet_response(addr, lambda i: packet, MessageType.EchoResponse),
            protocol.get_response(addr, MessageType.EchoResponse)
        )

    async def _send_set_packet(self, addr, set_packet, ack):
        transport, protocol = await self._get_endpoint()
        host, port, target_addr = addr
        for i in range(self.tries):
            seq = self._get_seq()
            protocol.register_ack_seq(ack, addr, seq)
            packet = self._make_packet(
                self.source_id, target_addr, seq, set_packet, ack=True
            )
            transport.sendto(packet, (host, port))
            try:
                await asyncio.sleep(self.timeout / self.tries)
            except asyncio.CancelledError:
                break
        protocol.cancel_ack(ack)

    async def _ack_set_packet(self, addr, set_packet):
        transport, protocol = await self._get_endpoint()
        ack = protocol.get_ack()
        sender = asyncio.ensure_future(
            self._send_set_packet(addr, set_packet, ack), loop=self.loop
        )
        ack_wait = asyncio.ensure_future(protocol.wait_ack(ack), loop=self.loop)
        await asyncio.wait(
            [sender, ack_wait], loop=self.loop, return_when=asyncio.FIRST_COMPLETED
        )
        if sender.done():
            sender.result()
        else:
            sender.cancel()
        if ack_wait.cancelled():
            raise LichtTimeoutError
        else:
            ack_wait.result()

    def _set_power(self, addr, level):
        packet = SetPower(level)
        return self._ack_set_packet(addr, packet)

    def _set_color(self, addr, h, s, b, k, ms):
        packet = LightSetColor(HSBK(h, s, b, k), ms)
        return self._ack_set_packet(addr, packet)

    async def get_label(self, light):
        label = await self._get_state_packet(
            light.addr, MessageType.GetLabel, MessageType.StateLabel
        )
        return self._convert_string(label['label'])

    async def get_power(self, light):
        power = await self._get_power(light.addr)
        if power == 0:
            return LightPower.OFF
        else:
            return LightPower.ON

    def set_power(self, light, power):
        if power is LightPower.OFF:
            level = 0
        else:
            level = 65535
        return self._set_power(light.addr, level)

    async def get_color(self, light):
        color = await self._get_light_state(light.addr)
        return self._to_color(color['color'])

    def fade_color(self, light, color, ms):
        if isinstance(color, LightColor):
            h, s, b = color
            h = int(h * 65535 / 360)
            s = int(s * 65535)
            b = int(b * 65535)
            return self._set_color(light.addr, h, s, b, 3500, ms)
        else:
            b, k = color
            b = int(b * 65535)
            return self._set_color(light.addr, 0, 0, b, k, ms)


class LifxLight(Light):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_host_info(self):
        return self.backend._get_host_info(self.addr)

    def get_host_firmware(self):
        return self.backend._get_host_firmware(self.addr)

    def get_wifi_info(self):
        return self.backend._get_wifi_info(self.addr)

    def get_wifi_firmware(self):
        return self.backend._get_wifi_firmware(self.addr)

    def get_version(self):
        return self.backend._get_version(self.addr)

    def get_times(self):
        return self.backend._get_info(self.addr)

    def get_location(self):
        return self.backend._get_location(self.addr)

    def get_group(self):
        return self.backend._get_group(self.addr)

    def ping(self):
        return self.backend._ping(self.addr)
