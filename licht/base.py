import math
from collections import namedtuple
from enum import Enum

from .utils import cache_method


class LightPower(Enum):
    OFF = 0
    ON = 1


class LightColor(namedtuple('LightColorBase', ['hue', 'saturation', 'brightness'])):
    @classmethod
    def from_rgb(cls, rgb):
        pass

    @staticmethod
    def _float_to_rgb(value):
        if value <= 0:
            return 0
        else:
            return math.ceil(value * 256) - 1

    @property
    def rgb(self):
        interval = int(self.hue / 60)
        offset = self.hue / 60 - interval
        a = self.brightness * (1 - self.saturation)
        b = self.brightness * (1 - self.saturation * offset)
        c = self.brightness * (1 - self.saturation * (1 - offset))

        if interval == 1:
            r, g, b = b, self.brightness, a
        elif interval == 2:
            r, g, b = a, self.brightness, c
        elif interval == 3:
            r, g, b = a, b, self.brightness
        elif interval == 4:
            r, g, b = c, a, self.brightness
        elif interval == 5:
            r, g, b = self.brightness, a, b
        else:
            r, g, b = self.brightness, c, a

        return (self._float_to_rgb(r), self._float_to_rgb(g), self._float_to_rgb(b))


LightWhite = namedtuple('LightWhite', ['brightness', 'kelvin'])


class Backend(object):
    def get_light(self, *args, **kwargs):
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

    def __str__(self):
        return self.get_label()

    @cache_method
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
