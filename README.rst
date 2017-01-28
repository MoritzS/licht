=====
licht
=====

A Python library for managing and controlling smart lights.

Supported Lights
================

Currently only Lifx is supported but support for Philips Hue is planned.

Requirements
============

- Python 3.6 or higher

Getting Started
===============

If you want to see what this library can do just run the demo:

.. code-block:: shell

    $ git clone https://github.com/MoritzS/licht.git
    $ cd licht
    $ ./demo.py
    Discovering lights:
    Discovered "My Light 1"
    Discovered "My Light 2"

    ping:
    My Light 1: ✔
    My Light 2: ✔

    get power:
    My Light 2: LightPower.OFF
    My Light 1: LightPower.ON

    get color:
    My Light 1: LightWhite(brightness=0.8499885557335775, kelvin=3500)
    My Light 2: LightColor(hue=239.9945067521172, saturation=0.004959182116426337, brightness=0.20619516289005874)

    power off:
    My Light 1: ✔
    My Light 2: ✔

    power on:
    My Light 1: ✔
    My Light 2: ✔

    bright white:
    My Light 1: ✔
    My Light 2: ✔

    warm white:
    My Light 2: ✔
    My Light 1: ✔

    color red:
    My Light 1: ✔
    My Light 2: ✔

    color green:
    My Light 1: ✔
    My Light 2: ✔

    color blue:
    My Light 1: ✔
    My Light 2: ✔

    Rainbow:
    My Light 1: ✔
    My Light 2: ✔


Examples with asyncio
=====================

``licht`` uses ``asyncio``, so you have to run the following examples in an
event loop. You can execute the examples like this:

.. code-block:: python

    from licht.lifx import LifxBackend

    backend = LifxBackend()

    async def example(backend):
        # insert example code here

    backend.loop.run_until_complete(example(backend))


- Turn off all Lifx lights in your network one by one:

    .. code-block:: python

        async for light in backend.discover_lights():
            await light.poweroff()

- Turn off all Lifx lights in your network simultaneously:

    .. code-block:: python

        lights = [light async for light in backend.discover_lights()]
        asyncio.wait([light.poweroff() for light in lights])

- Turn on a light with a specific IP address:

    .. code-block:: python

        light = await backend.get_light('192.168.123.123')
        await light.poweron()

- Set the color of a light to red:

    .. code-block:: python

        await light.set_color(LightColor(hue=0, saturation=1, brightness=1))

- Fade the color of a light to blue over 5 seconds:

    .. code-block:: python

        await light.fade_color(LightColor(hue=240, saturation=1, brightness=1), 5)

- Dim a light that is currently white:

    .. code-block:: python

        white = await light.get_color()
        assert isinstance(white, LightWhite)
        await light.set_color(LightWhite(white.brightness / 2, white.kelvin))


Examples without asyncio
========================

If you don't want to use ``asyncio`` you can use ``sync()`` on a backend. For
example to turn off all Lifx lights in your network:

.. code-block:: python

    from licht.lifx import LifxBackend

    backend = LifxBackend.sync()

    for light in backend.discover_lights():
        light.poweroff()
