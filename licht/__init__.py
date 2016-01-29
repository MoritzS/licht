import datetime
import functools
import random
import socket

from . import lifx


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

    def get_bulb(self, ip_address, port=lifx.LIFX_PORT):
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
            msg_type = lifx.MESSAGE_TYPES_REVERSE[msg_type]
        if payload is None:
            payload = b''
        elif isinstance(payload, lifx.Bitfield):
            payload = payload.to_bytes()
        frame = lifx.Frame(0, 0, tagged, 1, 1024, source_id)
        faddr = lifx.FrameAddress(target_addr, 0, 0, seq)
        header = lifx.ProtocolHeader(msg_type)

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

        broadcast_addr = ('<broadcast>', lifx.LIFX_PORT)

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
                header = lifx.Header.from_bytes(data)
                if header.message_type != 'StateService':
                    continue
                payload = data[lifx.Header.total_bytes:]
                service = lifx.StateService.from_bytes(payload)

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
                header = lifx.Header.from_bytes(data)
                if header.message_type != state_type:
                    continue
                payload = data[lifx.Header.total_bytes:]
                return state_cls.from_bytes(payload)

    def _get_device_info(self, addr, get, state):
        info = self._get_state_packet(addr, get, state, lifx.StateDeviceInfo)
        return info['signal'], info['tx'], info['rx']

    def _get_host_info(self, addr):
        return self._get_device_info(addr, 'GetHostInfo', 'StateHostInfo')

    def _get_wifi_info(self, addr):
        return self._get_device_info(addr, 'GetWifiInfo', 'StateWifiInfo')

    def _get_firmware(self, addr, get, state):
        firmware = self._get_state_packet(addr, get, state, lifx.StateFirmware)
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
        power = self._get_state_packet(addr, 'GetPower', 'StatePower', lifx.StatePower)
        return power['level']

    def _get_label(self, addr):
        label = self._get_state_packet(addr, 'GetLabel', 'StateLabel', lifx.StateLabel)
        return self._convert_string(label['label'])

    def _get_version(self, addr):
        version = self._get_state_packet(addr, 'GetVersion', 'StateVersion', lifx.StateVersion)
        return version['vendor'], version['product'], version['version']

    def _get_info(self, addr):
        info = self._get_state_packet(addr, 'GetInfo', 'StateInfo', lifx.StateInfo)
        time = self._convert_datetime(info['time'])
        uptime = self._convert_timedelta(info['uptime'])
        downtime = self._convert_timedelta(info['downtime'])
        return time, uptime, downtime

    def _get_location(self, addr):
        loc = self._get_state_packet(addr, 'GetLocation', 'StateLocation', lifx.StateLocation)
        label = self._convert_string(loc['label'])
        updated_at = self._convert_datetime(loc['updated_at'])
        return loc['location'], label, updated_at

    def _get_group(self, addr):
        group = self._get_state_packet(addr, 'GetGroup', 'StateGroup', lifx.StateGroup)
        label = self._convert_string(group['label'])
        updated_at = self._convert_datetime(group['updated_at'])
        return group['group'], label, updated_at

    @with_socket
    def _ping(self, sock, addr):
        payload = bytes([random.getrandbits(8) for _ in range(lifx.EchoPacket.total_bytes)])

        for i in range(self.tries):
            packet = lifx.EchoPacket(payload=payload)
            sock.sendto(self._make_packet(self.source_id, 0, i, 'EchoRequest', packet), addr)
            while True:
                try:
                    data, from_addr = sock.recvfrom(4096)
                except socket.timeout:
                    break
                if from_addr != addr:
                    continue
                header = lifx.Header.from_bytes(data)
                if header.message_type != 'EchoResponse':
                    continue
                response = lifx.EchoPacket.from_bytes(data[lifx.Header.total_bytes:])
                if response['payload'] == payload:
                    return True

        return False

    def _get_light_state(self, addr):
        state = self._get_state_packet(addr, 'Light:Get', 'Light:State', lifx.LightState)
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
