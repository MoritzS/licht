#!/usr/bin/env python

import struct
import unittest

from licht.lifx import RESERVED, Bitfield, Field, FieldType


class LifxBitFieldTest(unittest.TestCase):
    def assertFieldsEqual(self, field, field_dict):
        for key, val in field_dict.items():
            self.assertEqual(field[key], val)

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

        class ReservedSimpleBitfield(Bitfield):
            fields = [
                Field(RESERVED, 16),
                Field('foo', 16, FieldType.bytes),
                Field(RESERVED, 8),
                Field('bar', 16, FieldType.bytes),
            ]

        class ReservedFullBitfield(Bitfield):
            fields = [
                Field(RESERVED, 4),
                Field('foo', 12, FieldType.uint),
                Field(RESERVED, 5),
                Field('bar', 3, FieldType.uint),
            ]

        cls.SimpleBitfield = SimpleBitfield
        cls.FullBitfield = FullBitfield
        cls.ReservedSimpleBitfield = ReservedSimpleBitfield
        cls.ReservedFullBitfield = ReservedFullBitfield

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
        self.assertFieldsEqual(f, expected)

    def test_from_bytes_full(self):
        val1 = (((1 << 30) | 9999) << 33) | 123123
        value = val1.to_bytes(8, 'little') + struct.pack('<f', 6.125)
        f = self.FullBitfield.from_bytes(value)
        expected = {'foo': True, 'bar': 9999, 'baz': 123123, 'fiz': 6.125}
        self.assertFieldsEqual(f, expected)

    def test_reserved_simple(self):
        f = self.ReservedSimpleBitfield(foo=b'qq', bar=b'aa')
        self.assertEqual(f.to_bytes(), b'\x00\x00qq\x00aa')

        data = b'zzqqzaa'
        f = self.ReservedSimpleBitfield.from_bytes(data)
        self.assertFieldsEqual(f, {'foo': b'qq', 'bar': b'aa'})

    def test_reserved_full(self):
        f = self.ReservedFullBitfield(foo=3456, bar=3)
        self.assertEqual(f.to_bytes(), b'\x80\x0d\x03')

        data = b'\x80\x9d\xab'
        f = self.ReservedFullBitfield.from_bytes(data)
        self.assertFieldsEqual(f, {'foo': 3456, 'bar': 3})


if __name__ == '__main__':
    unittest.main()
