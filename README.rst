=====
licht
=====

A Python library for managing and controlling smart lights.

Supported Lights
================

Currently only Lifx is supported but support for Philips Hue is planned.

Requirements
============

- Python 3.4 or higher

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

    Running demo on "My Light 1":

    ping: success
    power: LightPower.OFF
    color: LightWhite(brightness=0.8499885557335775, kelvin=3500)
    power off: success
    power on: success
    bright white: success
    warm white: success
    color red: success
    color green: success
    color blue: success

    Running demo on "My Light 2":

    ping: success
    power: LightPower.OFF
    color: LightColor(hue=239.87914854657816, saturation=0.0009918364232852674, brightness=0.2030212863355459)
    power off: success
    power on: success
    bright white: success
    warm white: success
    color red: success
    color green: success
    color blue: success


Here are some examples on how to work with licht:

- Turn of all Lifx lights in your network:

    .. code-block:: python

        backend = LifxBackend()
        for light in backend.discover_lights():
            light.poweroff()

- Turn on a light with a specific IP address:

    .. code-block:: python

        backend = LifxBackend()
        light = backend.get_light('192.168.123.123')
        light.poweron()

- Set the color of a light to red:

    .. code-block:: python

        light.set_color(LightColor(hue=0, saturation=1, brightness=1))

- Fade the color of a light to blue over 5 seconds:

    .. code-block:: python

        light.fade_color(LightColor(hue=240, saturation=1, brightness=1), 5)

- Dim a light that is currently white:

    .. code-block:: python

        white = light.get_color()
        assert isinstance(white, LightWhite)
        light.set_color(LightWhite(white.brightness / 2, white.kelvin))
