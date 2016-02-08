#!/usr/bin/env python3

import time
from contextlib import contextmanager

from licht.base import LightColor, LightWhite
from licht.exceptions import LichtTimeoutError
from licht.lifx import LifxBackend


ESCAPE = '\x1b['
END_ESCAPE = 'm'
RESET = '0'
R = ESCAPE + RESET + END_ESCAPE
BOLD = '1'
RED = '31'
GREEN = '32'

SUCCESS = ESCAPE + GREEN + ';' + BOLD + END_ESCAPE + 'success' + R
FAIL = ESCAPE + RED + ';' + BOLD + END_ESCAPE + 'fail' + R


def bold(s):
    return ESCAPE + BOLD + END_ESCAPE + s + R


@contextmanager
def run_test(name, print_success=True):
    print('{}: '.format(name), end='', flush=True)
    time.sleep(1)
    try:
        yield
        time.sleep(1)
    except LichtTimeoutError:
        print(FAIL)
    else:
        if print_success:
            print(SUCCESS)


def run_demo():
    b = LifxBackend()

    print(bold('Discovering lights:'))

    ls = []
    for l in b.discover_lights():
        print('Discovered "{}"'.format(l.get_label()))
        ls.append(l)

    print()

    for l in ls:
        print(bold('Running demo on "{}":'.format(l.get_label())))
        print()

        with run_test('ping'):
            if not l.ping():
                raise ValueError()

        power = None
        with run_test('power', False):
            power = l.get_power()
            print(power)

        color = None
        with run_test('color', False):
            color = l.get_color()
            print(color)

        with run_test('power off'):
            l.poweroff()

        with run_test('power on'):
            l.poweron()

        with run_test('bright white'):
            l.set_color(LightWhite(1, 9000))

        with run_test('warm white'):
            l.set_color(LightWhite(1, 2500))

        with run_test('color red'):
            l.set_color(LightColor(0, 1, 1))

        with run_test('color green'):
            l.set_color(LightColor(120, 1, 1))

        with run_test('color blue'):
            l.set_color(LightColor(240, 1, 1))

        if power:
            l.set_power(power)
        if color:
            l.set_color(color)
        print()


if __name__ == '__main__':
    run_demo()
