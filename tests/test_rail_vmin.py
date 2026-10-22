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
from nvidia_vbios.rom import VbiosError, ada_general, from_bytes, inspect_image, load, normalize
from nvidia_vbios.rom.blackwell import BlackwellRom
from nvidia_vbios.rom.image import backend
from nvidia_vbios.rom.structure import vfe_free_slot
from test_ada_fields import messages, patched
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


# The synthetic shape of the RTX 4090 95.02.3C VMIN (TableRom._vmin_clone): the VMIN equation, the 15 mV constant
# that links it, the GPC root, the first unused slot and the memory clock entries 8..11 that name the constant.
CLONE_VMIN, CLONE_CONSTANT, CLONE_GPC_ROOT, CLONE_SLOT = 6, 8, 9, 10
CLONE_MEMORY_MHZ = ((0x03, 405), (0x03, 810), (0x03, 5001), (0x13, 10251), (0x13, 10501))


def ada_vmin_clone():
    """ada_vmin() with a constant sharing the VMIN equation, at the synthetic scale.

    Row byte 7 selects equation 6 (clamp 560 mV, next 7). Equation 8 is a 15 mV voltage constant whose next link
    is 6, 9 a GPC root (compare, MHz output), 0, 1 and 5 fixed-point equations and 10..15 unused slots (16
    equations). The BIT C token grows to 16 bytes for a clock programming table (C+0x0c, version 0x40, twelve
    15-byte entries): entry 0 names the GPC root, the memory entries 7..11 run at 405..10501 MHz and 8..11 name
    the constant, entry 7 (the idle clock) and the others name no equation.
    """
    blob = bytearray(ada_vmin())
    parsed = backend(from_bytes(bytes(blob)))
    vfe, base = vfe_base(parsed)
    start = parsed.legacy['start']
    bit = blob.find(b'\xff\xb8BIT\x00', start)
    table = start + 7800  # free data-image bytes after the clocks table, before the power channels
    writes = [(vfe + 5, bytes((16,))), (bit + 18 + 2, struct.pack('<H', 16)),
              (parsed.tokens['C']['data'] + 0x0C, struct.pack('<I', 7800 - 512))]
    eq = bytearray(25)
    eq[0:3], eq[23:25] = bytes((4, 0, 0xFF)), bytes((2, 0xFF))
    writes += [(base + 25 * i, bytes(eq)) for i in (0, 1, 5)]
    constant(eq, 0, 15000, link=CLONE_VMIN)
    eq[1] = 0
    writes.append((base + 25 * CLONE_CONSTANT, bytes(eq)))
    root = bytearray(25)
    root[0:3], root[15:17], root[19:21], root[23:25] = bytes((3, 0, 0xFF)), b'\xff\xff', b'\xff\xff', bytes((1, 0xFF))
    struct.pack_into('<ff', root, 3, 210, 3450)
    writes.append((base + 25 * CLONE_GPC_ROOT, bytes(root)))
    writes += [(base + 25 * i, vfe_free_slot(25)) for i in range(CLONE_SLOT, 16)]
    entries = bytearray(bytes.fromhex('40 08 0f 0c 00 00 00 00') + bytes(12 * 15))
    for i in range(12):
        e = 8 + 15 * i
        flags, mhz = CLONE_MEMORY_MHZ[i - 7] if 7 <= i <= 11 else (0x11 if i == 0 else 0x03, 100 * (i + 1))
        index = CLONE_GPC_ROOT if i == 0 else CLONE_CONSTANT if 8 <= i <= 11 else 0xFFFF
        entries[e:e + 4] = struct.pack('<BHB', flags, mhz, index & 0xFF)
        entries[e + 4], entries[e + 13], entries[e + 14] = 0xFF, index >> 8, 0xFF
    writes.append((table, bytes(entries)))
    for at, data in writes:
        for copy in parsed.copy_offsets(at, len(data)):
            blob[copy:copy + len(data)] = data
    for begin, end in parsed.image_regions:
        blob[end - 1] = (blob[end - 1] - sum(blob[begin:end])) & 255
    return bytes(blob)


def clone_positions(image):
    """(equation base, clock programming table, rail row) of an ada_vmin_clone() image."""
    parsed = backend(image)
    return vfe_base(parsed)[1], parsed.pointer('C', 0x0C), parsed.pointer('P', 0x68) + 5


class AdaVminCloneTests(unittest.TestCase):
    def changed(self, image, result):
        return {i for i, (a, b) in enumerate(zip(image.blob, result.blob)) if a != b}

    def test_shared_vmin_equation_takes_vmin_through_a_copy(self):
        image = from_bytes(ada_vmin_clone())
        parser = backend(image)
        base = clone_positions(image)[0]
        field = descriptors(image)['nvvdd_vmin_mv']
        self.assertEqual((field['current'], field['editable'], field['experimental'], field.get('opt_in')),
                         (560, True, True, None))
        self.assertEqual((field['bounds']['minimum'], field['bounds']['maximum']), (400, 840))
        self.assertEqual(field['vfe_clone'], dict(state='coupled', referrer=8, slot=10, stock_mv=560, constant_mv=15,
                                                  memory_mhz=[810, 5001, 10251, 10501], idle_memory_mhz=405))
        for text in ('a 15 mV constant also links that equation', 'from 810 MHz up', 'VFE slot 10',
                     'its lowest clock (405 MHz, single-monitor idle)', 'the override might not load',
                     'a higher one shows at every memory clock only above 575 mV',
                     'removing the override brings the card back', 'change it in a separate edit'):
            self.assertIn(text, field['reason'])
        vmin, constant_at, slot = (base + 25 * i for i in (CLONE_VMIN, CLONE_CONSTANT, CLONE_SLOT))
        stock = image.blob[vmin:vmin + 25]
        clamp = {at for o in (3, 7) for c in parser.copy_offsets(vmin + o, 4) for at in range(c, c + 4)}
        copy_bytes = {at for c in parser.copy_offsets(slot, 25) for at in range(c, c + 25)}
        # Link bytes 2 and 24; slot 10 changes only byte 2 (the high byte stays 0).
        links = {c + k for k in (2, 24) for c in parser.copy_offsets(constant_at, 1)}
        checksums = {end - 1 for _, end in parser.image_regions}
        result = edit(image, {'nvvdd_vmin_mv': 600})
        self.assertTrue(result.manifest['integrity']['valid'])
        changed = self.changed(image, result)
        self.assertLessEqual(changed, clamp | copy_bytes | links | checksums)
        self.assertEqual(changed & links, {c + 2 for c in parser.copy_offsets(constant_at, 1)})
        self.assertTrue(changed & clamp and changed & copy_bytes)
        for c, k in zip(parser.copy_offsets(slot, 25), parser.copy_offsets(constant_at, 25)):
            self.assertEqual(result.blob[c:c + 25], stock)
            self.assertEqual((result.blob[k + 2], result.blob[k + 24]), (CLONE_SLOT, 0))
        for c in parser.copy_offsets(vmin, 25):
            self.assertEqual(struct.unpack_from('<ff', result.blob, c + 3), (600000, 600000))
        self.assertIn('raw bytes', {e['stored_units'] for e in result.manifest['edits']})
        after = descriptors(result.image)['nvvdd_vmin_mv']
        self.assertEqual((after['current'], after['vfe_clone']['state'], after['vfe_clone']['slot']),
                         (600, 'decoupled', CLONE_SLOT))
        # The constant keeps its value through the copy; VMIN alone changes.
        item = backend(result.image).rail_vmin()[0]
        self.assertEqual((item['value_uv'], item['clone']['stock_uv']), (600000, 560000))
        # Another value moves only the clamp; the stock value restores every byte.
        again = edit(result.image, {'nvvdd_vmin_mv': 700})
        self.assertLessEqual(self.changed(result.image, again), clamp | checksums)
        self.assertEqual(edit(again.image, {'nvvdd_vmin_mv': 560}).blob, image.blob)
        self.assertEqual(edit(result.image, {'nvvdd_vmin_mv': 560}).blob, image.blob)
        for value in (399, 841):
            with self.subTest(value=value), self.assertRaises(VbiosError) as exc:
                edit(image, {'nvvdd_vmin_mv': value})
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_gpc_curve_offset_and_vmin_need_separate_edits_in_either_order(self):
        image = from_bytes(ada_vmin_clone())
        base = clone_positions(image)[0]
        self.assertEqual(backend(image).gpc_curve()['slot'], CLONE_SLOT)
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'nvvdd_vmin_mv': 600, 'gpc_curve_offset_mhz': 30})
        self.assertEqual((exc.exception.code, exc.exception.details['fields']),
                         ('SEPARATE_EDIT_REQUIRED', ['nvvdd_vmin_mv', 'gpc_curve_offset_mhz']))
        # VMIN first: the copy takes slot 10, the offset slot 11; revert in either order.
        vmin = edit(image, {'nvvdd_vmin_mv': 600}).image
        both = edit(vmin, {'gpc_curve_offset_mhz': 30}).image
        self.assertEqual(backend(both).gpc_curve()['slot'], CLONE_SLOT + 1)
        self.assertEqual(descriptors(both)['nvvdd_vmin_mv']['vfe_clone']['slot'], CLONE_SLOT)
        self.assertEqual(edit(edit(both, {'gpc_curve_offset_mhz': 0}).image, {'nvvdd_vmin_mv': 560}).blob, image.blob)
        gap = edit(both, {'nvvdd_vmin_mv': 560}).image
        self.assertEqual(gap.blob[base + 25 * CLONE_SLOT:base + 25 * CLONE_SLOT + 25], vfe_free_slot(25))
        self.assertEqual(descriptors(gap)['nvvdd_vmin_mv']['vfe_clone']['state'], 'coupled')
        self.assertEqual(edit(gap, {'gpc_curve_offset_mhz': 0}).blob, image.blob)
        # The offset first: it takes slot 10 and the copy slot 11; reverting the offset first leaves 10 unused
        # below the copy, and the copy is still found through the constant's link.
        gpc = edit(image, {'gpc_curve_offset_mhz': -30}).image
        both = edit(gpc, {'nvvdd_vmin_mv': 620}).image
        self.assertEqual((backend(both).gpc_curve()['slot'], descriptors(both)['nvvdd_vmin_mv']['vfe_clone']['slot']),
                         (CLONE_SLOT, CLONE_SLOT + 1))
        gap = edit(both, {'gpc_curve_offset_mhz': 0}).image
        self.assertEqual(gap.blob[base + 25 * CLONE_SLOT:base + 25 * CLONE_SLOT + 25], vfe_free_slot(25))
        clone = descriptors(gap)['nvvdd_vmin_mv']['vfe_clone']
        self.assertEqual((clone['state'], clone['slot']), ('decoupled', CLONE_SLOT + 1))
        self.assertEqual(edit(gap, {'nvvdd_vmin_mv': 560}).blob, image.blob)
        self.assertEqual(edit(edit(both, {'nvvdd_vmin_mv': 560}).image, {'gpc_curve_offset_mhz': 0}).blob, image.blob)

    def test_a_copy_with_the_vmin_clamp_keeps_its_bytes(self):
        # A copy whose clamp equals the VMIN equation's (a layout no edit makes): the current value changes
        # nothing, another value moves only the clamp, and the stock value then gives the coupled shape.
        image = from_bytes(ada_vmin_clone())
        parser = backend(image)
        vmin = clone_positions(image)[0] + 25 * CLONE_VMIN
        clamp = {at for o in (3, 7) for c in parser.copy_offsets(vmin + o, 4) for at in range(c, c + 4)}
        checksums = {end - 1 for _, end in parser.image_regions}
        blob = bytearray(edit(image, {'nvvdd_vmin_mv': 600}).blob)
        for at in parser.copy_offsets(vmin + 3, 4) + parser.copy_offsets(vmin + 7, 4):
            struct.pack_into('<f', blob, at, 560000)
        for begin, end in parser.image_regions:
            blob[end - 1] = (blob[end - 1] - sum(blob[begin:end])) & 255
        vendor = from_bytes(bytes(blob))
        field = descriptors(vendor)['nvvdd_vmin_mv']
        self.assertEqual((field['current'], field['editable'], field['vfe_clone']['state']), (560, True, 'decoupled'))
        self.assertEqual(edit(vendor, {'nvvdd_vmin_mv': 560}).blob, vendor.blob)
        moved = edit(vendor, {'nvvdd_vmin_mv': 600})
        self.assertLessEqual(self.changed(vendor, moved), clamp | checksums)
        self.assertEqual(edit(moved.image, {'nvvdd_vmin_mv': 560}).blob, image.blob)
        self.assertIn('change VMIN in a separate edit', descriptors(image)['gpc_curve_offset_mhz']['reason'])

    def test_guard_allows_only_the_canonical_copy_and_link(self):
        from decimal import Decimal
        from nvidia_vbios.editor import Binding, FieldRegistry
        image = from_bytes(ada_vmin_clone())
        parser = backend(image)
        base = clone_positions(image)[0]
        vmin, constant_at, slot = (base + 25 * i for i in (CLONE_VMIN, CLONE_CONSTANT, CLONE_SLOT))
        clamp = parser.copy_offsets(vmin + 3, 4) + parser.copy_offsets(vmin + 7, 4)
        # The clamp alone, under the reviewed key: not the complete binding.
        alias = custom_registry('nvvdd_vmin_mv', clamp, encoding='<f', bounds={'minimum': 0, 'maximum': 2000})
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'nvvdd_vmin_mv': 600}, field_registry=alias)
        self.assertEqual(exc.exception.code, 'INVALID_FIELD_EVIDENCE')
        # The constant's link, or the copy in its slot, under another key.
        decoupled = edit(image, {'nvvdd_vmin_mv': 600}).image
        for source, at in ((image, constant_at + 1), (decoupled, constant_at + 1), (decoupled, slot + 11)):
            current = struct.unpack_from('<h', source.blob, at)[0]
            with self.subTest(at=at - base), self.assertRaises(VbiosError) as exc:
                edit(source, {'probe': current ^ 0x0100}, field_registry=custom_registry(
                    'probe', parser.copy_offsets(at, 2), encoding='<h', scale=1,
                    bounds={'minimum': -32768, 'maximum': 32767}))
            self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')
        # Companion bytes from an extension binding are refused.
        custom = FieldRegistry()

        @custom.register
        def probe(image, parser):
            descriptor = dict(key='probe', label='probe', type='number', units='probe', current=0, editable=True,
                              bounds={'minimum': -10, 'maximum': 10}, evidence=[{'kind': 'synthetic-test'}])
            return [Binding(descriptor, tuple(parser.copy_offsets(slot + 3, 4)), '<f', Decimal(1),
                            companion=((None, ((constant_at + 2, b'\x0a'),)),))]
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'probe': 1}, field_registry=custom)
        self.assertEqual(exc.exception.code, 'INVALID_FIELD_EVIDENCE')

    def test_other_shapes_keep_the_shared_vmin_read_only(self):
        blob = ada_vmin_clone()
        image = from_bytes(blob)
        base, table, row = clone_positions(image)

        def eq(index, offset):
            return base + 25 * index + offset

        def entry(index, offset):
            return table + 8 + 15 * index + offset
        variants = {
            'constant referenced by another equation': [(eq(5, 2), b'\x08'), (eq(5, 24), b'\x00')],
            'constant with a slope': [(eq(CLONE_CONSTANT, 15), struct.pack('<f', 1.0))],
            'constant not a voltage': [(eq(CLONE_CONSTANT, 23), b'\x01')],
            'VMIN also linked by another equation': [(eq(5, 2), b'\x06'), (eq(5, 24), b'\x00')],
            'VMIN a min/max child instead': [(eq(CLONE_CONSTANT, 2), b'\xff'), (eq(CLONE_CONSTANT, 24), b'\xff'),
                                             (eq(5, 0), b'\x02'), (eq(5, 11), b'\x06'), (eq(5, 15), b'\x00')],
            'clock programming entry names VMIN': [(entry(1, 3), b'\x06'), (entry(1, 13), b'\x00')],
            'another row byte selects VMIN': [(row + 9, b'\x06')],
            'first unused slot not clean': [(eq(CLONE_SLOT, 1), b'\x00')],
            'no memory entry names the constant': [(entry(i, 3), b'\xff') for i in range(8, 12)] +
                                                  [(entry(i, 13), b'\xff') for i in range(8, 12)],
            'idle memory entry names the constant too': [(entry(7, 3), b'\x08'), (entry(7, 13), b'\x00')],
        }
        self.assertTrue(descriptors(image)['nvvdd_vmin_mv']['editable'])
        for name, writes in variants.items():
            with self.subTest(name=name):
                changed = blob
                for at, data in writes:
                    changed = patched(changed, at, data)
                field = descriptors(from_bytes(changed))['nvvdd_vmin_mv']
                self.assertFalse(field['editable'])
                self.assertNotIn('vfe_clone', field)
                self.assertIn('used by another equation or role', field['reason'])
        # Without the clock programming table (a 12-byte C token) the constant's users are unknown.
        bit = blob.find(b'\xff\xb8BIT\x00')
        field = descriptors(from_bytes(patched(blob, bit + 20, struct.pack('<H', 12))))['nvvdd_vmin_mv']
        self.assertEqual((field['editable'], field['current']), (False, None))


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
        self.assertIn('confirmed on one RTX 5090', field['reason'])
        self.assertEqual([(e['kind'], e['set_tested']) for e in field['evidence'][:2]],
                         [('hardware-test', True), ('vendor-image-comparison', False)])
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


def ada_xoc(*, rel='constant', alt='constant'):
    """Ada rail with REL 2 (constant 955 mV or derated 915..955 mV) and ALT 3 (constant 975 mV, derated 935..975 mV or
    absent), in two chains; OV (5, or 4 without ALT) is a constant 1200 mV reading a fixed-point variable, as on Ada."""
    blob = synthetic_rom(copies=2, alt=alt is not None, rel=rel)
    parsed = backend(from_bytes(blob))
    rail, (vfe, base) = parsed.pointer('P', 0x68), vfe_base(parsed)
    if alt == 'constant':
        eq = bytearray(25)
        constant(eq, 0, 975000)
        blob = patched(blob, base + 3 * 25, bytes(eq))
    blob = patched(blob, vfe + 11 + 25, b'\x04')  # variable 1: a fixed-point input, not a temperature
    return patched(blob, base + 25 * parsed.blob[rail + 5 + 6] + 1, b'\x01')


class AdaFollowOvTests(unittest.TestCase):
    def test_rel_and_alt_follow_ov_in_both_chains(self):
        image = from_bytes(ada_xoc(rel='derated', alt='derated'))
        parser = backend(image)
        field = descriptors(image)['nvvdd_rel_alt_follow_ov']
        self.assertEqual((field['current'], field['editable'], field['experimental'], field['opt_in']),
                         (0, True, True, True))
        self.assertEqual((field['bounds']['minimum'], field['bounds']['maximum']), (0, 1))
        self.assertIn('OV equation (1200 mV) in every chain: REL = ALT = OV,', field['reason'])
        self.assertIn('REL spans 915 to 955 mV in this image', field['reason'])
        self.assertIn('not hardware-tested on Ada', field['reason'])
        self.assertFalse(any(e.get('set_tested') for e in field['evidence']))
        self.assertEqual(edit(image, {'nvvdd_rel_alt_follow_ov': 0}).manifest['changed_bytes'], 0)
        row = parser.pointer('P', 0x68) + 5
        selectors = [copy + k for copy in parser.copy_offsets(row + 4, 2) for k in (0, 1)]
        result = edit(image, {'nvvdd_rel_alt_follow_ov': 1})
        self.assertEqual(sorted(e['offset'] for e in result.manifest['edits']), sorted(selectors))
        changed_bytes_within(self, image, result, selectors, width=1)
        self.assertLessEqual({c[0]['end'] - 1 for c in parser.chains}, {r['offset'] for r in result.manifest['integrity_repairs']})
        for copy in parser.copy_offsets(row, 0x1F):
            self.assertEqual(result.blob[copy + 4:copy + 7], bytes((5, 5, 5)))
        target = backend(result.image)
        self.assertTrue(target.integrity()['valid'])
        # REL now selects the constant OV equation, whose variable is not a temperature.
        self.assertEqual(target.rail_limits()[0]['input_variable']['type'], 4)
        after = descriptors(result.image)
        self.assertEqual((after['nvvdd_rel_alt_follow_ov']['current'], after['nvvdd_rel_alt_follow_ov']['editable']),
                         (1, False))
        self.assertIn('cannot restore', after['nvvdd_rel_alt_follow_ov']['reason'])
        self.assertEqual((after['nvvdd_rel_equation_max_mv']['current'], after['nvvdd_alt_equation_max_mv']['current']),
                         (1200, 1200))
        self.assertFalse(after['nvvdd_rel_max_mv']['editable'])
        # The followed REL is the OV equation: it takes no fixed value.
        self.assertFalse(after['nvvdd_rel_fixed_mv']['editable'])
        self.assertIn('is also selected by ALT and OV', after['nvvdd_rel_fixed_mv']['reason'])

    def test_followed_image_reopens_as_1(self):
        blob = ada_xoc()
        row = backend(from_bytes(blob)).pointer('P', 0x68) + 5
        field = descriptors(from_bytes(patched(blob, row + 4, bytes((5, 5)))))['nvvdd_rel_alt_follow_ov']
        self.assertEqual((field['current'], field['editable']), (1, False))
        # REL alone at OV (ALT kept) is no reviewed order.
        image = from_bytes(patched(blob, row + 4, bytes((5,))))
        self.assertNotIn('nvvdd_rel_alt_follow_ov', descriptors(image))
        self.assertTrue(any('unvalidated Ada rail selectors' in m for m in messages(image)))

    def test_without_alt_only_rel_moves(self):
        image = from_bytes(ada_xoc(rel='derated', alt=None))
        parser = backend(image)
        field = descriptors(image)['nvvdd_rel_alt_follow_ov']
        self.assertEqual((field['current'], field['editable']), (0, True))
        self.assertIn('REL selector (this image has no ALT selector)', field['reason'])
        row = parser.pointer('P', 0x68) + 5
        result = edit(image, {'nvvdd_rel_alt_follow_ov': 1})
        changed_bytes_within(self, image, result, parser.copy_offsets(row + 4, 1), width=1)
        self.assertEqual(result.blob[row + 4:row + 7], bytes((4, 0xFF, 4)))
        self.assertEqual(descriptors(result.image)['nvvdd_rel_alt_follow_ov']['current'], 1)

    def test_guards_refuse_other_rail_bytes_and_joint_voltage_edits(self):
        image = from_bytes(ada_xoc())
        parser = backend(image)
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'nvvdd_rel_alt_follow_ov': 1, 'nvvdd_rel_fixed_mv': 960})
        self.assertEqual(exc.exception.code, 'SEPARATE_EDIT_REQUIRED')
        row = parser.pointer('P', 0x68) + 5
        # Row byte 10 holds the REL index on the Ada images; only the canonical binding moves selectors.
        for at, value, text in ((row + 10, 5, 'rail table bytes must be preserved'),
                                (row + 4, 5, 'recognized rail table')):
            with self.subTest(offset=at - row):
                probe = custom_registry('probe', parser.copy_offsets(at, 1), encoding='<B', scale=1,
                                        bounds={'minimum': 0, 'maximum': 9})
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {'probe': value}, field_registry=probe)
                self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')
                self.assertIn(text, str(exc.exception))

    def test_ov_must_be_a_constant_and_the_legacy_image_padded(self):
        blob = ada_xoc()
        parser = backend(from_bytes(blob))
        base = vfe_base(parser)[1]
        image = from_bytes(patched(blob, base + 5 * 25 + 15, struct.pack('<f', -1000)))
        fields = descriptors(image)
        self.assertFalse(fields['nvvdd_rel_alt_follow_ov']['editable'])
        self.assertIn('another shape', fields['nvvdd_rel_alt_follow_ov']['reason'])
        self.assertIn('OV equation is not a constant', fields['nvvdd_rel_fixed_mv']['reason'])
        # The rail table lies in the legacy image: without its checksum padding every field is read-only.
        image = from_bytes(patched(blob, parser.legacy['end'] - 2, b'\x00'))
        self.assertFalse(any(f['editable'] for f in descriptors(image).values()))
        self.assertTrue(any('checksum padding' in m for m in messages(image)))


class AdaFixedVoltageTests(unittest.TestCase):
    def test_constant_rel_and_alt_take_values_in_both_chains_and_revert(self):
        image = from_bytes(ada_xoc())
        parser = backend(image)
        fields = descriptors(image)
        rel, alt = fields['nvvdd_rel_fixed_mv'], fields['nvvdd_alt_fixed_mv']
        self.assertEqual((rel['current'], rel['bounds']['minimum'], rel['bounds']['maximum'], rel['editable'],
                          rel['experimental']), (955, 955, 975, True, True))
        self.assertEqual((alt['current'], alt['bounds']['minimum'], alt['bounds']['maximum']), (975, 975, 1200))
        self.assertEqual(rel['ordering_group'], alt['ordering_group'])
        self.assertIn('higher voltage on its VF curve', rel['reason'])
        self.assertIn('power and thermal limits still apply', rel['reason'])
        at = rel['equation_offset']
        offsets = parser.copy_offsets(at + 7, 4) + parser.copy_offsets(at + 11, 4)
        result = edit(image, {'nvvdd_rel_fixed_mv': 970})
        self.assertEqual(sorted(e['offset'] for e in result.manifest['edits']), sorted(offsets))
        changed_bytes_within(self, image, result, offsets)
        self.assertTrue(result.manifest['integrity']['valid'])
        for copy in parser.copy_offsets(at, 25):
            # The clamp minimum keeps the stock value: the lower bound, and the value to revert to.
            self.assertEqual(struct.unpack_from('<fffff', result.blob, copy + 3), (955000, 970000, 970000, 0, 0))
        after = descriptors(result.image)
        self.assertEqual((after['nvvdd_rel_fixed_mv']['current'], after['nvvdd_rel_fixed_mv']['bounds']['minimum']),
                         (970, 955))
        self.assertEqual(after['nvvdd_rel_equation_max_mv']['equation_kind'], 'constant')
        self.assertEqual(edit(result.image, {'nvvdd_rel_fixed_mv': 955}).blob, image.blob)
        both = edit(image, {'nvvdd_rel_fixed_mv': 1100, 'nvvdd_alt_fixed_mv': 1200})
        alt_at = alt['equation_offset']
        changed_bytes_within(self, image, both, offsets + parser.copy_offsets(alt_at + 7, 4) +
                             parser.copy_offsets(alt_at + 11, 4))
        after = descriptors(both.image)
        self.assertEqual((after['nvvdd_rel_fixed_mv']['current'], after['nvvdd_alt_fixed_mv']['current']), (1100, 1200))
        self.assertEqual(edit(both.image, {'nvvdd_rel_fixed_mv': 955, 'nvvdd_alt_fixed_mv': 975}).blob, image.blob)

    def test_bounds_keep_rel_at_most_alt_and_values_at_least_stock(self):
        image = from_bytes(ada_xoc())
        for changes in ({'nvvdd_rel_fixed_mv': 950}, {'nvvdd_rel_fixed_mv': 980}, {'nvvdd_alt_fixed_mv': 970},
                        {'nvvdd_alt_fixed_mv': 1205}, {'nvvdd_rel_fixed_mv': 1100, 'nvvdd_alt_fixed_mv': 1050}):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes)
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        # Without ALT, REL goes up to the OV value; a derated ALT bounds it at its lowest value.
        fields = descriptors(from_bytes(ada_xoc(alt=None)))
        self.assertNotIn('nvvdd_alt_fixed_mv', fields)
        self.assertEqual(fields['nvvdd_rel_fixed_mv']['bounds']['maximum'], 1200)
        field = descriptors(from_bytes(ada_xoc(alt='derated')))['nvvdd_rel_fixed_mv']
        self.assertFalse(field['editable'])
        self.assertIn('outside 955 mV up to 935 mV', field['reason'])
        # A derated REL keeps its ceiling field; ALT stays at least REL's highest value, also in a joint edit.
        image = from_bytes(ada_xoc(rel='derated'))
        fields = descriptors(image)
        self.assertNotIn('nvvdd_rel_fixed_mv', fields)
        self.assertEqual(fields['nvvdd_alt_fixed_mv']['bounds']['minimum'], 975)
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'nvvdd_rel_equation_max_mv': 990})
        self.assertEqual((exc.exception.code, exc.exception.details['field']), ('OUT_OF_BOUNDS', 'nvvdd_alt_fixed_mv'))
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'nvvdd_rel_equation_max_mv': 990, 'nvvdd_alt_fixed_mv': 980})
        self.assertEqual((exc.exception.code, exc.exception.details['field']), ('OUT_OF_BOUNDS', 'nvvdd_alt_fixed_mv'))
        edit(image, {'nvvdd_rel_equation_max_mv': 990, 'nvvdd_alt_fixed_mv': 990})

    def test_vmin_stays_below_the_rel_of_the_result(self):
        blob = ada_vmin()  # no ALT; the VMIN clamp (560 mV) and its chain (0..75 mV)
        eq = bytearray(25)
        constant(eq, 0, 955000)
        image = from_bytes(patched(blob, vfe_base(backend(from_bytes(blob)))[1] + 2 * 25, bytes(eq)))
        raised = edit(image, {'nvvdd_rel_fixed_mv': 1000}).image
        self.assertEqual(descriptors(raised)['nvvdd_vmin_mv']['bounds']['maximum'], 925)
        # VMIN would be read-only in the result: no range is reported.
        with self.assertRaises(VbiosError) as exc:
            edit(raised, {'nvvdd_rel_fixed_mv': 955, 'nvvdd_vmin_mv': 900})
        self.assertEqual((exc.exception.code, exc.exception.details['field'], exc.exception.details['bounds']),
                         ('OUT_OF_BOUNDS', 'nvvdd_vmin_mv', None))
        self.assertEqual(descriptors(edit(raised, {'nvvdd_rel_fixed_mv': 955, 'nvvdd_vmin_mv': 880}).image)
                         ['nvvdd_vmin_mv']['current'], 880)
        # REL lowered alone may not leave a raised VMIN above the new bound; together they go back to stock.
        vmin = edit(raised, {'nvvdd_vmin_mv': 925}).image
        with self.assertRaises(VbiosError) as exc:
            edit(vmin, {'nvvdd_rel_fixed_mv': 955})
        self.assertEqual((exc.exception.code, exc.exception.details['field']), ('OUT_OF_BOUNDS', 'nvvdd_vmin_mv'))
        self.assertEqual(edit(vmin, {'nvvdd_rel_fixed_mv': 955, 'nvvdd_vmin_mv': 560}).blob, image.blob)

    def test_shared_and_unpinned_constants_are_read_only(self):
        blob = ada_xoc()
        parser = backend(from_bytes(blob))
        row, base = parser.pointer('P', 0x68) + 5, vfe_base(parser)[1]
        # The evaluated VMIN (row byte 7) selects the REL equation.
        field = descriptors(from_bytes(patched(blob, row + 7, b'\x02')))['nvvdd_rel_fixed_mv']
        self.assertFalse(field['editable'])
        self.assertIn('is also selected by the evaluated VMIN', field['reason'])
        # An ALT constant below its clamp maximum.
        field = descriptors(from_bytes(patched(blob, base + 3 * 25 + 11, struct.pack('<f', 960000))))['nvvdd_alt_fixed_mv']
        self.assertFalse(field['editable'])
        self.assertIn('does not hold its constant at its clamp maximum', field['reason'])
        # Ampere and GB20x images have no fixed-value fields.
        for image in (from_bytes(synthetic_rom(family='ampere')), from_bytes(blackwell_vmin(legacy=True))):
            self.assertFalse({'nvvdd_rel_fixed_mv', 'nvvdd_alt_fixed_mv'} & set(descriptors(image)))

    def test_guard_allows_only_the_canonical_floats(self):
        image = from_bytes(ada_xoc())
        parser = backend(image)
        at = descriptors(image)['nvvdd_rel_fixed_mv']['equation_offset']
        alias = custom_registry('nvvdd_rel_fixed_mv', parser.copy_offsets(at + 11, 4), encoding='<f', scale=1000,
                                bounds={'minimum': 0, 'maximum': 2000})
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'nvvdd_rel_fixed_mv': 960}, field_registry=alias)
        self.assertEqual(exc.exception.code, 'INVALID_FIELD_EVIDENCE')
        # Neither the clamp minimum nor the constant alone may change outside the canonical binding.
        for offset in (3, 11):
            probe = custom_registry('probe', parser.copy_offsets(at + offset, 4), encoding='<f', scale=1000,
                                    bounds={'minimum': 0, 'maximum': 2000})
            with self.subTest(offset=offset), self.assertRaises(VbiosError) as exc:
                edit(image, {'probe': 960}, field_registry=probe)
            self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')


if __name__ == '__main__':
    unittest.main()
