"""Checksum tails: where the editor may rewrite an image's last byte to repair its additive checksum."""
import glob
import os
from pathlib import Path
import struct
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nvidia_vbios.editor import edit, plan
from nvidia_vbios.editor.registry import registry
from nvidia_vbios.rom import VbiosError, from_bytes, inspect_image, load
from nvidia_vbios.rom import tables
from nvidia_vbios.rom.image import backend
from nvidia_vbios.rom.tables import CHECKSUM_PADDING, EMPTY_TABLE_TAIL, checksum_tail
from test_ada_fields import patched
from test_extended_fields import custom_registry, descriptors
from test_rom_formats import synthetic_rom
from test_turing import messages, synthetic_turing


def power_image(blob):
    """(start, end) of the first chain's image holding the power table."""
    parser = backend(from_bytes(blob))
    image = parser.owner(parser.pointer('P', 0x2C), 1)
    return image['start'], image['end']


def with_tail(blob, tail):
    """blob with tail written just before the checksum byte of the power-table image of every chain."""
    end = power_image(blob)[1]
    return patched(blob, end - 1 - len(tail), tail)


def editable(image):
    return sorted(f['key'] for f in inspect_image(image)['fields'] if f['editable'])


def old_rule(blob, end, family):
    """The tail rule before the empty-table tail: 15 0xff bytes only."""
    return len(CHECKSUM_PADDING) if blob[end - 16:end - 1] == CHECKSUM_PADDING else None


class ChecksumTailRuleTests(unittest.TestCase):
    def test_reviewed_tails_and_their_lengths(self):
        body = bytes(range(1, 33))
        for family in ('ampere', 'ada', 'turing'):
            with self.subTest(family=family):
                self.assertEqual(checksum_tail(body + b'\xff' * 15 + b'\x42', 48, family), 15)
                self.assertEqual(checksum_tail(body + EMPTY_TABLE_TAIL + b'\xff' * 20 + b'\x42', 61, family), 15)
        for family in ('ampere', 'ada'):
            for fill in range(15):
                with self.subTest(family=family, fill=fill):
                    blob = body + EMPTY_TABLE_TAIL + b'\xff' * fill + b'\x42'
                    self.assertEqual(checksum_tail(blob, len(blob), family), 8 + fill)
        # No evidence on Turing: its images end the power image with zero bytes, not this table.
        for fill in (0, 2, 3, 14):
            blob = body + EMPTY_TABLE_TAIL + b'\xff' * fill + b'\x42'
            self.assertIsNone(checksum_tail(blob, len(blob), 'turing'))

    def test_other_tails_are_refused(self):
        body = bytes(range(1, 33))
        cases = {
            'header byte 4 set': bytes.fromhex('10 08 00 00 08 00 00 00') + b'\xff' * 2,
            'header version 0x20': bytes.fromhex('20 08 00 00 00 00 00 00') + b'\xff' * 3,
            'header entry count 1': bytes.fromhex('10 08 00 01 00 00 00 00'),
            'a fill byte 0xfe': EMPTY_TABLE_TAIL + bytes.fromhex('ff fe ff'),
            'a zero byte between header and fill': EMPTY_TABLE_TAIL + bytes.fromhex('00 ff ff'),
            'data before 3 fill bytes': bytes.fromhex('de ad be ef 01 02 03 04') + b'\xff' * 3,
            'data before 14 fill bytes': bytes.fromhex('de ad be ef 01 02 03 04') + b'\xff' * 14,
            'data before the checksum': bytes.fromhex('de ad be ef 01 02 03 04'),
        }
        for name, tail in cases.items():
            blob = body + tail + b'\x42'
            for family in ('ampere', 'ada', 'turing'):
                with self.subTest(case=name, family=family):
                    self.assertIsNone(checksum_tail(blob, len(blob), family))


class EmptyTableTailTests(unittest.TestCase):
    """Synthetic Ampere and Ada images whose power-table image ends with the empty table and 0..14 0xff bytes."""
    SOURCES = {'ampere': dict(family='ampere', copies=2, policies=True),
               'ada': dict(family='ada', copies=2, policies=True)}

    def test_fields_stay_as_editable_as_with_the_padding(self):
        for family, options in self.SOURCES.items():
            padded = from_bytes(synthetic_rom(**options))
            for fill in (0, 2, 3, 14):
                with self.subTest(family=family, fill=fill):
                    image = from_bytes(with_tail(padded.blob, EMPTY_TABLE_TAIL + b'\xff' * fill))
                    parser = backend(image)
                    self.assertTrue(parser.integrity()['valid'])
                    self.assertTrue(parser.checksum_padding_reviewed())
                    self.assertEqual(editable(image), editable(padded))
                    self.assertIn('power_max_w', editable(image))
                    self.assertFalse(any('checksum padding' in m for m in messages(image)))

    def test_an_edit_rewrites_only_the_field_and_the_image_checksum_bytes(self):
        for family, options in self.SOURCES.items():
            for fill in (0, 3, 14):
                with self.subTest(family=family, fill=fill):
                    image = from_bytes(with_tail(synthetic_rom(**options), EMPTY_TABLE_TAIL + b'\xff' * fill))
                    parser = backend(image)
                    field = descriptors(image)['power_max_w']
                    binding = {b.descriptor['key']: b for b in registry.bindings(image, parser)[0]}['power_max_w']
                    result = edit(image, {'power_max_w': field['current'] + 5})
                    rebuilt = backend(result.image)
                    self.assertTrue(rebuilt.integrity()['valid'])
                    self.assertTrue(rebuilt.checksum_padding_reviewed())
                    self.assertEqual(descriptors(result.image)['power_max_w']['current'], field['current'] + 5)
                    start, end = power_image(image.blob)
                    ends = set(parser.copy_offsets(end - 1, 1))
                    self.assertEqual(len(ends), 2)
                    self.assertEqual({r['offset'] for r in result.manifest['integrity_repairs']}, ends)
                    fields = {o + k for o in binding.offsets for k in range(4)}
                    changed = {i for i, (a, b) in enumerate(zip(image.blob, result.blob)) if a != b}
                    self.assertLessEqual(changed, fields | ends)
                    self.assertTrue(changed & fields)
                    # The tail before each checksum byte is unchanged.
                    for last in ends:
                        self.assertEqual(result.blob[last - 8 - fill:last], image.blob[last - 8 - fill:last])
                    self.assertEqual(edit(result.image, {'power_max_w': field['current']}).blob, image.blob)

    def test_unreviewed_tails_keep_every_field_read_only(self):
        cases = {'header byte 4 set': bytes.fromhex('10 08 00 00 08 00 00 00') + b'\xff' * 2,
                 'a fill byte 0xfe': EMPTY_TABLE_TAIL + bytes.fromhex('ff fe ff'),
                 'data before 14 fill bytes': bytes.fromhex('de ad be ef 01 02 03 04') + b'\xff' * 14}
        for family, options in self.SOURCES.items():
            source = synthetic_rom(**options)
            for name, tail in cases.items():
                with self.subTest(family=family, case=name):
                    image = from_bytes(with_tail(source, tail))
                    self.assertTrue(inspect_image(image)['integrity']['valid'])
                    self.assertEqual(editable(image), [])
                    self.assertTrue(any('checksum padding' in m for m in messages(image)))
                    with self.assertRaises(VbiosError) as exc:
                        edit(image, {'power_max_w': 90})
                    self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')

    def test_the_repair_refuses_an_unreviewed_tail_and_fields_that_write_the_tail(self):
        source = synthetic_rom(family='ampere', copies=2)
        end = power_image(source)[1]
        # A custom field skips the editability check, so the repair's own check decides.
        unreviewed = from_bytes(with_tail(source, bytes.fromhex('de ad be ef 01 02 03 04 ff ff')))
        parser = backend(unreviewed)
        probe = custom_registry('probe', parser.copy_offsets(end - 64, 4), scale=1)
        with self.assertRaises(VbiosError) as exc:
            edit(unreviewed, {'probe': 7}, field_registry=probe)
        self.assertEqual(exc.exception.code, 'UNSUPPORTED_CHECKSUM_LAYOUT')
        for fill in (0, 3, 14):
            image = from_bytes(with_tail(source, EMPTY_TABLE_TAIL + b'\xff' * fill))
            parser = backend(image)
            self.assertEqual(edit(image, {'probe': 7}, field_registry=probe).manifest['integrity_repairs'][0]['kind'],
                             'additive_checksum')
            header = end - 1 - fill - 8
            # One changed byte of the header or of the fill, or four bytes up to the checksum byte.
            for at, encoding in ((header, '<B'), (header + 4, '<B'), (end - 2, '<B'), (end - 4, '<I')):
                with self.subTest(fill=fill, at=at - end):
                    touch = custom_registry('touch', parser.copy_offsets(at, 1), encoding=encoding, scale=1)
                    value = (image.blob[at] + 1) & 255 if encoding == '<B' else 7
                    with self.assertRaises(VbiosError) as exc:
                        edit(image, {'touch': value}, field_registry=touch)
                    self.assertEqual(exc.exception.code, 'CONFLICTING_FIELDS')
        # The same holds inside 15 0xff bytes of padding.
        padded = from_bytes(source)
        touch = custom_registry('touch', backend(padded).copy_offsets(end - 9, 4), scale=1)
        with self.assertRaises(VbiosError) as exc:
            edit(padded, {'touch': 0}, field_registry=touch)
        self.assertEqual(exc.exception.code, 'CONFLICTING_FIELDS')


class TuringTailTests(unittest.TestCase):
    def test_turing_keeps_the_padding_rule(self):
        source = synthetic_turing(copies=1)
        self.assertIn('power_max_w', editable(from_bytes(source)))
        for fill in (0, 3):
            with self.subTest(fill=fill):
                image = from_bytes(with_tail(source, EMPTY_TABLE_TAIL + b'\xff' * fill))
                self.assertTrue(inspect_image(image)['integrity']['valid'])
                self.assertFalse(backend(image).checksum_padding_reviewed())
                self.assertEqual(editable(image), [])
                self.assertTrue(any('checksum padding' in m for m in messages(image)))


if __name__ == '__main__':
    unittest.main()
