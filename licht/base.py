import colorsys
from collections import namedtuple
from enum import Enum


class LightPower(Enum):
    OFF = 0
    ON = 1


class LightColor(namedtuple('LightColorBase', ['hue', 'saturation', 'brightness'])):
    @classmethod
    def from_rgb(cls, rgb):
        rgb = [c / 255 for c in rgb]
        h, s, v = colorsys.rgb_to_hsv(*rgb)
        h = h * 360
        return cls(h, s, v)

    @property
    def rgb(self):
        h = self.hue / 360
        rgb = colorsys.hsv_to_rgb(h, self.saturation, self.brightness)
        return tuple(round(c * 255) for c in rgb)


LightWhite = namedtuple('LightWhite', ['brightness', 'kelvin'])


class Backend(object):
    async def get_light(self, *args, **kwargs):
        return Light(self, *args, **kwargs)

    def discover_lights(self):
        pass

    def get_label(self, light):
        return 'Light from {} with address {}'.format(self.__class__.__name__, light.addr)

    def get_power(self, light):
        pass

    def set_power(self, light, power):
        pass

    def get_color(self, light):
        pass

    def set_color(self, light, color):
        return self.fade_color(light, color, 0)

    def fade_color(self, light, color, ms):
        pass


class Light(object):
    def __init__(self, backend, addr):
        self.backend = backend
        self.addr = addr

    def __repr__(self):
        return '{}(backend={!r}, addr={!r})'.format(
            self.__class__.__name__, self.backend, self.addr
        )

    def get_label(self):
        return self.backend.get_label(self)

    def get_power(self):
        return self.backend.get_power(self)

    def set_power(self, power):
        return self.backend.set_power(self, power)

    def poweron(self):
        return self.set_power(LightPower.ON)

    def poweroff(self):
        return self.set_power(LightPower.OFF)

    def get_color(self):
        return self.backend.get_color(self)

    def set_color(self, color):
        return self.backend.set_color(self, color)

    def fade_color(self, color, ms):
        return self.backend.fade_color(self, color, ms)
