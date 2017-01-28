#!/usr/bin/env python3

import asyncio

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

SUCCESS = ESCAPE + GREEN + ';' + BOLD + END_ESCAPE + '✔' + R
FAIL = ESCAPE + RED + ';' + BOLD + END_ESCAPE + '✘' + R


def bold(s):
    return ESCAPE + BOLD + END_ESCAPE + s + R


async def run_test(lights, name, method, *args, loop, print_return_value=False):
    async def run_single(light, label):
        try:
            ret = await getattr(light, method)(*args)
        except LichtTimeoutError:
            ret = None
            print('{}: {}'.format(label, FAIL))
        else:
            if print_return_value:
                print('{}: {}'.format(label, ret))
            else:
                print('{}: {}'.format(label, SUCCESS))
        return (light, ret)

    print()
    print('{}:'.format(bold(name)))
    done, pending = await asyncio.wait(
        [run_single(light, label) for light, label in lights], loop=loop
    )
    return [f.result() for f in done]


async def run_rainbow(lights, loop):
    print()
    print('{}:'.format(bold('Rainbow')))
    async def run_single(light, label, color):
        try:
            await light.set_color(color)
        except LichtTimeoutError:
            print('{}: {}'.format(label, FAIL))
        else:
            print('{}: {}'.format(label, SUCCESS))
    await asyncio.wait(
        [
            run_single(light, label, LightColor(i * 360 / len(lights), 1, 1))
            for i, (light, label) in enumerate(lights)
        ], loop=loop
    )


async def run_demo(loop):
    backend = LifxBackend(loop=loop)

    print(bold('Discovering lights:'))

    lights = []
    async for light in backend.discover_lights():
        label = await light.get_label()
        print('Discovered "{}"'.format(label))
        lights.append((light, label))

    await run_test(lights, 'ping', 'ping', loop=loop)
    powers = await run_test(lights, 'get power', 'get_power', loop=loop, print_return_value=True)
    colors = await run_test(lights, 'get color', 'get_color', loop=loop, print_return_value=True)
    await asyncio.sleep(5)
    await run_test(lights, 'power off', 'poweroff', loop=loop)
    await asyncio.sleep(2)
    await run_test(lights, 'power on', 'poweron', loop=loop)
    await asyncio.sleep(2)
    await run_test(lights, 'bright white', 'set_color', LightWhite(1, 9000), loop=loop)
    await asyncio.sleep(2)
    await run_test(lights, 'warm white', 'set_color', LightWhite(1, 2500), loop=loop)
    await asyncio.sleep(2)
    await run_test(lights, 'color red', 'set_color', LightColor(0, 1, 1), loop=loop)
    await asyncio.sleep(2)
    await run_test(lights, 'color green', 'set_color', LightColor(120, 1, 1), loop=loop)
    await asyncio.sleep(2)
    await run_test(lights, 'color blue', 'set_color', LightColor(240, 1, 1), loop=loop)
    await asyncio.sleep(2)
    await run_rainbow(lights, loop)
    await asyncio.sleep(5)

    for light, power in powers:
        await light.set_power(power)
    for light, color in colors:
        await light.set_color(color)


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_demo(loop))
