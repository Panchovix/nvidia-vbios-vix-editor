"""Evaluated VMIN and the XOC-style REL/ALT selectors: generated images, and reference ROMs when available."""
import hashlib
import os
from pathlib import Path
import struct
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nvidia_vbios.editor import edit
from nvidia_vbios.rom import VbiosError, from_bytes, inspect_image, load
from nvidia_vbios.rom.blackwell import BlackwellRom
from nvidia_vbios.rom.image import backend
from test_ada_fields import patched
from test_extended_fields import changed_bytes_within, custom_registry, descriptors, extended_fixture, repair_fixture
from test_rom_formats import synthetic_rom


def constant(blob, at, value, *, kind=1, link=0xFFFF):
    """A 25-byte GB20x/Ada VFE equation: kind 1 holds minimum = maximum = value, zero slopes."""
    blob[at:at + 25] = bytes(25)
    blob[at:at + 3] = bytes((kind, 14, link & 0xFF))
    struct.pack_into('<fffff', blob, at + 3, value, value, value, 0, 0)
    blob[at + 23:at + 25] = bytes((2, link >> 8))


def vfe_base(parsed):
    vfe = parsed.pointer('P', 0x20)
    return vfe, vfe + parsed.blob[vfe + 1] + parsed.blob[vfe + 2] * parsed.blob[vfe + 3]


def blackwell_vmin(*, shared_slot=None, linked=False, own_link=False, rel_drop=0, legacy=False, absent_alt=False):
    """extended_fixture with 16 equations, NVVDD +0x13 -> constant 800 mV (eq 8), MSVDD +0x13 -> min/max (eq 9).

    OV (eq 2) becomes a constant 1200 mV equation; REL (eq 0) is clamped to 900..1000 mV.
    shared_slot: another NVVDD row word (offset) also selects eq 8; linked: eq 10 links to
    eq 8; own_link: eq 8 links to eq 11; rel_drop: REL links to a constant -rel_drop uV.
    legacy adds a legacy-image object directory: 0xfa, 0xbd (PCIR moved behind it), 0x21
    over the rail table, 0x35 around it.
    """
    blob = bytearray(extended_fixture(absent_alt=absent_alt))
    parsed = backend(from_bytes(bytes(blob)))
    rail, (vfe, base) = parsed.pointer('P', 0x68), vfe_base(parsed)
    blob[vfe + 5], blob[vfe + 10] = 16, 0
    for eq in range(8):
        blob[base + 25 * eq + 24] = 0xFF  # next link 0xffff: none, as in the corpus
    constant(blob, base + 25 * 8, 800000, link=11 if own_link else 0xFFFF)
    constant(blob, base + 25 * 11, 0)
    blob[base + 25 * 9:base + 25 * 9 + 25] = bytes(25)
    blob[base + 25 * 9:base + 25 * 9 + 3] = bytes((2, 0, 0xFF))
    blob[base + 25 * 9 + 11:base + 25 * 9 + 13] = bytes((5, 6))
    blob[base + 25 * 9 + 23:base + 25 * 9 + 25] = bytes((2, 0xFF))
    constant(blob, base + 25 * 2, 1200000)
    for i, eq in enumerate((8, 9)):
        struct.pack_into('<H', blob, rail + 5 + 65 * i + 0x13, eq)
    if shared_slot:
        struct.pack_into('<H', blob, rail + 5 + shared_slot, 8)
    if rel_drop:
        blob[base + 2], blob[base + 24] = 12, 0
        constant(blob, base + 25 * 12, -rel_drop)
    if linked:
        blob[base + 25 * 10:base + 25 * 10 + 25] = bytes(25)
        constant(blob, base + 25 * 10, 15000, link=8)
    if legacy:
        add_legacy_directory(blob, parsed)
    return repair_fixture(blob)


def add_legacy_directory(blob, parsed):
    start, rail = parsed.legacy['start'], parsed.pointer('P', 0x68)
    header, count = start + 718, 4
    base = header + 16 + 60 * count
    pcir = base + 2
    blob[pcir:pcir + 24] = blob[parsed.legacy['pcir']:parsed.legacy['pcir'] + 24]
    blob[parsed.legacy['pcir']:parsed.legacy['pcir'] + 4] = bytes(4)
    struct.pack_into('<H', blob, start + 24, pcir - start)
    struct.pack_into('<IIII', blob, header, 3, 16, count, parsed.legacy['device'])
    for i, (oid, at, size) in enumerate(((0xFA, base, 2), (0xBD, pcir, 24), (0x21, rail, 135),
                                         (0x35, base, rail + 200 - base))):
        entry = header + 16 + 60 * i
        struct.pack_into('<III', blob, entry, oid, at - base, size)
        blob[entry + 12:entry + 60] = hashlib.sha384(blob[at:at + size]).digest()
    blob[start + 0x209:start + 0x239] = hashlib.sha384(blob[header:base]).digest()


class BlackwellVminTests(unittest.TestCase):
    def test_constant_equation_takes_vmin_up_to_the_rel_minimum(self):
        image = from_bytes(blackwell_vmin())
        fields = descriptors(image)
        field = fields['nvvdd_vmin_mv']
        self.assertEqual((field['label'], field['current'], field['editable'], field['experimental']),
                         ('NVVDD minimum voltage (VMIN)', 800, True, True))
        self.assertEqual((field['bounds']['minimum'], field['bounds']['maximum']), (450, 900))
        self.assertIn('RTX 5080', field['reason'])
        self.assertEqual(field['selector'], {'raw': 8, 'width_bits': 16, 'offset': field['selector']['offset'],
                                             'absent': False})
        msvdd = fields['msvdd_vmin_mv']
        self.assertFalse(msvdd['editable'])
        self.assertIsNone(msvdd['current'])
        self.assertIn('min/max equation tree', msvdd['reason'])
        result = edit(image, {'nvvdd_vmin_mv': 850})
        at = field['equation_offset']
        self.assertEqual([e['offset'] for e in result.manifest['edits']], [at + 3, at + 7, at + 11])
        self.assertEqual(struct.unpack_from('<fffff', result.blob, at + 3), (850000, 850000, 850000, 0, 0))
        changed_bytes_within(self, image, result, [at + 3, at + 7, at + 11])
        self.assertEqual(descriptors(result.image)['nvvdd_vmin_mv']['current'], 850)
        for value in (449, 901, '850.0001'):
            with self.subTest(value=value), self.assertRaises(VbiosError) as exc:
                edit(image, {'nvvdd_vmin_mv': value})
            self.assertIn(exc.exception.code, ('OUT_OF_BOUNDS', 'UNREPRESENTABLE_VALUE'))

    def test_shared_or_linked_vmin_equation_is_read_only(self):
        # +0x15 is a row selector slot, +0x29/+0x3f the trailing block (voltage equations on Max-Q/SFF rows).
        for options in ({'shared_slot': 0x15}, {'shared_slot': 0x29}, {'shared_slot': 0x3F}, {'linked': True}):
            with self.subTest(**options):
                field = descriptors(from_bytes(blackwell_vmin(**options)))['nvvdd_vmin_mv']
                self.assertFalse(field['editable'])
                self.assertEqual(field['current'], None)
                self.assertIn('another equation or rail selector', field['reason'])
        # A next link of its own adds another equation: not a constant.
        field = descriptors(from_bytes(blackwell_vmin(own_link=True)))['nvvdd_vmin_mv']
        self.assertEqual((field['editable'], field['current']), (False, None))
        self.assertIn('not a constant voltage equation', field['reason'])

    def test_vmin_stays_at_most_the_lowest_rel_value(self):
        # REL (900..1000 mV) chained to a -50 mV constant can drop to 850 mV: the new top.
        image = from_bytes(blackwell_vmin(rel_drop=50000))
        field = descriptors(image)['nvvdd_vmin_mv']
        self.assertEqual((field['editable'], field['bounds']['maximum']), (True, 850))
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'nvvdd_vmin_mv': 851})
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        # Chained to -150 mV, REL can drop to 750 mV, below the stored 800 mV: read-only.
        field = descriptors(from_bytes(blackwell_vmin(rel_drop=150000)))['nvvdd_vmin_mv']
        self.assertEqual((field['editable'], field['current']), (False, 800))
        self.assertIn('up to 750 mV', field['reason'])

    def test_vmin_slot_is_read_only_and_not_named_vmin(self):
        image = from_bytes(blackwell_vmin())
        field = descriptors(image)['nvvdd_vmin_equation_max_mv']
        self.assertFalse(field['editable'])
        self.assertIn('not the evaluated VMIN', field['label'])
        self.assertIn('row +0x21', field['reason'])
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'nvvdd_vmin_equation_max_mv': 950})
        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')

    def test_guard_allows_only_the_canonical_floats(self):
        image = from_bytes(blackwell_vmin())
        at = descriptors(image)['nvvdd_vmin_mv']['equation_offset']
        # An extension writing the value float alone, or an alias of the canonical key.
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'probe': 850}, field_registry=custom_registry('probe', [at + 11], encoding='<f',
                                                                        bounds={'minimum': 0, 'maximum': 2000}))
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')
        alias = custom_registry('nvvdd_vmin_mv', [at + 3, at + 7], encoding='<f',
                                bounds={'minimum': 0, 'maximum': 2000})
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'nvvdd_vmin_mv': 850}, field_registry=alias)
        self.assertEqual(exc.exception.code, 'INVALID_FIELD_EVIDENCE')


def ada_vmin(*, family='ada', pinned=True, value=560000, bounded=True):
    """Row byte 7 -> equation 6: Ada quadratic clamped to value (560 mV) and chained to equation 7; Ampere constant 700 mV.

    Equation 7 is a temperature slope clamped to 0..75 mV, or unclamped when not bounded.
    """
    blob = synthetic_rom(copies=2) if family == 'ada' else synthetic_rom(family='ampere')
    parsed = backend(from_bytes(blob))
    rail, (vfe, base) = parsed.pointer('P', 0x68), vfe_base(parsed)
    if family == 'ada':
        eq = bytearray(25)
        eq[0:3] = bytes((1, 1, 7))
        struct.pack_into('<fffff', eq, 3, value, value if pinned else 600000, 575000, -15000, 0)
        eq[23:25] = bytes((2, 0))
        blob = patched(blob, base + 6 * 25, bytes(eq))
        tail = bytearray(25)
        tail[0:3] = bytes((1, 0, 0xFF))
        struct.pack_into('<fffff', tail, 3, *((0, 75000) if bounded else (-3.4e38, 3.4e38)), 50000, -1000, 0)
        tail[23:25] = bytes((2, 0xFF))
        blob = patched(blob, base + 7 * 25, bytes(tail))
        return patched(blob, rail + 5 + 7, bytes((6,)))
    blob = patched(blob, vfe + 5, bytes((10,)))
    eq = bytearray(24)
    eq[0:3] = bytes((1, 0x0A, 9))
    struct.pack_into('<fffff', eq, 3, 700000, 700000, 700000, 0, 0)
    eq[23] = 2
    blob = patched(blob, base + 8 * 24, bytes(eq))
    # Equation 9: the temperature term clamped to 0..75 mV, u8 links (0xff = none).
    eq[0:3] = bytes((1, 0x0B, 0xFF))
    struct.pack_into('<fffff', eq, 3, 0, 75000, 51000, -714, 0)
    blob = patched(blob, base + 9 * 24, bytes(eq))
    return patched(blob, rail + 5 + 7, bytes((8,)))


class AdaVminTests(unittest.TestCase):
    def test_pinned_clamp_takes_vmin_in_both_chains(self):
        image = from_bytes(ada_vmin())
        parser = backend(image)
        field = descriptors(image)['nvvdd_vmin_mv']
        self.assertEqual((field['current'], field['editable'], field['experimental']), (560, True, True))
        # REL is at least 915 mV and equation 7 adds up to 75 mV on top of the clamp.
        self.assertEqual((field['bounds']['minimum'], field['bounds']['maximum']), (400, 840))
        self.assertIn('add 0 to 75 mV', field['reason'])
        self.assertIn('plus 90 mV', field['reason'])
        at = field['equation_offset']
        offsets = parser.copy_offsets(at + 3, 4) + parser.copy_offsets(at + 7, 4)
        self.assertEqual(len(offsets), 4)
        result = edit(image, {'nvvdd_vmin_mv': 700})
        self.assertEqual(sorted(e['offset'] for e in result.manifest['edits']), sorted(offsets))
        for copy in parser.copy_offsets(at, 25):
            self.assertEqual(struct.unpack_from('<fffff', result.blob, copy + 3), (700000, 700000, 575000, -15000, 0))
        changed_bytes_within(self, image, result, offsets)
        self.assertTrue(result.manifest['integrity']['valid'])
        self.assertEqual(descriptors(result.image)['nvvdd_vmin_mv']['current'], 700)

    def test_unpinned_clamp_and_slot_are_read_only(self):
        fields = descriptors(from_bytes(ada_vmin(pinned=False)))
        self.assertFalse(fields['nvvdd_vmin_mv']['editable'])
        self.assertIn('does not pin', fields['nvvdd_vmin_mv']['reason'])
        for options, text in (({'bounded': False}, 'no bounded value'), ({'value': 560000.5}, 'not a whole uV')):
            with self.subTest(**options):
                field = descriptors(from_bytes(ada_vmin(**options)))['nvvdd_vmin_mv']
                self.assertFalse(field['editable'])
                self.assertIn(text, field['reason'])
        slot = fields['nvvdd_vmin_equation_max_mv']
        self.assertFalse(slot['editable'])
        self.assertIn('did not change the driver VMIN', slot['reason'])

    def test_ampere_same_layout_is_offered_untested(self):
        image = from_bytes(ada_vmin(family='ampere'))
        fields = descriptors(image)
        field = fields['nvvdd_vmin_mv']
        self.assertEqual((field['current'], field['editable'], field['bounds']['maximum']), (700, True, 1006.25))
        self.assertIn('not hardware-tested on Ampere', field['reason'])
        # Rail 1 selects rail 0's REL equation at byte 7: shared, read-only.
        self.assertFalse(fields['msvdd_vmin_mv']['editable'])
        result = edit(image, {'nvvdd_vmin_mv': 650})
        self.assertEqual(descriptors(result.image)['nvvdd_vmin_mv']['current'], 650)

    def test_minmax_children_use_high_bytes_15_and_16(self):
        # Equation 6 is a min/max whose first child is REL (2): high byte 15 = 0, byte 19 = 1.
        # Read with the old high bytes 19/20 the child would be 0x102 and REL would look unshared.
        blob = synthetic_rom()
        base = vfe_base(backend(from_bytes(blob)))[1]
        eq = bytearray(25)
        eq[0:3], eq[11:13], eq[15:17], eq[19:21] = bytes((2, 0, 0xFF)), bytes((2, 0xFF)), bytes((0, 0xFF)), bytes((1, 0xFF))
        eq[23:25] = bytes((2, 0xFF))
        image = from_bytes(patched(blob, base + 6 * 25, bytes(eq)))
        self.assertIn(2, backend(image)._ada_references(base, 8))
        fields = descriptors(image)
        self.assertFalse(fields['nvvdd_rel_max_mv']['editable'])
        self.assertEqual(fields['nvvdd_rel_equation_max_mv']['equation_kind'], 'shared')
        self.assertTrue(descriptors(from_bytes(blob))['nvvdd_rel_max_mv']['editable'])


class FollowOvTests(unittest.TestCase):
    def test_legacy_directory_is_required(self):
        image = from_bytes(blackwell_vmin())
        self.assertIsNone(inspect_image(image)['integrity']['legacy_directory'])
        field = descriptors(image)['nvvdd_rel_alt_follow_ov']
        self.assertEqual((field['current'], field['editable'], field['opt_in']), (0, False, True))
        self.assertIn('legacy-image object 0x21', field['reason'])
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'nvvdd_rel_alt_follow_ov': 1})
        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')

    def test_rel_and_alt_follow_ov_with_legacy_repairs(self):
        image = from_bytes(blackwell_vmin(legacy=True))
        parser = backend(image)
        self.assertEqual(inspect_image(image)['integrity']['legacy_directory'],
                         {'object_count': 4, 'bad_object_ids': [], 'directory_sha384_valid': True})
        fields = descriptors(image)
        field = fields['nvvdd_rel_alt_follow_ov']
        self.assertEqual((field['current'], field['editable'], field['experimental'], field['opt_in']),
                         (0, True, True, True))
        self.assertEqual((field['bounds']['minimum'], field['bounds']['maximum']), (0, 1))
        self.assertIn('1200 mV', field['reason'])
        self.assertEqual(edit(image, {'nvvdd_rel_alt_follow_ov': 0}).manifest['changed_bytes'], 0)
        result = edit(image, {'nvvdd_rel_alt_follow_ov': 1})
        row = parser.pointer('P', 0x68) + 5
        self.assertEqual(struct.unpack_from('<HHH', result.blob, row + 0x0D), (2, 2, 2))
        legacy = {(r.get('object_id'), r['kind']) for r in result.manifest['integrity_repairs']
                  if r.get('directory') == 'legacy'}
        self.assertEqual(legacy, {(0x21, 'object_sha384'), (0x35, 'object_sha384'), (None, 'directory_sha384')})
        self.assertIn(parser.legacy['end'] - 1, {r['offset'] for r in result.manifest['integrity_repairs']})
        changed_bytes_within(self, image, result, [row + 0x0D, row + 0x0F], width=2)
        target = backend(result.image)
        self.assertTrue(target.legacy_valid())
        self.assertTrue(target.integrity()['valid'])
        after = descriptors(result.image)
        self.assertEqual((after['nvvdd_rel_alt_follow_ov']['current'], after['nvvdd_rel_alt_follow_ov']['editable']),
                         (1, False))
        self.assertIn('cannot restore', after['nvvdd_rel_alt_follow_ov']['reason'])
        self.assertEqual(after['nvvdd_rel_equation_max_mv']['current'], 1200)
        self.assertEqual(after['msvdd_rel_equation_max_mv'], fields['msvdd_rel_equation_max_mv'])

    def test_voltage_fields_need_a_separate_edit_and_extensions_cannot_move_selectors(self):
        image = from_bytes(blackwell_vmin(legacy=True))
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'nvvdd_rel_alt_follow_ov': 1, 'nvvdd_vmin_mv': 850})
        self.assertEqual(exc.exception.code, 'SEPARATE_EDIT_REQUIRED')
        row = backend(image).pointer('P', 0x68) + 5
        probe = custom_registry('probe', [row + 0x0D], encoding='<H', scale=1, bounds={'minimum': 0, 'maximum': 9})
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'probe': 2}, field_registry=probe)
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')

    def test_without_alt_only_rel_moves(self):
        image = from_bytes(blackwell_vmin(legacy=True, absent_alt=True))
        field = descriptors(image)['nvvdd_rel_alt_follow_ov']
        self.assertEqual((field['current'], field['editable']), (0, True))
        self.assertIn('REL selector (this image has no ALT selector)', field['reason'])
        self.assertIn('REL = OV,', field['reason'])
        row = backend(image).pointer('P', 0x68) + 5
        result = edit(image, {'nvvdd_rel_alt_follow_ov': 1})
        self.assertEqual(struct.unpack_from('<HHH', result.blob, row + 0x0D), (2, 0xFFFF, 2))
        changed_bytes_within(self, image, result, [row + 0x0D], width=2)
        after = descriptors(result.image)['nvvdd_rel_alt_follow_ov']
        self.assertEqual((after['current'], after['editable']), (1, False))
        self.assertIn('already selected by the NVVDD REL selector', after['reason'])

    def test_other_rail_table_and_legacy_bytes_are_refused(self):
        image = from_bytes(blackwell_vmin(legacy=True))
        parser = backend(image)
        row = parser.pointer('P', 0x68) + 5
        # A rail row word outside the follow-OV binding (no role selector at +0x15).
        probe = custom_registry('probe', [row + 0x15], encoding='<H', scale=1, bounds={'minimum': 0, 'maximum': 9})
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'probe': 3}, field_registry=probe)
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')
        self.assertIn('rail table bytes must be preserved', str(exc.exception))
        # Legacy object 0xfa lies outside the rail table.
        at = next(o['data'] for o in parser.legacy_objects if o['id'] == 0xFA)
        probe = custom_registry('probe', [at], encoding='<B', scale=1, bounds={'minimum': 0, 'maximum': 255})
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'probe': image.blob[at] ^ 1}, field_registry=probe)
        self.assertIn('limited to the rail table', str(exc.exception))

    def test_edit_must_reparse_with_a_valid_legacy_directory(self):
        image = from_bytes(blackwell_vmin(legacy=True))
        valid = BlackwellRom.legacy_valid
        # The source verifies; the rebuilt copy is made to fail, as a missed repair would.
        with mock.patch.object(BlackwellRom, 'legacy_valid', autospec=True,
                               side_effect=lambda self: self.blob == image.blob and valid(self)):
            with self.assertRaises(VbiosError) as exc:
                edit(image, {'nvvdd_rel_alt_follow_ov': 1})
        self.assertEqual(exc.exception.code, 'INTEGRITY_FAILED')

    def test_broken_legacy_hash_keeps_the_field_read_only(self):
        blob = bytearray(blackwell_vmin(legacy=True))
        parsed = backend(from_bytes(bytes(blob)))
        owner = next(o for o in parsed.legacy_objects if o['id'] == 0x35)
        blob[owner['data'] + owner['size'] - 1] ^= 1
        image = from_bytes(repair_fixture(blob))
        report = inspect_image(image)['integrity']
        self.assertTrue(report['valid'])
        self.assertEqual(report['legacy_directory']['bad_object_ids'], [0x35])
        self.assertFalse(descriptors(image)['nvvdd_rel_alt_follow_ov']['editable'])


if __name__ == '__main__':
    unittest.main()
