"""Turing (TU102-TU117): editor fields and loader payloads on generated images and reference ROMs."""
import contextlib
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nvidia_vbios.editor import edit, normalize_manifest, plan
from nvidia_vbios.editor.registry import registry
from nvidia_vbios.families import architecture
from nvidia_vbios.gui.controller import loader_messages, open_document, save_document, stage_document
from nvidia_vbios.rom import FormatError, VbiosError, from_bytes, inspect_image, load, normalize
from nvidia_vbios.rom.image import backend
from nvidia_vbios.rom.structure import image_chains, scan_images
from nvidia_vbios.rom.turing import npde
from test_ada_fields import THERMAL_FACTORY_KEYS, checked_elsewhere, patched

POWER = ['power_max_w', 'power_default_w', 'power_min_w']
E0_END = 'turing-e0-end-v1'
DESKTOP_CHANNELS = {0: '02 df 00 1b b7 00 00 10', 9: '02 f5 00 1b b7 00 00 10'}
NOTEBOOK_CHANNELS = {0: '02 f5 00 1b b7 00 00 10'}
# Per-input power channels of a two-connector desktop board: PCIe slot 3, connectors 4/5 (rails
# 0xfa/0xfb, provider bytes 1/2) and the NVVDD current sensor 19 (class 1, rail 1, sensor 6).
INPUT_CHANNELS = {3: '05 ff 00 1b b7 00 00 10', 4: '05 fa 00 1b b7 00 00 10 00 00 00 00 00 00 00 01',
                  5: '05 fb 00 1b b7 00 00 10 00 00 00 00 00 00 00 02',
                  19: '01 01 00 1b b7 00 00 10 00 00 00 00 00 00 06'}
# Their rows: (flags byte 0, channel, parameter byte 0, minimum/rated/maximum). Slot and connector
# power (class 4 mW), the slot and connector current thresholds 0/1/2 (class 5 mA) and the NVVDD
# current limit (class 10 mA).
INPUT_ROWS = {3: (0x04, 3, 0, (1000, 63000, 74000)), 4: (0x04, 4, 0, (1000, 143000, 167000)),
              5: (0x04, 5, 0, (1000, 143000, 167000)), 7: (0x15, 3, 0, (1000, 11000, 16500)),
              8: (0x15, 4, 1, (1000, 22500, 33750)), 9: (0x15, 5, 2, (1000, 22500, 33750)),
              13: (0x1A, 19, 0, (1000, 350780, 390000))}
INPUTS = ['slot_power_max_w', 'slot_power_rated_w'] + [
    f'connector_{n}_{kind}' for n in (1, 2) for kind in ('power_max_w', 'power_rated_w')]
THRESHOLDS = ['slot_current_threshold_max_ma', 'slot_current_threshold_rated_ma'] + [
    f'connector_{n}_current_threshold_{side}_ma' for n in (1, 2) for side in ('max', 'rated')] + [
    'nvvdd_output_ocp_max_ma', 'nvvdd_output_ocp_rated_ma']
VOLTAGES = ['nvvdd_vmin_mv', 'nvvdd_rel_fixed_mv', 'nvvdd_alt_fixed_mv']
CLOCKS = ['gpc_offset_max_mhz', 'gpc_offset_min_mhz', 'memory_offset_max_mhz', 'memory_offset_min_mhz',
          'dram_max_table_mhz', 'dram_min_table_mhz']
# v0x35 clock rows (usage, offset minimum/maximum or other parameters, ordering byte) in the GV
# HAL order; the XBAR slave row holds a nonzero parameter where master rows hold their range.
CLOCK_ROWS = ((1, -1000, 1000, 0x13), (2, -500, 500, 0x24), (1, -1000, 3000, 0x62), (2, 0, 0, 0x35),
              (2, 7, 0, 0x71), (2, 0, 0, 0x46), (0, 9, 0, 0xFF), (1, 0, 0, 0x80), (2, 2, 0, 0x08), (2, 0, 0, 0x57))
# Rail row (legacy image) and VFE equations: REL 0, ALT 1, BOOT 2 (fixed point), OV 3, VMIN 4 (clamp
# 692.5 mV) chained to 5 (-112.5..+75 mV).
RAIL_ROW = '00 35 0c 00 00 01 03 00 02 04 ff 00 00 00'
EQUATIONS = {0: (1, 10, 1068750, 1068750, (1068750, 0, 0)), 1: (1, 10, 1093750, 1093750, (1093750, 0, 0)),
             2: (4, 7, 0, 0, (0, 0, 0)), 3: (1, 7, 1125000, 1125000, (1125000, 0, 0)),
             4: (1, 7, 692500, 692500, (0, 0, 0)), 5: (1, 7, -112500, 75000, (0, 1, 0))}


def synthetic_turing(*, device=0x1F06, efi_image=True, notebook=False, header=0x2C, channels=None, tgp_channel=None,
                     limits=(125000, 175000, 200000), copies=2, inputs=False, rails=False, clocks=False, fans=0):
    """NVGI banks holding a generated Turing chain, then a type-0x70 image outside the banks.

    Chain: legacy [+ EFI] + E0 + E0 (not flagged last; its NPDE has a last-image byte) + a
    type-0x70 image flagged last. The second E0 image holds the power table 30/2c/42 (header
    0x27: 30/27/42) with the TGP row 2 (min/rated/max mW in limits) and the 20-entry power
    channel table; the board-total channel (class 2, rail 0xf5) is 9 on the desktop layout
    and 0 on the notebook one (header bytes 10..13 ff ff ff 02).

    inputs adds INPUT_ROWS (16 power rows) on INPUT_CHANNELS; rails adds the 1x rail row (legacy
    image) and the VFE table (second E0 image, EQUATIONS); clocks adds the v0x35 clock table
    (legacy image, CLOCK_ROWS); fans adds the cooler, v0x10 policy and mapping tables (second E0
    image) with 1 or 2 active channels (negative: no GPU-driven fan, as on laptops).
    """
    bank_size, prefix = 16384, 512
    images = [(2048, b'\x55\xaa', 0, device, 0x80 if not efi_image else 0)]
    images += [(512, b'\x55\xaa', 3, device, 0x80)] if efi_image else []
    images += [(512, b'VN', 0xE0, device & 0xFF80, 0), (8192, b'VN', 0xE0, device & 0xFF80, 0), (512, b'VN', 0x70, 0, 0x80)]
    bank = bytearray(b'\xff' * bank_size)
    bank[:4] = b'NVGI'
    regions, at = [], prefix
    for size, signature, code, dev, last in images:
        bank[at:at + size] = bytes(size)
        bank[at:at + 2] = signature
        struct.pack_into('<H', bank, at + 0x18, 0x20)
        h = at + 0x20
        bank[h:h + 4] = b'PCIR' if signature == b'\x55\xaa' else b'NPDS'
        struct.pack_into('<HHHH', bank, h + 4, 0x10DE, dev, 0, 0x18)
        struct.pack_into('<H', bank, h + 0x10, size // 512)
        bank[h + 0x14:h + 0x16] = bytes((code, last))
        if code == 0xE0:
            bank[at + 0x40:at + 0x4C] = b'NPDE' + struct.pack('<HHHBB', 0x101, 0x14, size // 512, 0, 0)
        if code == 0x70:
            bank[at + 0x38:at + 0x3C] = b'ISBN'
        bank[at + size - 16:at + size] = b'\xff' * 16
        regions.append((at, at + size))
        at += size
    legacy = prefix
    bit = legacy + 128
    bank[bit:bit + 6] = b'\xff\xb8BIT\x00'
    bank[bit + 8:bit + 11] = bytes((12, 6, 2))
    bank[bit + 11] = -sum(bank[bit:bit + 12]) & 255
    struct.pack_into('<BBHH', bank, bit + 12, ord('P'), 2, 0xC4, 256)
    struct.pack_into('<BBHH', bank, bit + 18, ord('C'), 2, 0x1C, 600)
    bank[legacy + 700:legacy + 714] = b'90.06.44.00.AE'
    efi = 512 if efi_image else 0
    data = regions[-2][0]
    power, table = data + 0x100, data + 0x600

    def point(token, offset, target):
        # Pointers past the legacy image skip the EFI image.
        struct.pack_into('<I', bank, legacy + (256 if token == 'P' else 600) + offset,
                         target - legacy - (efi if target >= legacy + 2048 else 0))
    point('P', 0x2C, power)
    point('P', 0x3C, table)
    count = 16 if inputs else 3
    bank[power:power + 4] = bytes((0x30, header, 0x42, count))
    bank[power + 10] = 2
    if notebook:
        bank[power + 10:power + 14] = bytes((0xFF, 0xFF, 0xFF, 2))
    row = power + header + 2 * 0x42
    bank[row:row + 2] = bytes((0x21, (0 if notebook else 9) if tgp_channel is None else tgp_channel))
    struct.pack_into('<III', bank, row + 2, *limits)
    for index, (flags, channel, parameter, values) in (INPUT_ROWS.items() if inputs else ()):
        row = power + header + index * 0x42
        bank[row:row + 2], bank[row + 14] = bytes((flags, channel)), parameter
        struct.pack_into('<III', bank, row + 2, *values)
    bank[table:table + 6] = bytes.fromhex('20 06 16 14 00 00')
    for index, entry in (channels or {**(NOTEBOOK_CHANNELS if notebook else DESKTOP_CHANNELS),
                                      **(INPUT_CHANNELS if inputs else {})}).items():
        entry = bytes.fromhex(entry)
        bank[table + 6 + 0x16 * index:table + 6 + 0x16 * index + len(entry)] = entry
    if rails:
        rail, vfe = legacy + 800, data + 0x800
        point('P', 0x68, rail)
        point('P', 0x20, vfe)
        bank[rail:rail + 19] = bytes.fromhex('10 05 0e 01 00 ' + RAIL_ROW)
        bank[vfe:vfe + 6] = bytes.fromhex('30 09 19 14 18 08')
        bank[vfe + 9 + 10 * 25], bank[vfe + 9 + 7 * 25] = 3, 4  # variables 10 (sensed temperature) and 7
        base = vfe + 9 + 20 * 25
        for index in range(8):
            bank[base + 24 * index + 2] = 0xFF  # no next link
        for index, (kind, variable, low, high, coefficients) in EQUATIONS.items():
            eq = base + 24 * index
            bank[eq:eq + 3] = bytes((kind, variable, 5 if index == 4 else 0xFF))
            struct.pack_into('<5f', bank, eq + 3, low, high, *coefficients)
            bank[eq + 23] = 2
    if clocks:
        at = legacy + 900
        point('C', 8, at)
        bank[at:at + 9] = bytes.fromhex('35 09 0b 0a 03 e8 03 00 00')
        for i, (usage, low, high, ordering) in enumerate(CLOCK_ROWS):
            row = at + 9 + 11 * i
            bank[row:row + 3] = bytes((usage, i, i))
            struct.pack_into('<hh', bank, row + 3, low, high)
            bank[row + 7:row + 11] = bytes((ordering, 0, 0xFF, 0xFF))
    if fans:
        turing_fan_tables(bank, data, point, fans)
    for start, end in regions:
        bank[end - 1] = (bank[end - 1] - sum(bank[start:end])) & 255
    tail = bytearray(b'\xff' * 512)
    tail[:2], tail[0x18:0x1A], tail[0x20:0x24] = b'VN', b'\x20\x00', b'NPDS'
    struct.pack_into('<HHHH', tail, 0x24, 0x10DE, 0, 0, 0x18)
    struct.pack_into('<H', tail, 0x30, 1)
    tail[0x34:0x36] = bytes((0x70, 0x80))
    return bytes(bank) * copies + bytes(tail)


def turing_fan_tables(bank, data, point, fans):
    """Cooler (P+0x58), v0x10 policy (P+0x5c) and mapping (P+0x64) tables with two entries each.

    The policy entry holds the Ada curve layout from byte 3 on: the fixed bytes 9..16, levels 20/50/100 %
    at bytes 17..19 and three (1/32 C, RPM) points from byte 21 that reach the row limits (20-100 %,
    1000-3300 RPM).
    """
    cooler, policy, mapping = data + 0xC00, data + 0xC80, data + 0xD00
    for offset, at, header in ((0x58, cooler, (0x10, 6, 0x1A, 2)), (0x5C, policy, (0x10, 6, 0x36, 2)),
                               (0x64, mapping, (0x10, 4, 5, 2))):
        point('P', offset, at)
        bank[at:at + 4] = bytes(header)
    active = max(fans, 0)
    bank[cooler + 4:cooler + 6] = bank[policy + 4:policy + 6] = bytes(i if i < active else 0xFF for i in range(2))
    for i in range(2):
        on = i < active
        row, entry = cooler + 6 + 26 * i, policy + 6 + 54 * i
        bank[row] = 2 if on else 0
        bank[row + 2:row + 6], bank[row + 10] = bytes((20, 100, 0x3D, 0x02 + i)), 9 + i
        struct.pack_into('<I', bank, row + 11, 27000)
        struct.pack_into('<HH', bank, row + 14, 1000, 3300)
        bank[entry:entry + 3] = bytes((int(on), 1, i if on else 0))
        bank[entry + 9:entry + 17] = bytes.fromhex('23 2b 0a 01 00 02 80 00')
        bank[entry + 17:entry + 20] = bytes((20, 50, 100))
        struct.pack_into('<6H', bank, entry + 21, 55 * 32, 1000, 70 * 32, 2000, 85 * 32, 3300)
        bank[mapping + 4 + 5 * i:mapping + 6 + 5 * i] = bytes((int(on), i))


def patch_banks(blob, change):
    """Apply change(bytearray, chain) to every chain of blob, then repair every image checksum."""
    chains = backend(from_bytes(blob)).chains
    patched = bytearray(blob)
    for chain in chains:
        change(patched, chain)
    for image in (image for chain in chains for image in chain):
        patched[image['end'] - 1] = (patched[image['end'] - 1] - sum(patched[image['start']:image['end']])) & 255
    return bytes(patched)


def chain_types(blob):
    """Image types of the first Turing chain of blob (headers only, no checksums)."""
    return [p['type'] for p in image_chains(blob, *scan_images(blob)[:2], family='turing')[0]]


def descriptors(image):
    return {f['key']: f for f in inspect_image(image)['fields']}


def tgp_offsets(blob):
    parser = backend(from_bytes(blob))
    return parser.copy_offsets(parser.power_rows()[parser.tgp_index]['maximum_offset'] - 8, 12)


def messages(image):
    return [d['message'] for d in inspect_image(image)['diagnostics']]


def changed_within(test, image, result, offsets, width=4):
    """Only the declared bytes and the checksum bytes changed, in both banks."""
    allowed = {at + k for at in offsets for k in range(width)}
    allowed |= {r['offset'] for r in result.manifest['integrity_repairs']}
    changed = {i for i, (a, b) in enumerate(zip(image.blob, result.blob)) if a != b}
    test.assertLessEqual(changed, allowed)
    test.assertEqual({at // 16384 for at in changed}, {0, 1})
    test.assertTrue(backend(result.image).integrity()['valid'])


def turing_evidence(field):
    return any(e.get('source', '').startswith('Turing VBIOS corpus') or e.get('format', '').startswith('Turing')
               for e in field['evidence'])


class TuringStructureTests(unittest.TestCase):
    def test_turing_ids_and_bios_family(self):
        arch = architecture(0x1F06, ('90.06.44.00.AE',))
        self.assertEqual((arch['family'], arch['in_scope'], arch['bios_family_consistent']), ('turing', True, True))
        self.assertEqual(arch['evidence'][1]['expected_prefix'], '90.')
        self.assertFalse(architecture(0x1F06, ('94.06.44.00.AE',))['bios_family_consistent'])
        for device in (0x1E02, 0x1E07, 0x1E30, 0x1E84, 0x1E90, 0x1F08, 0x1F82, 0x1F83, 0x2182, 0x2187, 0x21C4):
            self.assertEqual(architecture(device)['family'], 'turing', hex(device))
        # GA100 keeps its own BIOS family; neighbors outside NVIDIA's table stay unknown.
        self.assertEqual(architecture(0x20B0, ('92.00.25.00.08',))['evidence'][1]['expected_prefix'], '92.')
        self.assertEqual(architecture(0x1E00)['family'], 'unknown')

    def test_chain_ends_with_the_type_0x70_image(self):
        for efi in (True, False):
            with self.subTest(efi=efi):
                parser = backend(from_bytes(synthetic_turing(efi_image=efi)))
                self.assertEqual(len(parser.chains), 2)
                types = [p['type'] for p in parser.chains[0]]
                self.assertEqual(types, [0, 3, 0xE0, 0xE0, 0x70] if efi else [0, 0xE0, 0xE0, 0x70])
                self.assertEqual([p['last'] for p in parser.chains[0][-2:]], [False, True])
                self.assertEqual(parser.efi is not None, efi)
                self.assertTrue(parser.integrity()['valid'])

    def test_ampere_and_ada_rules_do_not_take_the_turing_chain(self):
        blob = synthetic_turing()
        pci, extended, _ = scan_images(blob)
        for family in ('ampere', 'ada', None):
            with self.subTest(family=family), self.assertRaisesRegex(FormatError, 'complete last image'):
                image_chains(blob, pci, extended, family=family)
        # A type-0x70 image that is not flagged last does not end a Turing chain either.
        broken = bytearray(blob)
        npds = [p for p in extended if p['type'] == 0x70][0]['npds']
        broken[npds + 0x15] = 0
        with self.assertRaisesRegex(FormatError, 'complete last image'):
            image_chains(bytes(broken), *scan_images(bytes(broken))[:2], family='turing')

    def test_only_an_unflagged_data_image_and_an_nvidia_type_0x70_npds_tail_end_the_chain(self):
        blob = synthetic_turing()
        parser = backend(from_bytes(blob))
        self.assertEqual(chain_types(blob), [0, 3, 0xE0, 0xE0, 0x70])
        tail, last = parser.chains[0][-1], parser.chains[0][-2]
        # The tail carries no device (0000) on the reference images; this chip's ID is accepted too.
        accepted = bytearray(blob)
        struct.pack_into('<H', accepted, tail['npds'] + 6, 0x1F00)
        self.assertEqual(chain_types(bytes(accepted))[-1], 0x70)
        refused = {'another chip': lambda b: struct.pack_into('<H', b, tail['npds'] + 6, 0x2200),
                   'another vendor': lambda b: struct.pack_into('<H', b, tail['npds'] + 4, 0x1234),
                   # A PCIR image (55 aa) of type 0x70 is not the NPDS tail.
                   'PCIR image': lambda b: (b.__setitem__(slice(tail['start'], tail['start'] + 2), b'\x55\xaa'),
                                            b.__setitem__(slice(tail['npds'], tail['npds'] + 4), b'PCIR')),
                   # A loader that reads the NPDE byte would end the chain at this data image.
                   'NPDE last byte': lambda b: b.__setitem__(npde(blob, last) + 0x0A, 0x80)}
        for name, change in refused.items():
            broken = bytearray(blob)
            change(broken)
            with self.subTest(refused=name), self.assertRaisesRegex(FormatError, 'complete last image'):
                chain_types(bytes(broken))
        # A data image flagged last in its NPDS ends the chain there, as on Ampere and Ada.
        flagged = bytearray(blob)
        flagged[last['npds'] + 0x15] = 0x80
        self.assertEqual(chain_types(bytes(flagged)), [0, 3, 0xE0, 0xE0])

    def test_no_table_is_read_from_the_type_0x70_image(self):
        blob = synthetic_turing()
        parser = backend(from_bytes(blob))
        power, size = parser.pointer('P', 0x2C), 0x2C + 3 * 0x42
        def move(b, chain):
            # Copy the power table into the type-0x70 image and point P+0x2c at the copy.
            at = chain[-1]['start'] + 0x40
            b[at:at + size] = blob[chain[0]['start'] + power - parser.legacy['start']:][:size]
            entry = chain[0]['start'] + parser.tokens['P']['data'] - parser.legacy['start'] + 0x2C
            struct.pack_into('<I', b, entry, at - chain[0]['start'] - parser.efi['size'])
        report = inspect_image(from_bytes(patch_banks(blob, move)))
        self.assertFalse([f for f in report['fields'] if f['key'] in POWER])
        self.assertIn('outside or crosses a primary image boundary',
                      ' '.join(d['message'] for d in report['diagnostics']))

    def test_smaller_bit_tokens_have_no_pointers_past_their_end(self):
        parser = backend(from_bytes(synthetic_turing()))
        self.assertEqual(parser.tokens['P']['size'], 0xC4)
        for offset in (0xC4, 0xDC, 0xE0, 0xE8, 0xF4):
            with self.subTest(offset=hex(offset)), self.assertRaisesRegex(FormatError, 'outside BIT token'):
                parser.pointer('P', offset)
        self.assertIsNone(parser.profile_table())
        self.assertEqual(parser.power_profiles(), [])


class TuringPowerTests(unittest.TestCase):
    def test_board_power_fields_are_experimental_with_the_turing_caveats(self):
        image = from_bytes(synthetic_turing())
        report = inspect_image(image)
        fields = {f['key']: f for f in report['fields']}
        self.assertEqual([fields[k]['current'] for k in POWER], [200, 175, 125])
        self.assertEqual(sorted(k for k, f in fields.items() if f['editable']), sorted(POWER))
        # Without the other tables only the placeholders remain.
        self.assertEqual(sorted(fields), sorted(POWER + ['current_limit_a', 'ocp_limit_a', 'memory_offset_max_mhz']))
        for key in POWER:
            field = fields[key]
            self.assertTrue(field['experimental'], key)
            for text in ('decodes like the Ampere one', 'nvidia-smi reported an edited TGP', 'signed hash list',
                         'about 458 W with them raised'):
                self.assertIn(text, field['reason'], key)
            self.assertIn('Turing 30/2c/42', field['evidence'][0]['recognized_variants'])
            self.assertIn('integrity-observation', [e['kind'] for e in field['evidence']])
        # Same bounds as the Ampere fields: ceiling from the rated value, floor from 1 W.
        self.assertEqual((fields['power_max_w']['bounds']['minimum'], fields['power_min_w']['bounds']['minimum']),
                         (175, 1))
        self.assertIsNone(fields['power_max_w']['bounds']['hardware_safe_maximum'])
        self.assertEqual(set(messages(image)), {'requested table is absent'})

    def test_header_variant_and_notebook_layout(self):
        fields = descriptors(from_bytes(synthetic_turing(header=0x27)))
        self.assertEqual([fields[k]['current'] for k in POWER], [200, 175, 125])
        notebook = descriptors(from_bytes(synthetic_turing(notebook=True, efi_image=False, limits=(1000, 80000, 95000))))
        self.assertEqual([notebook[k]['current'] for k in POWER], [95, 80, 1])
        self.assertIn('stored notebook TGP', notebook['power_max_w']['reason'])
        self.assertIn('no Turing laptop reading', notebook['power_default_w']['reason'])

    def test_tgp_row_must_read_the_only_board_total_channel(self):
        refused = (dict(tgp_channel=0),                                               # another class-2 sum
                   dict(channels={**DESKTOP_CHANNELS, 3: '02 f5 00 1b b7 00 00 10'}),        # two board totals
                   dict(channels={0: '02 df 00 1b b7 00 00 10'}))                       # none
        for options in refused:
            with self.subTest(options=options):
                report = inspect_image(from_bytes(synthetic_turing(**options)))
                self.assertFalse([f for f in report['fields'] if f['key'] in POWER])
                self.assertIn('total board power channel', ' '.join(d['message'] for d in report['diagnostics']))
        moved = synthetic_turing(channels={4: '02 f5 00 1b b7 00 00 10'}, tgp_channel=4)
        self.assertEqual(descriptors(from_bytes(moved))['power_max_w']['current'], 200)
        blob = synthetic_turing()
        parser = backend(from_bytes(blob))
        table = parser.pointer('P', 0x3C) - parser.legacy['start']
        count_0x20 = patch_banks(blob, lambda b, chain: b.__setitem__(chain[0]['start'] + table + 3, 0x20))
        messages = [d['message'] for d in inspect_image(from_bytes(count_0x20))['diagnostics']]
        self.assertIn('unvalidated Turing power channel table', messages)

    def test_edit_writes_both_banks_and_their_checksums_and_reverts(self):
        image = from_bytes(synthetic_turing())
        result = edit(image, {'power_max_w': 250, 'power_default_w': 180, 'power_min_w': 100})
        parser = backend(result.image)
        self.assertTrue(parser.integrity()['valid'])
        self.assertEqual([r['default_raw'] for r in parser.power_rows()], [0, 0, 180000])
        changed = [i for i, (a, b) in enumerate(zip(image.blob, result.blob)) if a != b]
        rows, ends = tgp_offsets(image.blob), [c[-2]['end'] - 1 for c in parser.chains]
        self.assertTrue(set(changed) <= {at + k for at in rows for k in range(12)} | set(ends))
        self.assertEqual({at // 16384 for at in changed}, {0, 1})          # both banks
        self.assertEqual(sorted(r['kind'] for r in result.manifest['integrity_repairs']), ['additive_checksum'] * 2)
        back = edit(result.image, {'power_max_w': 200, 'power_default_w': 175, 'power_min_w': 125})
        self.assertEqual(back.blob, image.blob)

    def test_unpadded_power_image_keeps_every_field_read_only(self):
        blob = bytearray(synthetic_turing(copies=1))
        parser = backend(from_bytes(bytes(blob)))
        end = parser.chains[0][-2]['end']
        blob[end - 2] = 0
        blob[end - 1] = (blob[end - 1] + 0xFF) & 255
        report = inspect_image(from_bytes(bytes(blob)))
        self.assertEqual([f['key'] for f in report['fields'] if f['editable']], [])


class TuringInputTests(unittest.TestCase):
    """Slot, connector and NVVDD rows (INPUT_ROWS) on the channels of a two-connector board."""
    def setUp(self):
        self.image = from_bytes(synthetic_turing(inputs=True))
        self.parser = backend(self.image)
        self.rows = self.parser.power_rows()
        self.channels = self.parser.pointer('P', 0x3C) + 6

    def test_rows_by_class_unit_and_channel(self):
        fields = descriptors(self.image)
        expected = {'slot_power_max_w': 74, 'slot_power_rated_w': 63, 'connector_1_power_max_w': 167,
                    'connector_1_power_rated_w': 143, 'connector_2_power_max_w': 167, 'connector_2_power_rated_w': 143,
                    'slot_current_threshold_max_ma': 16500, 'slot_current_threshold_rated_ma': 11000,
                    'connector_1_current_threshold_max_ma': 33750, 'connector_1_current_threshold_rated_ma': 22500,
                    'connector_2_current_threshold_max_ma': 33750, 'connector_2_current_threshold_rated_ma': 22500,
                    'nvvdd_output_ocp_max_ma': 390000, 'nvvdd_output_ocp_rated_ma': 350780}
        self.assertEqual(sorted(k for k, f in fields.items() if f['editable']), sorted(POWER + list(expected)))
        for key, value in expected.items():
            with self.subTest(key=key):
                field = fields[key]
                self.assertEqual(field['current'], value)
                self.assertTrue(field['experimental'] and turing_evidence(field))
                self.assertEqual(field.get('opt_in', False), key in THRESHOLDS)
                # The connector power rows ran on one RTX 2080 Ti with the board power; the others did not.
                tested = key.startswith('connector_') and key.endswith('_w')
                self.assertIn('reached about 458 W' if tested else 'not hardware-tested on Turing', field['reason'])
                self.assertNotRegex(field['reason'], 'reading; not hardware|not hardware-tested; not hardware' +
                                    ('|untested' if tested else ''))
        self.assertEqual([fields[f'connector_{n}_power_max_w']['channel_rail'] for n in (1, 2)], [0xFA, 0xFB])
        self.assertEqual([fields[f'connector_{n}_current_threshold_rated_ma']['threshold_index'] for n in (1, 2)],
                         [1, 2])
        self.assertEqual([fields[f'connector_{n}_current_threshold_rated_ma']['policy_indices'] for n in (1, 2)],
                         [[8], [9]])
        self.assertEqual(fields['nvvdd_output_ocp_rated_ma']['policy_indices'], [13])
        self.assertIn('class 10', fields['nvvdd_output_ocp_rated_ma']['reason'])
        self.assertNotIn('nvvdd_threshold_rows', fields['nvvdd_output_ocp_rated_ma'])
        self.assertNotIn('input_current_max_ma', fields)

    def test_edits_write_both_banks_and_their_checksums_and_revert(self):
        changes = {'slot_power_max_w': 80, 'slot_power_rated_w': 75, 'connector_1_power_max_w': 260,
                   'connector_1_power_rated_w': 250, 'connector_2_power_rated_w': 160,
                   'slot_current_threshold_rated_ma': 12000, 'connector_2_current_threshold_max_ma': 40000,
                   'connector_2_current_threshold_rated_ma': 30000, 'nvvdd_output_ocp_rated_ma': 360000}
        result = edit(self.image, changes)
        rows = {3: (75000, 80000), 4: (250000, 260000), 5: (160000, 167000), 7: (12000, 16500),
                9: (30000, 40000), 13: (360000, 390000)}
        for index, (before, after) in enumerate(zip(self.rows, backend(result.image).power_rows())):
            if index in rows:
                self.assertEqual((after['default_raw'], after['maximum_raw']), rows[index])
                self.assertEqual(after['minimum_raw'], before['minimum_raw'])
            else:
                self.assertEqual(after, before)
        offsets = [at for i in rows for o in (6, 10) for at in self.parser.copy_offsets(self.rows[i]['offset'] + o, 4)]
        changed_within(self, self.image, result, offsets)
        self.assertEqual(len(result.manifest['integrity_repairs']), 2)
        self.assertEqual(result.manifest['preservation']['changed_rated_defaults'],
                         sorted(k for k in changes if 'rated' in k))
        revert = {key: descriptors(self.image)[key]['current'] for key in changes}
        self.assertEqual(edit(result.image, revert).blob, self.image.blob)
        for refused in ({'connector_1_current_threshold_rated_ma': 34000}, {'slot_power_max_w': 60}):
            with self.subTest(refused=refused), self.assertRaises(VbiosError) as exc:
                edit(self.image, refused)
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_a_current_correction_offset_is_accepted_on_turing_only(self):
        # nvgpu curr_corr_offset (channel bytes 10..13), as on the RTX 2070 connector channels.
        blob = patched(self.image.blob, self.channels + 0x16 * 4 + 10, struct.pack('<I', 200))
        fields = descriptors(from_bytes(blob))
        for key in ('connector_1_power_max_w', 'connector_1_current_threshold_rated_ma'):
            self.assertTrue(fields[key]['editable'], key)
        self.assertEqual(fields['connector_1_power_max_w']['policy_indices'], [4])
        from test_rom_formats import synthetic_rom
        ampere = synthetic_rom(family='ampere', copies=2, policies=True)
        table = backend(from_bytes(ampere)).pointer('P', 0x3C)
        refused = descriptors(from_bytes(patched(ampere, table + 6 + 22 * 5 + 10, struct.pack('<I', 200))))
        self.assertEqual(refused['connector_1_power_max_w']['policy_indices'], [7])  # channel 5 refused
        self.assertNotIn('connector_2_power_max_w', refused)

    def test_a_class_1_slot_row_is_the_slot_power_policy(self):
        # The MSI GTX 1650 stores its slot row in the TGP's class (1, mW); another class gives no field.
        row = self.rows[3]['offset']
        fields = descriptors(from_bytes(patched(self.image.blob, row, b'\x01')))
        for key, value in (('slot_power_max_w', 74), ('slot_power_rated_w', 63)):
            with self.subTest(key=key):
                self.assertTrue(fields[key]['editable'])
                self.assertEqual((fields[key]['current'], fields[key]['policy_indices']), (value, [3]))
                self.assertIn('class 1 mW row (the TGP class)', fields[key]['evidence'][0]['format'])
                self.assertIn('a class-1 policy like the TGP', fields[key]['reason'])
        self.assertNotIn('class-1', descriptors(self.image)['slot_power_rated_w']['reason'])
        self.assertNotIn('slot_power_max_w', descriptors(from_bytes(patched(self.image.blob, row, b'\x02'))))
        from test_rom_formats import synthetic_rom
        ampere = synthetic_rom(family='ampere', copies=2, policies=True)
        at = backend(from_bytes(ampere)).ampere_policies('slot_power')[0]['offset']
        self.assertIn('slot_power_max_w', descriptors(from_bytes(ampere)))
        class_1 = patched(ampere, at, bytes([ampere[at] & 0xF0 | 1]))
        self.assertNotIn('slot_power_max_w', descriptors(from_bytes(class_1)))

    def test_a_slot_channel_with_a_provider_byte_or_another_rail_is_refused(self):
        # Provider byte; the laptop slot rail 0xf1; a current correction offset (connector channels only).
        for at, data in ((15, b'\x01'), (1, b'\xf1'), (10, struct.pack('<I', 200))):
            with self.subTest(at=at):
                fields = descriptors(from_bytes(patched(self.image.blob, self.channels + 0x16 * 3 + at, data)))
                self.assertFalse(any(k.startswith('slot_') for k in fields))
                self.assertIn('connector_1_power_max_w', fields)

    def test_a_rail_0xe0_channel_gives_no_input_current_field(self):
        # The Ampere 12 V input rail: on Turing no input current role, and the channel is no connector.
        image = from_bytes(patched(self.image.blob, self.channels + 0x16 * 4 + 1, b'\xe0'))
        fields = descriptors(image)
        self.assertFalse(any(k.startswith('input_current') for k in fields))
        self.assertNotIn('connector_2_power_max_w', fields)
        self.assertEqual(fields['connector_1_power_max_w']['policy_indices'], [5])
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'input_current_rated_ma': 20000})
        self.assertEqual(exc.exception.code, 'UNKNOWN_FIELD')

    def test_a_connector_threshold_needs_threshold_index_1_or_2(self):
        for index in (0, 3):
            with self.subTest(index=index):
                fields = descriptors(from_bytes(patched(self.image.blob, self.rows[8]['offset'] + 14, bytes((index,)))))
                self.assertFalse(any(k.startswith('connector_1_current') for k in fields))
                self.assertTrue(fields['connector_2_current_threshold_rated_ma']['editable'])
                self.assertTrue(fields['connector_1_power_max_w']['editable'])

    def test_class_0_rows_give_no_threshold_or_nvvdd_field(self):
        # The ASUS XOC shape: rows 7, 8, 9 and 13 turned into class 0 mA rows.
        blob = self.image.blob
        for index in (7, 8, 9, 13):
            blob = patched(blob, self.rows[index]['offset'], b'\x10')
        fields = descriptors(from_bytes(blob))
        self.assertFalse(any('_current_threshold_' in k or 'output_ocp' in k for k in fields))
        self.assertTrue(all(fields[k]['editable'] for k in INPUTS))

    def test_a_threshold_without_a_connector_power_row_gives_no_field(self):
        # Row 4 (channel 4) is no longer class 4: connector 1 is channel 5 (row 5) with its threshold row 9.
        fields = descriptors(from_bytes(patched(self.image.blob, self.rows[4]['offset'], b'\x00')))
        self.assertNotIn('connector_2_power_max_w', fields)
        self.assertNotIn('connector_2_current_threshold_max_ma', fields)
        self.assertEqual(fields['connector_1_current_threshold_max_ma']['policy_indices'], [9])
        self.assertEqual(fields['connector_1_current_threshold_max_ma']['threshold_index'], 2)

    def test_a_second_nvvdd_current_row_is_named(self):
        blob = patched(self.image.blob, self.channels + 0x16 * 18,
                       bytes.fromhex('01 01 00 1b b7 00 00 10 00 00 00 00 00 00 05 02'))
        blob = patched(blob, self.rows[12]['offset'], bytes((0x15, 18)) + struct.pack('<III', 1000, 155880, 155880))
        fields = descriptors(from_bytes(blob))
        for key in ('nvvdd_output_ocp_max_ma', 'nvvdd_output_ocp_rated_ma'):
            with self.subTest(key=key):
                self.assertTrue(fields[key]['editable'])
                self.assertIn('row 12 is a class-5 mA threshold on another NVVDD channel (18; 155.88 A rated',
                              fields[key]['reason'])
                self.assertEqual(fields[key]['nvvdd_threshold_rows'],
                                 [{'row': 12, 'power_channel': 18, 'minimum': 1000, 'rated': 155880,
                                   'maximum': 155880, 'units': 'mA'}])
        self.assertFalse(any('threshold' in k and k.startswith('nvvdd') for k in fields))


class TuringVoltageTests(unittest.TestCase):
    """The 1x rail row (legacy image) and the VFE equations (EQUATIONS)."""
    def setUp(self):
        self.image = from_bytes(synthetic_turing(rails=True))
        self.parser = backend(self.image)
        self.row = self.parser.pointer('P', 0x68) + 5

    def test_constant_limits_read_only_and_the_vmin_clamp_editable(self):
        fields = descriptors(self.image)
        for role, value, selector in (('rel', 1068.75, 0), ('alt', 1093.75, 1), ('ov', 1125, 3)):
            with self.subTest(role=role):
                field = fields[f'nvvdd_{role}_equation_max_mv']
                self.assertEqual((field['current'], field['editable'], field['equation_kind']),
                                 (value, False, 'constant'))
                self.assertIn('constant equation', field['reason'])
                self.assertTrue(turing_evidence(field))
                self.assertEqual(fields[f'nvvdd_{role}_selector_index']['current'], selector)
        self.assertNotIn('nvvdd_vmin_equation_max_mv', fields)  # the 1x row has no VMIN slot
        self.assertFalse(fields['nvvdd_rel_max_mv']['editable'])
        self.assertEqual(fields['nvvdd_boot_voltage_uv']['current'], 800000)
        self.assertIsNone(fields['msvdd_rel_max_mv']['current'])
        vmin = fields['nvvdd_vmin_mv']
        self.assertEqual((vmin['current'], vmin['editable'], vmin['experimental']), (692.5, True, True))
        self.assertEqual((vmin['bounds']['minimum'], vmin['bounds']['maximum']), (400, 993.75))  # REL - 75 mV
        self.assertEqual(vmin['selector']['raw'], 4)
        self.assertIn('rail row byte 9', vmin['reason'])
        self.assertIn('not hardware-tested on Turing', vmin['reason'])
        self.assertTrue(vmin['evidence'][0]['format'].startswith('Turing rail row byte 9'))
        self.assertEqual(sorted(k for k, f in fields.items() if f['editable']), sorted(POWER + VOLTAGES))
        self.assertEqual(messages(self.image), ['requested table is absent'])  # the clock table

    def test_vmin_edit_writes_the_clamp_in_both_banks(self):
        result = edit(self.image, {'nvvdd_vmin_mv': 750})
        item = backend(result.image).rail_vmin()[0]
        self.assertEqual((item['value_uv'], item['pinned']), (750000, True))
        source = self.parser.rail_vmin()[0]
        changed_within(self, self.image, result, self.parser.copy_offsets(source['minimum_offset'], 4) +
                       self.parser.copy_offsets(source['maximum_offset'], 4))
        self.assertEqual(edit(result.image, {'nvvdd_vmin_mv': 692.5}).blob, self.image.blob)
        for key, value, code in (('nvvdd_vmin_mv', 994, 'OUT_OF_BOUNDS'),
                                 ('nvvdd_rel_equation_max_mv', 1100, 'FIELD_READ_ONLY')):
            with self.subTest(key=key), self.assertRaises(VbiosError) as exc:
                edit(self.image, {key: value})
            self.assertEqual(exc.exception.code, code)

    def test_fixed_rel_and_alt_write_their_constant_and_clamp_maximum_in_both_banks(self):
        fields = descriptors(self.image)
        for key, value, bounds in (('nvvdd_rel_fixed_mv', 1068.75, (1068.75, 1093.75)),  # clamp minimum .. ALT
                                   ('nvvdd_alt_fixed_mv', 1093.75, (1093.75, 1125))):  # clamp minimum .. OV
            with self.subTest(key=key):
                field = fields[key]
                self.assertEqual((field['current'], field['editable'], field['opt_in'], field['experimental']),
                                 (value, True, True, True))
                self.assertEqual((field['bounds']['minimum'], field['bounds']['maximum']), bounds)
                self.assertEqual((field['value_semantics'], field['ordering_group']),
                                 ('stored-fixed-equation-value', 'nvvdd-rel-alt'))
                self.assertIn('the stored boot voltage and the highest VMIN', field['reason'])
                self.assertIn('not hardware-tested on Turing', field['reason'])
                self.assertTrue(turing_evidence(field))
        self.assertEqual(fields['nvvdd_vmin_mv']['ordering_group'], 'nvvdd-rel-alt')
        rel = self.parser.rail_equations()[0]['equation_offset']
        result = edit(self.image, {'nvvdd_rel_fixed_mv': 1093.75})
        changed_within(self, self.image, result, [o for k in (7, 11) for o in self.parser.copy_offsets(rel + k, 4)])
        # The clamp minimum keeps the stored value, the lowest value offered, so the copy reverts exactly.
        self.assertEqual(struct.unpack_from('<5f', result.blob, rel + 3), (1068750, 1093750, 1093750, 0, 0))
        after = descriptors(result.image)
        rel_field = after['nvvdd_rel_equation_max_mv']
        self.assertEqual((rel_field['current'], rel_field['equation_kind'], after['nvvdd_vmin_mv']['bounds']['maximum']),
                         (1093.75, 'constant', 1018.75))
        self.assertEqual((after['nvvdd_rel_fixed_mv']['current'], after['nvvdd_rel_fixed_mv']['bounds']['minimum']),
                         (1093.75, 1068.75))
        self.assertEqual(edit(result.image, {'nvvdd_rel_fixed_mv': 1068.75}).blob, self.image.blob)
        flat = edit(self.image, {'nvvdd_rel_fixed_mv': 1125, 'nvvdd_alt_fixed_mv': 1125})
        self.assertEqual(edit(flat.image, {'nvvdd_rel_fixed_mv': 1068.75, 'nvvdd_alt_fixed_mv': 1093.75}).blob,
                         self.image.blob)
        # VMIN joins their ordering group: raised past the old REL together, it lifts the REL floor (+75 mV chain).
        higher = edit(self.image, {'nvvdd_vmin_mv': 1000, 'nvvdd_rel_fixed_mv': 1100, 'nvvdd_alt_fixed_mv': 1100})
        self.assertEqual(backend(higher.image).rail_vmin()[0]['value_uv'], 1000000)
        self.assertEqual(descriptors(higher.image)['nvvdd_rel_fixed_mv']['bounds']['minimum'], 1075)

    def test_rel_alt_ov_and_vmin_keep_their_order(self):
        for changes in ({'nvvdd_rel_fixed_mv': 1100},                                     # above ALT
                        {'nvvdd_rel_fixed_mv': 1060},                                     # below its clamp minimum
                        {'nvvdd_alt_fixed_mv': 1050},                                     # below REL
                        {'nvvdd_alt_fixed_mv': 1130},                                     # above OV
                        {'nvvdd_rel_fixed_mv': 790},                                      # below the boot voltage
                        {'nvvdd_rel_fixed_mv': 1130, 'nvvdd_alt_fixed_mv': 1130},
                        {'nvvdd_rel_fixed_mv': 1110, 'nvvdd_alt_fixed_mv': 1100},
                        # VMIN plus its chain (+75 mV) would pass REL: refused on the joint result.
                        {'nvvdd_vmin_mv': 1050, 'nvvdd_rel_fixed_mv': 1100, 'nvvdd_alt_fixed_mv': 1100}):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(self.image, changes)
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        # A raised VMIN lifts the REL floor: REL goes back down only with VMIN, in one edit.
        raised = edit(edit(self.image, {'nvvdd_rel_fixed_mv': 1093.75}).image, {'nvvdd_vmin_mv': 1018.75}).image
        with self.assertRaises(VbiosError) as exc:
            edit(raised, {'nvvdd_rel_fixed_mv': 1068.75})
        self.assertEqual((exc.exception.code, exc.exception.details['field']), ('OUT_OF_BOUNDS', 'nvvdd_rel_fixed_mv'))
        self.assertEqual(edit(raised, {'nvvdd_rel_fixed_mv': 1068.75, 'nvvdd_vmin_mv': 692.5}).blob, self.image.blob)

    def test_fixed_rel_and_alt_stay_at_or_above_the_boot_voltage(self):
        # A stored boot voltage (row bytes 0..3) above REL leaves REL outside its range; ALT keeps its own.
        fields = descriptors(from_bytes(patched(self.image.blob, self.row, struct.pack('<I', 1080000))))
        self.assertFalse(fields['nvvdd_rel_fixed_mv']['editable'])
        self.assertIn('outside 1080 mV up to 1093.75 mV', fields['nvvdd_rel_fixed_mv']['reason'])
        self.assertTrue(fields['nvvdd_alt_fixed_mv']['editable'])

    def test_fixed_rel_and_alt_need_unshared_constants(self):
        rel, alt = (r['equation_offset'] for r in self.parser.rail_equations()[:2])
        sloped = descriptors(from_bytes(patched(self.image.blob, rel + 15, struct.pack('<f', 1))))
        self.assertFalse(sloped['nvvdd_rel_fixed_mv']['editable'])
        self.assertIn('not a constant', sloped['nvvdd_rel_fixed_mv']['reason'])
        self.assertIn('REL equation is not a constant', sloped['nvvdd_alt_fixed_mv']['reason'])
        shared = descriptors(from_bytes(patched(self.image.blob, rel + 6 * 24, bytes((1, 7, 1)))))
        self.assertFalse(shared['nvvdd_alt_fixed_mv']['editable'])  # equation 6 continues into ALT
        self.assertEqual(shared['nvvdd_alt_fixed_mv']['reason'],
                         'read-only: the NVVDD ALT equation is used by another equation')
        self.assertTrue(shared['nvvdd_rel_fixed_mv']['editable'])
        no_alt = descriptors(from_bytes(patched(self.image.blob, self.row + 5, b'\xff')))
        self.assertNotIn('nvvdd_alt_fixed_mv', no_alt)
        self.assertEqual(no_alt['nvvdd_rel_fixed_mv']['bounds']['maximum'], 1125)  # up to OV
        # A custom binding cannot rewrite the REL equation outside the reviewed one.
        from test_extended_fields import custom_registry
        with self.assertRaises(VbiosError) as exc:
            edit(self.image, {'nvvdd_rel_fixed_mv': 1080},
                 field_registry=custom_registry('nvvdd_rel_fixed_mv', self.parser.copy_offsets(rel + 11, 4),
                                                encoding='<f', scale=1000))
        self.assertEqual(exc.exception.code, 'INVALID_FIELD_EVIDENCE')

    def test_a_custom_binding_cannot_rewrite_the_boot_voltage_equation(self):
        # Equation 2, picked by the boot voltage selector (row byte 8), is no role of rail_equations.
        from test_extended_fields import custom_registry
        boot = self.parser.rail_boot_equations()[0]
        self.assertEqual((boot['selector_offset'], boot['selector_raw'], boot['equation_offset']),
                         (self.row + 8, 2, self.parser.rail_equations()[0]['equation_offset'] + 2 * 24))
        for at in (3, 7, 11):
            with self.subTest(byte=at), self.assertRaises(VbiosError) as exc:
                edit(self.image, {'x_mv': 900},
                     field_registry=custom_registry('x_mv', self.parser.copy_offsets(boot['equation_offset'] + at, 4),
                                                    encoding='<f', scale=1000))
            self.assertEqual((exc.exception.code, str(exc.exception)),
                             ('PRESERVED_FIELD_CHANGED', 'the boot voltage equation bytes must be preserved'))

    def test_selector_order_and_layout_gates(self):
        cases = (('VMIN != OV + 1', self.row + 9, b'\x05', 'unvalidated Turing rail selectors'),
                 ('BOOT = VMIN', self.row + 8, b'\x04', 'unvalidated Turing rail selectors'),
                 ('ALT after BOOT', self.row + 5, b'\x02', 'unvalidated Turing rail selectors'),
                 ('margin limit', self.row + 10, b'\x04', 'unvalidated Turing rail selectors'),
                 # Near misses of the REL = ALT = OV layout (rel_and_alt_selecting_ov).
                 ('REL = OV, ALT below OV', self.row + 4, b'\x03\x01', 'unvalidated Turing rail selectors'),
                 ('ALT = OV alone', self.row + 5, b'\x03', 'unvalidated Turing rail selectors'),
                 ('REL = ALT = OV, BOOT != OV - 1', self.row + 4, b'\x03\x03\x03\x00\x01',
                  'unvalidated Turing rail selectors'),
                 ('V20 header', self.row - 5, b'\x20', 'unvalidated Turing rail layout'))
        for name, at, data, message in cases:
            with self.subTest(case=name):
                image = from_bytes(patched(self.image.blob, at, data))
                self.assertFalse(any(k.startswith('nvvdd_') for k in descriptors(image)))
                self.assertIn(message, ' '.join(messages(image)))

    def test_rel_and_alt_selecting_ov(self):
        # The Galax HOF XOC layout: REL and ALT select the OV equation (REL = ALT = OV = 1125 mV).
        image = from_bytes(patched(self.image.blob, self.row + 4, b'\x03\x03'))
        fields = descriptors(image)
        self.assertEqual(messages(image), ['requested table is absent'])  # the clock table only
        for role in ('rel', 'alt', 'ov'):
            with self.subTest(role=role):
                field = fields[f'nvvdd_{role}_equation_max_mv']
                self.assertEqual((field['current'], field['editable']), (1125, False))
                self.assertEqual(fields[f'nvvdd_{role}_selector_index']['current'], 3)
        self.assertFalse(fields['nvvdd_rel_max_mv']['editable'])
        for key, others in (('nvvdd_rel_fixed_mv', 'ALT and OV'), ('nvvdd_alt_fixed_mv', 'REL and OV')):
            with self.subTest(key=key):
                self.assertEqual((fields[key]['current'], fields[key]['editable']), (1125, False))
                self.assertIn(f'is also selected by {others}', fields[key]['reason'])
        vmin = fields['nvvdd_vmin_mv']
        self.assertEqual((vmin['current'], vmin['editable']), (692.5, True))
        self.assertEqual((vmin['bounds']['minimum'], vmin['bounds']['maximum']), (400, 1050))  # REL - 75 mV
        self.assertIsNone(fields['msvdd_rel_max_mv']['current'])
        self.assertNotIn('nvvdd_rel_alt_follow_ov', fields)  # GB20x and Ada only
        self.assertEqual(sorted(k for k, f in fields.items() if f['editable']), sorted(POWER + ['nvvdd_vmin_mv']))
        self.assertEqual(backend(edit(image, {'nvvdd_vmin_mv': 700}).image).rail_vmin()[0]['value_uv'], 700000)
        for key, value, code in (('nvvdd_vmin_mv', 1051, 'OUT_OF_BOUNDS'),
                                 ('nvvdd_rel_fixed_mv', 1100, 'FIELD_READ_ONLY')):
            with self.subTest(key=key), self.assertRaises(VbiosError) as exc:
                edit(image, {key: value})
            self.assertEqual(exc.exception.code, code)
        # Without ALT, REL alone may select OV.
        no_alt = descriptors(from_bytes(patched(self.image.blob, self.row + 4, b'\x03\xff')))
        self.assertEqual(no_alt['nvvdd_rel_equation_max_mv']['current'], 1125)
        self.assertNotIn('nvvdd_alt_fixed_mv', no_alt)
        # A temperature-derated OV equation stays read-only through REL and ALT too: their edit would move OV.
        ov = fields['nvvdd_ov_equation_max_mv']['equation_offset']
        sloped = patched(patched(image.blob, ov + 1, b'\x0a'), ov + 15, struct.pack('<f', -100))
        sloped = descriptors(from_bytes(sloped))
        for key in ('nvvdd_rel_max_mv', 'nvvdd_rel_equation_max_mv', 'nvvdd_alt_equation_max_mv'):
            with self.subTest(key=key):
                self.assertFalse(sloped[key]['editable'])
        self.assertEqual(sloped['nvvdd_rel_equation_max_mv']['equation_kind'], 'shared')

    def test_a_shared_vmin_equation_stays_read_only(self):
        # Equation 6 now continues into the VMIN equation 4.
        vmin = self.parser.rail_vmin()[0]['equation_offset']
        field = descriptors(from_bytes(patched(self.image.blob, vmin + 2 * 24, bytes((1, 7, 4)))))['nvvdd_vmin_mv']
        self.assertFalse(field['editable'])
        self.assertIn('is used by another equation or role', field['reason'])


class TuringClockTests(unittest.TestCase):
    def setUp(self):
        self.image = from_bytes(synthetic_turing(clocks=True))
        self.parser = backend(self.image)
        self.table = self.parser.pointer('C', 8)

    def test_master_rows_only_and_every_chain_written(self):
        rows = self.parser.clock_ranges()
        self.assertEqual([r['domain'] for r in rows], ['GPC', 'XBAR', 'DRAM', 'SYS', 'HUB', 'VID', 'PWR', 'DISP',
                                                       'PCIEGEN', 'HOST'])
        self.assertEqual([r['range_stored'] for r in rows], [u == 1 for u, *_ in CLOCK_ROWS])
        fields = descriptors(self.image)
        self.assertEqual(sorted(k for k, f in fields.items() if f['editable']), sorted(POWER + CLOCKS))
        self.assertFalse(any(k.startswith(('xbar_', 'sys_', 'vid_')) for k in fields))  # slave rows
        self.assertEqual([fields[k]['current'] for k in CLOCKS], [1000, -1000, 6000, -2000, 3000, -1000])
        self.assertTrue(all(turing_evidence(fields[k]) and fields[k]['experimental'] for k in CLOCKS))
        result = edit(self.image, {'gpc_offset_max_mhz': 1500, 'memory_offset_min_mhz': -4000})
        named = {r['domain']: r for r in rows}
        changed_within(self, self.image, result, [at for o in (named['GPC']['maximum_offset'],
                                                               named['DRAM']['minimum_offset'])
                                                  for at in self.parser.copy_offsets(o, 2)], width=2)
        after = {r['domain']: (r['minimum_mhz'], r['maximum_mhz']) for r in backend(result.image).clock_ranges()}
        self.assertEqual((after['GPC'], after['DRAM']), ((-1000, 1500), (-2000, 3000)))
        self.assertEqual(edit(result.image, {'gpc_offset_max_mhz': 1000, 'memory_offset_min_mhz': -2000}).blob,
                         self.image.blob)

    def test_a_disabled_range_stays_read_only_and_no_range_collapses(self):
        fields = descriptors(from_bytes(patched(self.image.blob, self.table + 9 + 3, bytes(4))))  # GPC 0..0
        for key in ('gpc_offset_max_mhz', 'gpc_offset_min_mhz'):
            self.assertFalse(fields[key]['editable'])
            self.assertIn('0..0', fields[key]['reason'])
        self.assertTrue(fields['memory_offset_max_mhz']['editable'])
        with self.assertRaises(VbiosError) as exc:
            edit(self.image, {'memory_offset_min_mhz': 0, 'memory_offset_max_mhz': 0})
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        self.assertIn('a Turing clock offset range must not collapse', str(exc.exception))

    def test_an_unpadded_legacy_image_keeps_the_clocks_read_only_while_power_stays_editable(self):
        image = from_bytes(patched(self.image.blob, self.parser.legacy['end'] - 2, b'\x00'))
        fields = descriptors(image)
        self.assertEqual(sorted(k for k, f in fields.items() if f['editable']), sorted(POWER))
        for key in CLOCKS:
            self.assertIn('legacy image holding the clock table lacks the reviewed checksum padding',
                          fields[key]['reason'])
        self.assertFalse(any('checksum padding' in m for m in messages(image)))
        self.assertEqual(backend(edit(image, {'power_max_w': 250}).image).power_rows()[2]['maximum_raw'], 250000)

    def test_header_usage_and_ordering_gates(self):
        for name, at, data, message in (('header', 8, b'\x01', 'unvalidated clock table variant'),
                                        ('GPC usage', 9, b'\x02', 'does not match the GV HAL GPC row'),
                                        ('DRAM ordering', 9 + 2 * 11 + 7, b'\x63', 'GV HAL DRAM row'),
                                        ('XBAR fixed byte', 9 + 11 + 8, b'\x01', 'GV HAL XBAR row')):
            with self.subTest(gate=name):
                image = from_bytes(patched(self.image.blob, self.table + at, data))
                fields = descriptors(image)
                self.assertFalse(any(k in fields for k in CLOCKS if k != 'memory_offset_max_mhz'))
                self.assertIsNone(fields['memory_offset_max_mhz']['current'])  # the placeholder
                self.assertIn(message, ' '.join(messages(image)))


class TuringFanTests(unittest.TestCase):
    def setUp(self):
        self.image = from_bytes(synthetic_turing(fans=2))
        self.parser = backend(self.image)

    def test_pwm_limits_and_curves_at_the_shifted_policy_entry(self):
        from test_ada_fields import fan_curves, fan_limits
        fields = descriptors(self.image)
        keys = ['fan_pwm_frequency_hz'] + fan_limits(2) + fan_curves(2, 0)
        self.assertEqual(sorted(k for k, f in fields.items() if f['editable']), sorted(POWER + keys))
        self.assertTrue(all(turing_evidence(fields[k]) for k in keys))
        # The GSP-RM fan analysis covers the v0x20 tables only; Turing has no speed table to name.
        self.assertFalse([k for k in keys
                          if any(e['kind'] == 'static-firmware-analysis' for e in fields[k]['evidence'])])
        self.assertNotIn('speed-table value', fields['fan_1_min_rpm']['reason'])
        for key in keys:
            self.assertIn('not hardware-tested on Turing', fields[key]['reason'])
            self.assertNotIn('; not hardware-tested; not hardware-tested', fields[key]['reason'])
        self.assertEqual([fields[k]['current'] for k in ('fan_pwm_frequency_hz', 'fan_1_min_rpm', 'fan_2_max_pct',
                                                         'fan_1_curve_2_temp_c', 'fan_2_curve_3_rpm')],
                         [27000, 1000, 100, 70, 3300])
        channels = fields['fan_channels']
        self.assertEqual((channels['current'], channels['editable']), (2, False))
        self.assertIn('no other channel count is offered', channels['reason'])
        changes = {'fan_1_curve_2_temp_c': 72, 'fan_2_curve_1_rpm': 1200, 'fan_1_curve_3_pct': 95,
                   'fan_pwm_frequency_hz': 25000}
        result = edit(self.image, changes)
        # Policy entries start after a 6-byte header; the Ada curve offsets apply from entry byte 3.
        entry = self.parser.pointer('P', 0x5C) + 6
        written = [(entry + 3 + 18 + 4, 2), (entry + 54 + 3 + 20, 2), (entry + 3 + 16, 1)]
        written += [(r['pwm_frequency_offset'], 2) for r in self.parser.fan_coolers()['rows']]
        changed_within(self, self.image, result,
                       [c for at, size in written for c in self.parser.copy_offsets(at, size)], width=2)
        b = result.blob
        self.assertEqual((struct.unpack_from('<H', b, written[0][0])[0], struct.unpack_from('<H', b, written[1][0])[0],
                          b[written[2][0]]), (72 * 32, 1200, 95))
        self.assertEqual(edit(result.image, {k: fields[k]['current'] for k in changes}).blob, self.image.blob)
        with self.assertRaises(VbiosError) as exc:
            edit(self.image, {'fan_channels': 1})
        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')

    def test_no_zero_rpm_fields_on_turing(self):
        # Turing images store zeros and 0xff where the pair would sit and leave the flag bits clear; a planted pair
        # and flag still give no field (fans stop through the curve there).
        blob = self.image.blob
        for row in self.parser.fan_coolers()['rows']:
            blob = patched(blob, row['policy_offset'] + 30, struct.pack('<HH', 43 * 32, 50 * 32))
            blob = patched(blob, row['policy_offset'] + 46, b'\x00')
            blob = patched(blob, row['policy_offset'] - 2, b'\x07')
        self.assertFalse([k for k in descriptors(from_bytes(blob)) if 'zero_rpm' in k])
        self.assertFalse([k for k in descriptors(self.image) if 'zero_rpm' in k])

    def test_tables_that_disagree_are_refused(self):
        cases = (('policy list', 0x5C, 5, b'\xff', 'policy channel list disagrees with the cooler list'),
                 ('mapping row', 0x64, 4 + 5 + 1, b'\x00', 'not stored in every fan table'),
                 ('mapping enable', 0x64, 4, b'\x00', 'enables disagree across the fan tables'),
                 ('policy channel', 0x5C, 6 + 2, b'\x01', 'not stored in every fan table'),
                 ('policy layout', 0x5C, 6 + 54 + 9, b'\x24', 'unrecognized Turing fan policy entry layout'))
        for name, pointer, at, data, message in cases:
            with self.subTest(case=name):
                image = from_bytes(patched(self.image.blob, self.parser.pointer('P', pointer) + at, data))
                self.assertFalse(any(k.startswith('fan_') for k in descriptors(image)))
                self.assertIn(message, ' '.join(messages(image)))

    def test_laptops_without_a_gpu_driven_fan_have_no_fan_field(self):
        for options in (dict(fans=-1), dict(fans=-1, notebook=True, efi_image=False)):
            with self.subTest(options=options):
                image = from_bytes(synthetic_turing(**options))
                self.assertFalse(any(k.startswith('fan_') for k in descriptors(image)))
                self.assertFalse(any('fan' in m for m in messages(image)))
        one = descriptors(from_bytes(synthetic_turing(fans=1)))
        self.assertIn('fan_1_max_rpm', one)
        self.assertFalse(any(k.startswith('fan_2_') for k in one))


class TuringJointTests(unittest.TestCase):
    def test_joint_edit_of_every_field_writes_every_copy_and_reverts(self):
        image = from_bytes(synthetic_turing(inputs=True, rails=True, clocks=True, fans=2))
        joint_edit(self, image)


def joint_step(field):
    """A different in-bounds value for a joint edit of every canonical field (the Ampere corpus rule)."""
    from test_extended_fields import curve_step
    bounds, current = field['bounds'], Decimal(str(field['current']))
    if field['key'] == 'max_operating_temp_c':
        return current - 1
    if field['key'] in ('factory_gpc_offset_mhz', 'factory_memory_offset_mhz'):
        # A value other than 0 sets the flag and 0 writes flag 0 with 0 kHz: step only an entry that stores an offset
        # (flag 1, not 0 kHz), which going back restores byte for byte.
        return current + 1 if field['stored_flag'] == 1 and current != 0 else current
    if field['value_semantics'] == 'stored-fixed-equation-value':
        return current + 5  # REL and ALT: above their clamp minimum (the stored value), below OV
    if 'fan_policy' in field:
        return curve_step(field)
    if 'fan_channel' in field and bounds['minimum'] == bounds['maximum']:
        return current  # a limit flush with its curve moves only with the curve
    delta = {'W': 1, 'mA': 100, 'Hz': -1000, '%': -1}.get(field['units'], 100)
    delta *= 2 if field['key'].startswith('memory_offset') else 1
    if field['key'].endswith(('_min_w', '_min_mhz', '_min_rpm')):
        delta = -abs(delta)
    value = current + delta
    if bounds['minimum'] is not None and value < Decimal(str(bounds['minimum'])):
        value = current - delta
    if 'rated' in field['key'] and value > Decimal(str(bounds['maximum'])):
        value = current - abs(delta)
    return value


def joint_edit(test, image):
    """Step every editable canonical field at once (as on Ampere), check the bytes, then revert."""
    parser = backend(image)
    bindings = {b.descriptor['key']: b for b in registry.bindings(image, parser)[0]}
    fields = descriptors(image)
    chosen, used, spans = {}, set(), {}
    for key, field in fields.items():
        # The Advanced section (switches and the fields that depend on them) has its own corpus test.
        if not field['editable'] or field.get('section') == 'advanced':
            continue
        binding = bindings[key]
        spans[key] = {at for o in binding.offsets for at in range(o, o + struct.calcsize(binding.encoding))}
        if field.get('alias_of') or spans[key] & used:
            continue
        test.assertEqual(len(binding.offsets) % len(parser.chains), 0, key)
        used |= spans[key]
        chosen[key] = joint_step(field)
    result = plan(image, chosen)
    test.assertTrue(result.manifest['integrity']['valid'])
    repairs = {r['offset'] for r in result.manifest['integrity_repairs']}
    test.assertLessEqual({i for i, (a, b) in enumerate(zip(image.blob, result.blob)) if a != b}, used | repairs)
    after = descriptors(result.image)
    for key, value in chosen.items():
        test.assertEqual(Decimal(str(after[key]['current'])), value, key)
    test.assertEqual(edit(result.image, {k: fields[k]['current'] for k in chosen}).blob, image.blob)
    return chosen


class TuringPayloadTests(unittest.TestCase):
    def test_default_payload_is_the_single_bank_as_it_is(self):
        blob = synthetic_turing()
        payload = normalize(from_bytes(blob))
        self.assertEqual(payload.blob, blob[:16384])
        parser = backend(payload)
        self.assertEqual([p['type'] for p in parser.chains[0]], [0, 3, 0xE0, 0xE0, 0x70])
        self.assertEqual(normalize(payload).blob, payload.blob)

    def test_e0_end_payload_ends_at_the_second_e0_image(self):
        for efi in (True, False):
            with self.subTest(efi=efi):
                bank = normalize(from_bytes(synthetic_turing(efi_image=efi))).blob
                payload = normalize(from_bytes(synthetic_turing(efi_image=efi)), representation=E0_END)
                parser = backend(payload)
                chain = parser.chains[0]
                self.assertEqual([p['type'] for p in chain], [0, 3, 0xE0, 0xE0] if efi else [0, 0xE0, 0xE0])
                self.assertTrue(chain[-1]['last'])
                self.assertEqual(len(payload.blob), chain[-1]['end'])
                self.assertFalse([p for p in scan_images(payload.blob)[1] if p['type'] == 0x70])
                self.assertTrue(parser.integrity()['valid'])
                self.assertEqual(parser.legacy['device'], 0x1F06)
                # The NPDS and NPDE last-image bits; their sum keeps the checksum byte unchanged.
                diff = [i for i in range(len(payload.blob)) if payload.blob[i] != bank[i]]
                last = chain[-1]
                self.assertEqual(diff, [last['npds'] + 0x15, last['start'] + 0x4A])
                self.assertEqual([payload.blob[i] for i in diff], [0x80, 0x80])
                self.assertEqual(descriptors(payload)['power_max_w']['current'], 200)
                for representation in (None, E0_END):
                    self.assertEqual(normalize(payload, representation=representation).blob, payload.blob)

    def test_e0_end_repairs_the_checksum_when_the_flags_do_not_cancel(self):
        from nvidia_vbios.rom import turing
        blob = bytearray(synthetic_turing(copies=1))
        bank = backend(from_bytes(bytes(blob)))
        last = bank.chains[0][-2]
        blob[last['start'] + 0x4A] = 0x80                     # NPDE last-image byte already set
        blob[last['end'] - 1] = (blob[last['end'] - 1] - 0x80) & 255
        # The chain rule refuses such a source (the NPDE ends the chain there); a bank handed over
        # directly still gets a valid checksum.
        with self.assertRaisesRegex(FormatError, 'complete last image'):
            backend(from_bytes(bytes(blob)))
        bank.blob = bytes(blob)
        payload = from_bytes(turing.e0_end(bank))
        self.assertTrue(backend(payload).integrity()['valid'])
        diff = [i for i in range(len(payload.blob)) if payload.blob[i] != blob[i]]
        self.assertEqual(diff, [last['npds'] + 0x15, last['end'] - 1])

    def test_e0_end_refuses_other_families_and_turing_refuses_other_representations(self):
        from test_rom_formats import synthetic_rom
        with self.assertRaises(VbiosError) as exc:
            normalize(from_bytes(synthetic_rom(family='ampere')), representation=E0_END)
        self.assertEqual(exc.exception.code, 'UNREVIEWED_RELOCATION_SOURCE')
        for representation in ('ada-relocated-v1', 'ada-relocated-v2', 'ampere-relocated-v1'):
            with self.subTest(representation=representation), self.assertRaises(VbiosError) as exc:
                normalize(from_bytes(synthetic_turing()), representation=representation)
            self.assertEqual(exc.exception.code, 'UNREVIEWED_RELOCATION_SOURCE')

    def test_e0_end_needs_an_npde_last_image_byte(self):
        blob = bytearray(synthetic_turing(copies=1))
        last = backend(from_bytes(bytes(blob))).chains[0][-2]
        blob[last['start'] + 0x40:last['start'] + 0x44] = b'XXXX'
        blob[last['end'] - 1] = (blob[last['end'] - 1] - sum(b'XXXX') + sum(b'NPDE')) & 255
        with self.assertRaises(VbiosError) as exc:
            normalize(from_bytes(bytes(blob)), representation=E0_END)
        self.assertEqual(exc.exception.code, 'RELOCATION_VERIFICATION_FAILED')

    def test_e0_end_refuses_an_unpadded_image_or_an_npde_without_a_reviewed_last_image_byte(self):
        blob = synthetic_turing()
        cases = {'no checksum padding': lambda b, chain: b.__setitem__(chain[-2]['end'] - 2, 0),
                 'NPDE version 0x200': lambda b, chain: struct.pack_into('<H', b, chain[-2]['start'] + 0x44, 0x200),
                 'NPDE header 0x0a': lambda b, chain: struct.pack_into('<H', b, chain[-2]['start'] + 0x46, 0x0A)}
        for name, change in cases.items():
            source = from_bytes(patch_banks(blob, change))
            self.assertTrue(backend(source).integrity()['valid'])
            with self.subTest(case=name), self.assertRaises(VbiosError) as exc:
                normalize(source, representation=E0_END)
            self.assertEqual(exc.exception.code, 'RELOCATION_VERIFICATION_FAILED')

    def test_e0_end_checks_the_source_chain_and_the_re_parsed_payload(self):
        from nvidia_vbios.rom import turing
        bank = backend(normalize(from_bytes(synthetic_turing())))
        changes = {'PCI identity': lambda p: setattr(p, 'legacy', dict(p.legacy, device=0x1F07)),
                   'chain shape': lambda p: p.chains[0].__setitem__(1, dict(p.chains[0][1], type=4)),
                   'last image': lambda p: p.chains[0].__setitem__(-1, dict(p.chains[0][-1], last=False)),
                   'integrity': lambda p: setattr(p, 'integrity', lambda: {'valid': False})}
        for name, change in changes.items():
            class Reparsed(turing.TableRom):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    change(self)
            with self.subTest(changed=name), mock.patch.object(turing, 'TableRom', Reparsed), \
                    self.assertRaises(VbiosError) as exc:
                turing.e0_end(bank)
            self.assertEqual(exc.exception.code, 'RELOCATION_VERIFICATION_FAILED')
        # The tail must be the type-0x70 image.
        bank.chains[0][-1] = dict(bank.chains[0][-1], type=0x71)
        with self.assertRaises(VbiosError) as exc:
            turing.e0_end(bank)
        self.assertEqual(exc.exception.code, 'RELOCATION_VERIFICATION_FAILED')

    def test_cli_normalize_writes_the_e0_end_payload_and_its_manifest(self):
        from nvidia_vbios import cli
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / 'edited.rom', Path(tmp) / 'payload.bin'
            source.write_bytes(synthetic_turing())
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(['normalize', str(source), str(output), '--representation', E0_END])
            self.assertEqual(code, 0)
            manifest = json.loads(output.with_name('payload.bin.json').read_text())
            self.assertEqual(output.read_bytes(), normalize(from_bytes(synthetic_turing()), representation=E0_END).blob)
        self.assertEqual(manifest['representation'], E0_END)
        self.assertIn('type-0x70 image', manifest['note'])

    def test_manifest_note(self):
        source = from_bytes(synthetic_turing())
        payload = normalize(source, representation=E0_END)
        note = normalize_manifest(source, payload, E0_END, 'source.rom')['note']
        self.assertIn('Experimental, not hardware validated', note)
        self.assertIn('type-0x70 image', note)

    def test_editor_window_saves_both_payloads_next_to_a_turing_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source.rom'
            source.write_bytes(synthetic_turing())
            output = Path(tmp) / 'copy.rom'
            saved = save_document(stage_document(open_document(source), {'power_max_w': 220}), output).last_saved
            self.assertEqual([(l['output'], l['representation']) for l in saved['loaders']],
                             [(str(Path(tmp) / 'copy-loader.bin'), None),
                              (str(Path(tmp) / 'copy-loader-e0end.bin'), E0_END)])
            self.assertEqual(saved['loader'], saved['loaders'][0])
            copy = load(output)
            for loader in saved['loaders']:
                manifest = json.loads(Path(loader['manifest']).read_text())
                self.assertEqual((manifest['representation'], manifest['source_sha256']),
                                 (loader['representation'], copy.sha256))
                payload = Path(loader['output']).read_bytes()
                self.assertEqual(payload, normalize(copy, representation=loader['representation']).blob)
                self.assertEqual(descriptors(from_bytes(payload))['power_max_w']['current'], 220)
            # Either payload left by an earlier copy refuses the whole save.
            for name in ('again-loader.bin', 'again-loader-e0end.bin.json'):
                with self.subTest(existing=name):
                    (Path(tmp) / name).write_bytes(b'older')
                    with self.assertRaises(VbiosError) as exc:
                        save_document(stage_document(open_document(source), {'power_max_w': 230}),
                                      Path(tmp) / 'again.rom')
                    self.assertEqual(exc.exception.code, 'LOADER_OUTPUT_EXISTS')
                    self.assertFalse((Path(tmp) / 'again.rom').exists())
                    (Path(tmp) / name).unlink()

    def test_a_payload_the_loaders_would_refuse_is_not_saved(self):
        # A full-size file whose second bank is erased: plain normalize keeps the flash bytes after
        # the chain and sends more than 512 KiB, the e0-end payload ends at the last data image.
        single = synthetic_turing(copies=1)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source.rom'
            source.write_bytes(single[:16384] + b'\xff' * 0x80000 + single[16384:])
            saved = save_document(stage_document(open_document(source), {'power_max_w': 220}),
                                  Path(tmp) / 'copy.rom').last_saved
            default, e0_end = saved['loaders']
            self.assertIn('accepts at most 524288', default['error'])
            self.assertFalse((Path(tmp) / 'copy-loader.bin').exists())
            self.assertEqual(e0_end['output'], str(Path(tmp) / 'copy-loader-e0end.bin'))
            self.assertEqual(loader_messages(saved), [('saved_loader', dict(output=e0_end['output'])),
                                                      ('saved_loader_other_failed', dict(reason=default['error']))])

    def test_status_lines_name_the_file_to_load_first(self):
        first, second = dict(output='copy-loader.bin'), dict(output='copy-loader-e0end.bin')
        refused = dict(error='refused')
        cases = (([first, second], [('saved_loader', dict(output='copy-loader.bin')),
                                    ('saved_loader_alternative', dict(output='copy-loader-e0end.bin'))]),
                 ([first, refused], [('saved_loader', dict(output='copy-loader.bin')),
                                     ('saved_loader_other_failed', dict(reason='refused'))]),
                 ([refused, refused], [('saved_loader_failed', dict(reason='refused'))] * 2),
                 ([], []))
        for loaders, lines in cases:
            with self.subTest(loaders=loaders):
                self.assertEqual(loader_messages(dict(loader=loaders[0] if loaders else None, loaders=loaders)), lines)
        # One payload (Ampere, Ada): as before.
        self.assertEqual(loader_messages(dict(loader=first)), [('saved_loader', dict(output='copy-loader.bin'))])
        self.assertEqual(loader_messages(dict(loader=refused)), [('saved_loader_failed', dict(reason='refused'))])


if __name__ == '__main__':
    unittest.main()
