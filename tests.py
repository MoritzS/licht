#!/usr/bin/env python

import struct
import unittest

from licht.lifx import Bitfield, Field, FieldType


class LifxBitFieldTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class SimpleBitfield(Bitfield):
            fields = [
                Field('foo', 16, FieldType.int),
                Field('bar', 6 * 8, FieldType.bytes),
                Field('baz', 64, FieldType.float),
            ]

        class FullBitfield(Bitfield):
            fields = [
                Field('foo', 1, FieldType.bool),
                Field('bar', 30, FieldType.uint),
                Field('baz', 33, FieldType.uint),
                Field('fiz', 32, FieldType.float),
            ]

        cls.SimpleBitfield = SimpleBitfield
        cls.FullBitfield = FullBitfield

    def test_to_bytes_simple(self):
        f = self.SimpleBitfield(foo=1234, bar=b'hello!', baz=3.14)
        expected = (1234).to_bytes(2, 'little') + b'hello!' + struct.pack('<d', 3.14)
        self.assertEqual(f.to_bytes(), expected)

    def test_to_bytes_full(self):
        f = self.FullBitfield(foo=True, bar=123456, baz=987654, fiz=1.55)
        expected = (((1 << 30) | 123456) << 33) | 987654
        expected = expected.to_bytes(8, 'little') + struct.pack('<f', 1.55)
        self.assertEqual(f.to_bytes(), expected)

    def test_from_bytes_simple(self):
        value = (-1234).to_bytes(2, 'little', signed=True) + b'foobar' + struct.pack('<d', 5.25)
        f = self.SimpleBitfield.from_bytes(value)
        expected = {'foo': -1234, 'bar': b'foobar', 'baz': 5.25}
        for key, val in expected.items():
            self.assertEqual(f[key], val)

    def test_from_bytes_full(self):
        val1 = (((1 << 30) | 9999) << 33) | 123123
        value = val1.to_bytes(8, 'little') + struct.pack('<f', 6.125)
        f = self.FullBitfield.from_bytes(value)
        expected = {'foo': True, 'bar': 9999, 'baz': 123123, 'fiz': 6.125}
        for key, val in expected.items():
            self.assertEqual(f[key], val)


if __name__ == '__main__':
    unittest.main()
