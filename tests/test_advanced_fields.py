"""Advanced section (PERF_CF controllers, LPWR idle power) on GB20x, Ada, Ampere and Turing: synthetic images and
opt-in reference ROMs."""
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nvidia_vbios import cli
from nvidia_vbios.editor import IMPORT_SECTIONS, edit, import_fields
from nvidia_vbios.editor.registry import (LPWR_ENABLED_ENTRIES, LPWR_ENABLED_UNRECOGNIZED_REASON,
                                          LPWR_GR_RG_ENABLED_UNRECOGNIZED_REASON, LPWR_GR_RG_UNRECOGNIZED_REASON,
                                          LPWR_MIXED_REASON, LPWR_STOCK, LPWR_STOCK_UNRECOGNIZED_REASON,
                                          LPWR_TABLE_UNREVIEWED_REASON, LPWR_TIME_SWITCH_REASON,
                                          PERF_CF_CONTROLLER_UNRECOGNIZED_REASON, PERF_CF_POLICY_UNRECOGNIZED_REASON,
                                          lpwr_covered, percent_fxp, registry)
from nvidia_vbios.gui.presentation import lpwr_notes
from nvidia_vbios.gui.i18n import MESSAGES_EN
from nvidia_vbios.gui.messages_es import MESSAGES_ES
from nvidia_vbios.gui.presentation import (SECTION_NAMES, dependency_reason, field_label, field_section,
                                           read_only_reason, section_order, unsupported_notes, value_text)
from nvidia_vbios.rom import from_bytes, inspect_image, load, VbiosError
from nvidia_vbios.rom.image import backend
from test_extended_fields import changed_bytes_within, custom_registry, descriptors, repair_fixture, set_device
from test_rom_formats import synthetic_blackwell, synthetic_rom
from test_thermal_factory_fields import probe
from test_turing import synthetic_turing

DOMAINS = ('gpc', 'dram', 'vid')
CONTROLLER_KINDS = ('target_pct', 'jump_pct', 'hysteresis_down', 'hysteresis_up')
PERF_CF_KEYS = ('perf_cf_util_policy',) + tuple(f'perf_cf_{d}_{k}' for d in DOMAINS for k in CONTROLLER_KINDS)
LPWR_SWITCHES = {'lpwr_gr_power_gating': 'gr_pg', 'lpwr_mscg': 'ms', 'lpwr_nvdec_gating': 'nvdec',
                 'lpwr_nvenc_gating': 'nvenc', 'lpwr_ofa_gating': 'ofa', 'lpwr_nvjpg_gating': 'nvjpg',
                 'lpwr_difr': 'difr', 'lpwr_gr_rail_gating': 'gr_rg'}
DIFR_TIMES = ('lpwr_difr_dfpr_idle_ms', 'lpwr_difr_sw_asr_idle_us', 'lpwr_difr_cg_idle_us')
# Object of each Advanced field's table.
PERF_CF_OBJECTS = {'perf_cf_util_policy': 0x61}
LPWR_OBJECTS = {'gr_pg': 0x39, 'ms': 0x3A, 'gr_rg': 0x7E, 'difr': 0x8E, 'nvdec': 0xB4, 'nvenc': 0xB5, 'ofa': 0xB6,
                'nvjpg': 0xB7}


def fixture(*, perf_cf=True, lpwr=True, device=None, mutate=None):
    """A synthetic GB20x image with the Advanced tables; mutate(blob, parser) reshapes them before the rehash."""
    blob = bytearray(synthetic_blackwell(perf_cf=perf_cf, lpwr=lpwr))
    if device is not None:
        set_device(blob, device)
    if mutate is not None:
        mutate(blob, backend(from_bytes(bytes(blob))))
    return from_bytes(repair_fixture(blob))


def controller(parser, index):
    return parser.perf_cf()['controllers']['entries'][index]


def policy(parser, index=0):
    return parser.perf_cf()['policies']['entries'][index]


def lpwr_entry(parser, name, index):
    return parser.lpwr_table(name)['entries'][index]


def bindings(image):
    return {b.descriptor['key']: b for b in registry.bindings(image, backend(image))[0]}


def object_of(key, field):
    """The object a field of the Advanced section writes."""
    if key in PERF_CF_OBJECTS:
        return PERF_CF_OBJECTS[key]
    if key.startswith('perf_cf_'):
        return 0x60
    return LPWR_OBJECTS[field['lpwr_table']]


def changed(before, after):
    return {i for i, (a, b) in enumerate(zip(before.blob, after.blob)) if a != b}


def set_gr_rail_gating(*values):
    def mutate(blob, parser):
        for i, value in enumerate(values):
            blob[lpwr_entry(parser, 'gr_rg', i)['offset']] = value
    return mutate


# Generated Turing, Ampere and Ada images with the PERF_CF and LPWR tables in the shapes of the reviewed images:
# each table sits in the data image at its offset from the legacy image start and the BIT P token of every chain
# points to it (the Turing token ends before the GR rail gating and DIFR pointers, the Ampere one before DIFR).
LEGACY_DEVICES = {'turing': 0x1F06, 'ampere': 0x2204, 'ada': 0x28B0}
LEGACY_TABLE_AT = {0xA8: 9000, 0xAC: 9600, 0x80: 9700, 0x84: 9750, 0xD4: 9850, 0xE8: 9880}
LEGACY_ENTRY_SIZES = {'turing': 24, 'ampere': 32, 'ada': 49}
# Controllers 0..2 as (type, clock table row, target, jump threshold, decrease hysteresis): the GPC, DRAM and VID
# controllers of an RTX 2080 Ti (40/55, 40/55 and 60/80 %, truncated fractions) and of an RTX 3090 or an RTX 2000
# Ada (40/75, 65/80 and 65/85 %); then a second GPC and DRAM pair, a type 3 controller and empty entries.
LEGACY_CONTROLLERS = {'turing': ((1, 0, 0x666, 0x8CC, 9), (1, 2, 0x666, 0x8CC, 4), (1, 5, 0x999, 0xCCC, 9)),
                      'ampere': ((1, 0, 0x666, 0xC00, 9), (1, 2, 0xA66, 0xCCC, 4), (1, 5, 0xA66, 0xD9A, 9))}
LEGACY_CONTROLLERS['ada'] = LEGACY_CONTROLLERS['ampere']
LEGACY_POLICIES = bytes.fromhex('10 05 0a 08 00' '81 00 00000000 07000000' '01 01 01000000 18000000'
                                '81 02 00000000 20000000') + bytes.fromhex('01 00 00000000 00000000') * 5
# LPWR tables per family: BIT P offset -> (header, entries), as stored on an RTX 2060 SUPER, an RTX 3090 and an RTX
# 2000 Ada.
GR_PG_HEADER, LEGACY_MS_OFF = '10 0a 05 05 00 58 1b 01 00 01', '00fcffffffffffff00ffffffffffff'
LEGACY_LPWR = {
    'turing': {0x80: (GR_PG_HEADER, ['efffffff01', 'e7ffffff01', 'e6ffffff01', 'e6ffffff01', 'e5ffffff01']),
               0x84: ('10 07 0f 05 00 0a 00', ['fdffffff7f0affff026400b400e600', 'edffffff7f0affff026400b400e600',
                                               'ecffffffffffffff006400b400e600', 'ecffffffffffffff006400b400e600',
                                               'ccffffffffffffff006400b400e600'])},
    'ampere': {0x80: (GR_PG_HEADER, ['e7ffffff00', 'e7ffffff00', 'c0ffffff00', 'e7ffffff00', 'c0ffffff00']),
               0x84: ('10 07 0f 05 00 0f 00', ['fdffffff7f0affff0364005e015e01', '2dffffff7f0affff0064005e015e01']
                      + [LEGACY_MS_OFF] * 3),
               0xD4: ('10 09 01 05 00 f4 01 dc 05', ['ff', 'ff', 'fe', 'fe', 'fe'])},
    'ada': {0x80: (GR_PG_HEADER, ['a7ffffff00', 'a7ffffff00', 'a7ffffff00', '80ffffff00', '80ffffff00']),
            0x84: ('10 07 0f 05 00 0f 00', ['fdffffff7f0affff0264005e019001', '2dffffff7f0affff0064005e015e01']
                   + [LEGACY_MS_OFF] * 3),
            0xD4: ('10 09 01 05 ff f4 01 88 13', ['fe'] * 5),
            0xE8: ('10 0b 11 05 ff e8 03 0f 00 0f 00', ['ffffffff026400fa002c01640096009600'] +
                   ['00feffff00ffffffffffffffffffffffff'] * 4)},
}
LPWR_POINTERS = {'gr_pg': 0x80, 'ms': 0x84, 'gr_rg': 0xD4, 'difr': 0xE8}


def legacy_controllers(family, entry_size, count=8):
    rows = LEGACY_CONTROLLERS[family] + ((1, 0, 0x999, 0xCCC, 9), (1, 2, 0xB33, 0xE66, 4))
    table = bytearray((0x10, 6, entry_size, count, 0xC8, 0))
    for i in range(count):
        entry = bytearray(entry_size)
        if i < len(rows):
            kind, row, target, jump, down = rows[i]
            entry[:3] = bytes((kind, 1, i))
            struct.pack_into('<IIII', entry, 3, target, jump, 0x1000, 0xCCC)
            entry[19:23] = bytes((row, 1, down, 9))
        elif i == len(rows):
            entry[:3] = bytes((3, 1, 0xFF))
        table += entry
    return bytes(table)


def legacy_advanced(family, *, device=None, entry_size=None, lpwr=None, mutate=None):
    """A generated Turing, Ampere or Ada image (two chains) with the PERF_CF tables (legacy_controllers, policy 0
    active over controllers 0..2) and the LPWR tables of LEGACY_LPWR, whose entries lpwr may replace ({BIT P offset:
    [hex entry, ...]}); mutate(blob, parser) reshapes them in every chain before the checksums are repaired."""
    device = device or LEGACY_DEVICES[family]
    blob = (synthetic_turing(clocks=True, device=device) if family == 'turing' else
            synthetic_rom(family=family, copies=2, device=device))
    parser = backend(from_bytes(blob))
    out = bytearray(blob)
    if family == 'ada':
        # The generated Ada image always carries the RTX 2000 Ada identity: rewrite its PCI device.
        for image in (image for chain in parser.chains for image in chain if image['type'] in (0, 3)):
            struct.pack_into('<H', out, image['pcir'] + 6, device)
    tables = {0xA8: legacy_controllers(family, entry_size or LEGACY_ENTRY_SIZES[family]), 0xAC: LEGACY_POLICIES}
    for pointer, (header, entries) in LEGACY_LPWR[family].items():
        tables[pointer] = bytes.fromhex(header) + b''.join(bytes.fromhex(e) for e in (lpwr or {}).get(pointer, entries))
    legacy, efi = parser.legacy, parser.efi
    token = parser.tokens['P']['data'] - legacy['start']
    for pointer, data in tables.items():
        if pointer + 4 > parser.tokens['P']['size']:
            continue  # past this family's BIT P token
        relative = LEGACY_TABLE_AT[pointer]
        value = relative - (efi['size'] if efi is not None and relative >= legacy['size'] else 0)
        for chain in parser.chains:
            start = chain[0]['start'] + relative
            if any(out[start:start + len(data)]):
                raise AssertionError('the generated image has no room for this table')
            out[start:start + len(data)] = data
            struct.pack_into('<I', out, chain[0]['start'] + token + pointer, value)
    if mutate is not None:
        mutate(out, backend(from_bytes(bytes(out))))
    for image in (image for chain in parser.chains for image in chain):
        out[image['end'] - 1] = (out[image['end'] - 1] - sum(out[image['start']:image['end']])) & 255
    return from_bytes(bytes(out))


def in_every_chain(parser, at, value, width=1):
    """mutate helper: store value (bytes) at at in every chain."""
    def write(blob, _):
        for start in parser.copy_offsets(at, width):
            blob[start:start + len(value)] = value
    return write


class PerfCfTests(unittest.TestCase):
    def test_absent_tables_add_no_field_and_no_diagnostic(self):
        report = inspect_image(from_bytes(synthetic_blackwell()))
        self.assertFalse([f for f in report['fields'] if f.get('section') == 'advanced'])
        self.assertFalse([d for d in report['diagnostics']
                          if d.get('resolver') in ('perf_cf_controllers', 'lpwr_features')])

    def test_descriptors_section_dependency_and_bounds(self):
        for header in (6, 14):
            with self.subTest(header=header):
                fields = descriptors(fixture(perf_cf=header))
                switch = fields['perf_cf_util_policy']
                self.assertEqual((switch['current'], switch['units'], switch['editable'], switch['section']),
                                 (1, 'flag', True, 'advanced'))
                self.assertNotIn('depends_on', switch)
                expected = {'gpc': (40, 75, 9, (10, 74), (41, 100), (5, 36)),
                            'dram': (52, 64, 4, (10, 63), (53, 100), (2, 16)),
                            'vid': (65, 85, 9, (10, 84), (66, 100), (5, 36))}
                for domain, (target, jump, down, target_range, jump_range, down_range) in expected.items():
                    rows = {kind: fields[f'perf_cf_{domain}_{kind}'] for kind in CONTROLLER_KINDS}
                    self.assertEqual([rows[k]['current'] for k in CONTROLLER_KINDS], [target, jump, down, 1])
                    for kind, bounds in zip(CONTROLLER_KINDS, (target_range, jump_range, down_range, (1, 4))):
                        self.assertEqual((rows[kind]['bounds']['minimum'], rows[kind]['bounds']['maximum']), bounds)
                    for row in rows.values():
                        self.assertEqual((row['section'], row['editable'], row['experimental']),
                                         ('advanced', True, True))
                        self.assertEqual(row['depends_on'], {'field': 'perf_cf_util_policy', 'value': 1})
                        self.assertNotIn('opt_in', row)
                        self.assertEqual(field_section(row), 'advanced')
                    self.assertEqual(rows['target_pct']['ordering_group'], f'perf-cf-{domain}')
                    self.assertEqual(rows['target_pct']['units'], '%')
                    self.assertEqual(rows['hysteresis_down']['units'], 'samples')
                self.assertEqual(fields['perf_cf_dram_target_pct']['stored_raw'], 0x851)

    def test_switch_off_and_back_is_byte_identical(self):
        for header in (6, 14):
            with self.subTest(header=header):
                image = fixture(perf_cf=header)
                at = policy(backend(image))['offset']
                result = edit(image, {'perf_cf_util_policy': 0})
                self.assertTrue(result.manifest['integrity']['valid'])
                self.assertEqual(result.blob[at], 0x01)
                changed_bytes_within(self, image, result, [at], width=1)
                self.assertEqual(result.manifest['changed_object_ids'], [0x61])
                after = descriptors(result.image)
                self.assertEqual(after['perf_cf_util_policy']['current'], 0)
                # The controller fields stay listed and editable, still depending on the switch.
                self.assertTrue(after['perf_cf_gpc_target_pct']['editable'])
                self.assertEqual(edit(result.image, {'perf_cf_util_policy': 1}).blob, image.blob)

    def test_controller_fields_change_only_while_the_switch_is_on(self):
        image = fixture()
        off = edit(image, {'perf_cf_util_policy': 0}).image
        for key, value in (('perf_cf_gpc_target_pct', 50), ('perf_cf_dram_jump_pct', 70),
                           ('perf_cf_vid_hysteresis_down', 12), ('perf_cf_gpc_hysteresis_up', 2)):
            with self.subTest(key=key):
                with self.assertRaises(VbiosError) as exc:
                    edit(off, {key: value})
                self.assertEqual(exc.exception.code, 'DEPENDENT_FIELD_DISABLED')
                self.assertEqual(exc.exception.details['field'], key)
                self.assertEqual(exc.exception.details['depends_on'], {'field': 'perf_cf_util_policy', 'value': 1})
                # Turned off in the same edit: refused too.
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {'perf_cf_util_policy': 0, key: value})
                self.assertEqual(exc.exception.code, 'DEPENDENT_FIELD_DISABLED')
                # Turned on in the same edit: accepted.
                result = edit(off, {'perf_cf_util_policy': 1, key: value})
                self.assertEqual(descriptors(result.image)[key]['current'], value)
        # The stored value may be requested again while the switch is off: nothing changes.
        self.assertEqual(edit(off, {'perf_cf_gpc_target_pct': 40}).manifest['changed_bytes'], 0)

    def test_target_and_jump_are_whole_percent_fractions(self):
        image = fixture()
        parser = backend(image)
        gpc, dram = controller(parser, 0), controller(parser, 1)
        result = edit(image, {'perf_cf_gpc_target_pct': 50})
        self.assertEqual(struct.unpack_from('<I', result.blob, gpc['target_offset'])[0], 0x800)
        changed_bytes_within(self, image, result, [gpc['target_offset']], width=4)
        self.assertEqual(result.manifest['changed_object_ids'], [0x60])
        self.assertEqual(edit(result.image, {'perf_cf_gpc_target_pct': 40}).blob, image.blob)
        # The stock DRAM target 0x851 (51.98 %) is not the fraction nearest to 52 %: going back to
        # 52 % stores the stock fraction, so the bytes are the stock ones.
        lowered = edit(image, {'perf_cf_dram_target_pct': 30})
        self.assertEqual(struct.unpack_from('<I', lowered.blob, dram['target_offset'])[0], 1229)
        self.assertEqual(edit(lowered.image, {'perf_cf_dram_target_pct': 52}).blob, image.blob)
        # A changed jump threshold leaves the target fraction as stored.
        result = edit(image, {'perf_cf_dram_jump_pct': 90, 'perf_cf_dram_target_pct': 52})
        self.assertEqual(struct.unpack_from('<II', result.blob, dram['target_offset']), (0x851, 3686))
        self.assertEqual(descriptors(result.image)['perf_cf_dram_jump_pct']['current'], 90)
        self.assertEqual(edit(image, {'perf_cf_gpc_jump_pct': 100}).blob[gpc['jump_offset']:gpc['jump_offset'] + 4],
                         struct.pack('<I', 0x1000))
        for key, value, code in (('perf_cf_gpc_target_pct', 9, 'OUT_OF_BOUNDS'),
                                 ('perf_cf_gpc_target_pct', 75, 'OUT_OF_BOUNDS'),
                                 ('perf_cf_gpc_target_pct', Decimal('40.5'), 'UNREPRESENTABLE_VALUE'),
                                 ('perf_cf_gpc_jump_pct', 101, 'OUT_OF_BOUNDS'),
                                 ('perf_cf_gpc_jump_pct', 40, 'OUT_OF_BOUNDS')):
            with self.subTest(key=key, value=value):
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {key: value})
                self.assertEqual(exc.exception.code, code)

    def test_target_and_jump_cross_the_stored_values_together(self):
        image = fixture()
        result = edit(image, {'perf_cf_gpc_target_pct': 90, 'perf_cf_gpc_jump_pct': 95})
        fields = descriptors(result.image)
        self.assertEqual((fields['perf_cf_gpc_target_pct']['current'], fields['perf_cf_gpc_jump_pct']['current']),
                         (90, 95))
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'perf_cf_gpc_target_pct': 90, 'perf_cf_gpc_jump_pct': 80})
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        self.assertIn(exc.exception.details['field'], ('perf_cf_gpc_target_pct', 'perf_cf_gpc_jump_pct'))
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'perf_cf_gpc_target_pct': 80, 'perf_cf_gpc_jump_pct': 80})
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_hysteresis_ranges(self):
        image = fixture()
        parser = backend(image)
        result = edit(image, {'perf_cf_gpc_hysteresis_down': 36, 'perf_cf_dram_hysteresis_down': 2,
                              'perf_cf_vid_hysteresis_up': 4})
        self.assertEqual(result.blob[controller(parser, 0)['hysteresis_down_offset']], 36)
        self.assertEqual(result.blob[controller(parser, 1)['hysteresis_down_offset']], 2)
        self.assertEqual(result.blob[controller(parser, 2)['hysteresis_up_offset']], 4)
        self.assertEqual(result.manifest['changed_object_ids'], [0x60])
        for key, value in (('perf_cf_gpc_hysteresis_down', 37), ('perf_cf_gpc_hysteresis_down', 4),
                           ('perf_cf_dram_hysteresis_down', 1), ('perf_cf_dram_hysteresis_down', 17),
                           ('perf_cf_gpc_hysteresis_up', 0), ('perf_cf_gpc_hysteresis_up', 5)):
            with self.subTest(key=key, value=value):
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {key: value})
                self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_unrecognized_policy_or_controller_is_read_only(self):
        def policy_kind(blob, parser):
            blob[policy(parser)['offset']] = 0x82
        image = fixture(mutate=policy_kind)
        fields = descriptors(image)
        for key in PERF_CF_KEYS:
            with self.subTest(key=key):
                self.assertEqual((fields[key]['editable'], fields[key]['reason']),
                                 (False, PERF_CF_POLICY_UNRECOGNIZED_REASON))
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'perf_cf_util_policy': 0})
        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')

        def dram_domain(blob, parser):
            blob[controller(parser, 1)['offset'] + 19] = 3
        fields = descriptors(fixture(mutate=dram_domain))
        for kind in CONTROLLER_KINDS:
            self.assertEqual((fields[f'perf_cf_dram_{kind}']['editable'], fields[f'perf_cf_dram_{kind}']['reason']),
                             (False, PERF_CF_CONTROLLER_UNRECOGNIZED_REASON))
            self.assertTrue(fields[f'perf_cf_gpc_{kind}']['editable'])
        self.assertTrue(fields['perf_cf_util_policy']['editable'])

        def same_percent(blob, parser):
            struct.pack_into('<I', blob, controller(parser, 2)['target_offset'], 3480)
        self.assertFalse(descriptors(fixture(mutate=same_percent))['perf_cf_vid_target_pct']['editable'])

    def test_notebook_type_5_controller_is_recognized(self):
        def type5(blob, parser):
            blob[controller(parser, 0)['offset']] = 5
        image = fixture(mutate=type5)
        self.assertTrue(descriptors(image)['perf_cf_gpc_target_pct']['editable'])
        self.assertEqual(descriptors(edit(image, {'perf_cf_gpc_target_pct': 60}).image)
                         ['perf_cf_gpc_target_pct']['current'], 60)

    def test_unsupported_table_is_an_advanced_diagnostic(self):
        def entry_size(blob, parser):
            blob[parser.pointer('P', 0xA8) + 2] = 56
        report = inspect_image(fixture(mutate=entry_size))
        self.assertFalse(set(PERF_CF_KEYS) & {f['key'] for f in report['fields']})
        self.assertIn('perf_cf_controllers', {d.get('resolver') for d in report['diagnostics']})
        self.assertEqual(unsupported_notes(report).keys(), {'advanced'})

    def test_only_the_reviewed_bindings_write_the_tables(self):
        for header in (6, 14):
            image = fixture(perf_cf=header)
            parser = backend(image)
            gpc, first = controller(parser, 0), policy(parser)
            probes = [(first['offset'] + 1, '<B'), (gpc['offset'] + 11, '<I'), (gpc['offset'] + 24, '<B'),
                      (controller(parser, 3)['target_offset'], '<I')]
            if header == 14:
                # The extra header bytes of this layout.
                probes.append((parser.perf_cf()['controllers']['offset'] + 6, '<B'))
            for offset, encoding in probes:
                with self.subTest(header=header, offset=offset):
                    with self.assertRaises(VbiosError) as exc:
                        edit(image, {'probe': 1}, field_registry=custom_registry('probe', [offset], encoding=encoding,
                                                                                scale=1))
                    self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')
        # The reviewed key over other bytes is refused.
        image = fixture()
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'perf_cf_gpc_hysteresis_up': 2}, field_registry=custom_registry(
                'perf_cf_gpc_hysteresis_up', [controller(backend(image), 0)['offset'] + 1], encoding='<B', scale=1))
        self.assertEqual(exc.exception.code, 'INVALID_FIELD_EVIDENCE')


class LpwrTests(unittest.TestCase):
    def test_switches_cover_the_entries_enabled_in_stock(self):
        fields = descriptors(fixture())
        self.assertEqual({key: fields[key]['lpwr_entries'] for key in LPWR_SWITCHES if key in fields},
                         {'lpwr_gr_power_gating': [0, 1], 'lpwr_mscg': [0, 1, 2], 'lpwr_nvdec_gating': [0, 1, 2, 3, 4],
                          'lpwr_nvenc_gating': [0, 1, 2, 3, 4], 'lpwr_ofa_gating': [0, 1, 2, 3, 4],
                          'lpwr_nvjpg_gating': [0, 1, 2, 3, 4], 'lpwr_difr': [0]})
        for key in LPWR_SWITCHES:
            if key in fields:
                self.assertEqual((fields[key]['current'], fields[key]['units'], fields[key]['switch'],
                                  fields[key]['section'], fields[key]['editable']), (1, 'flag', 'stock-off', 'advanced',
                                                                                     True))
                self.assertNotIn('depends_on', fields[key])
        # GR rail gating is off on this product (an RTX 5090): no switch and no idle time.
        self.assertNotIn('lpwr_gr_rail_gating', fields)
        self.assertNotIn('lpwr_gr_rail_gating_idle_us', fields)

    def test_off_clears_bit_0_of_the_covered_entries_and_stock_restores_them(self):
        image = fixture()
        parser = backend(image)
        fields = descriptors(image)
        # Every switch but GR rail gating (off on this product).
        expected = [key for key in LPWR_SWITCHES if key != 'lpwr_gr_rail_gating']
        self.assertEqual([key for key in LPWR_SWITCHES if key in fields], expected)
        for key in expected:
            name = LPWR_SWITCHES[key]
            with self.subTest(key=key):
                result = edit(image, {key: 0})
                self.assertTrue(result.manifest['integrity']['valid'])
                self.assertEqual(result.manifest['changed_object_ids'], [LPWR_OBJECTS[name]])
                table = parser.lpwr_table(name)
                width = struct.calcsize(table['format'])
                covered = fields[key]['lpwr_entries']
                changed_bytes_within(self, image, result, [table['entries'][i]['offset'] for i in covered], width)
                after = backend(result.image).lpwr_table(name)['entries']
                for before, entry in zip(table['entries'], after):
                    expected = before['value'] & ~1 if before['index'] in covered else before['value']
                    self.assertEqual(entry['value'], expected)
                self.assertEqual(descriptors(result.image)[key]['current'], 0)
                self.assertEqual(descriptors(result.image)[key]['lpwr_entries'], covered)
                self.assertEqual(edit(result.image, {key: 1}).blob, image.blob)

    def test_entries_that_disagree_leave_the_switch_read_only(self):
        def mixed(blob, parser):
            blob[lpwr_entry(parser, 'gr_pg', 1)['offset']] &= 0xFE
        image = fixture(mutate=mixed)
        field = descriptors(image)['lpwr_gr_power_gating']
        self.assertEqual((field['editable'], field['current'], field['reason']), (False, None, LPWR_MIXED_REASON))
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'lpwr_gr_power_gating': 0})
        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')

    def test_gr_rail_gating_only_on_products_that_enable_it(self):
        image = fixture(device=0x2C33, mutate=set_gr_rail_gating(0xFF))
        fields = descriptors(image)
        switch, idle = fields['lpwr_gr_rail_gating'], fields['lpwr_gr_rail_gating_idle_us']
        self.assertEqual((switch['current'], switch['editable'], switch['lpwr_entries']), (1, True, [0]))
        self.assertEqual((idle['current'], idle['units'], idle['stored_units'], idle['bounds']['minimum'],
                          idle['bounds']['maximum'], idle['depends_on']),
                         (500, 'us', '10 us', 250, 2000, {'field': 'lpwr_gr_rail_gating', 'value': 1}))
        parser = backend(image)
        at = lpwr_entry(parser, 'gr_rg', 0)['offset']
        off = edit(image, {'lpwr_gr_rail_gating': 0})
        self.assertEqual(off.blob[at:at + 5], bytes((0xFE, 0xFC, 0xFC, 0xFC, 0xFC)))
        self.assertEqual(off.manifest['changed_object_ids'], [0x7E])
        self.assertEqual(edit(off.image, {'lpwr_gr_rail_gating': 1}).blob, image.blob)
        word = parser.lpwr_table('gr_rg')['offset'] + 5
        result = edit(image, {'lpwr_gr_rail_gating_idle_us': 1230})
        self.assertEqual(struct.unpack_from('<H', result.blob, word)[0], 123)
        changed_bytes_within(self, image, result, [word], width=2)
        for value, code in ((1235, 'UNREPRESENTABLE_VALUE'), (240, 'OUT_OF_BOUNDS'), (2010, 'OUT_OF_BOUNDS')):
            with self.subTest(value=value):
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {'lpwr_gr_rail_gating_idle_us': value})
                self.assertEqual(exc.exception.code, code)
        with self.assertRaises(VbiosError) as exc:
            edit(off.image, {'lpwr_gr_rail_gating_idle_us': 1000})
        self.assertEqual(exc.exception.code, 'DEPENDENT_FIELD_DISABLED')
        # The RTX 5080 and 5090 Laptop GPUs enable entries 0..2; a stored Off reads 0 and Stock enables exactly
        # those.
        for device in (0x2C59, 0x2C18):
            with self.subTest(device=device):
                laptop = fixture(device=device, mutate=set_gr_rail_gating(0xFF, 0xFF, 0xFF))
                field = descriptors(laptop)['lpwr_gr_rail_gating']
                self.assertEqual((field['current'], field['editable'], field['lpwr_entries']), (1, True, [0, 1, 2]))
                self.assertNotIn('lpwr_coverage', field)
                at = lpwr_entry(backend(laptop), 'gr_rg', 0)['offset']
                off = edit(laptop, {'lpwr_gr_rail_gating': 0})
                self.assertEqual(off.blob[at:at + 5], bytes((0xFE, 0xFE, 0xFE, 0xFC, 0xFC)))
                field = descriptors(off.image)['lpwr_gr_rail_gating']
                self.assertEqual((field['current'], field['editable'], field['lpwr_entries']), (0, True, [0, 1, 2]))
                self.assertEqual(edit(off.image, {'lpwr_gr_rail_gating': 1}).blob, laptop.blob)
        # A reviewed product whose entry stores another value: read-only.
        field = descriptors(fixture(device=0x2C33, mutate=set_gr_rail_gating(0x7F)))['lpwr_gr_rail_gating']
        self.assertEqual((field['editable'], field['reason']), (False, LPWR_GR_RG_UNRECOGNIZED_REASON))

    def test_gr_rail_gating_on_unlisted_products_covers_the_enabled_entries(self):
        """A product LPWR_STOCK does not list: the switch covers the entries the image enables, and a copy saved with
        Off, which enables none, shows no switch."""
        self.assertNotIn(0x2C02, LPWR_STOCK['gr_rg'])
        # Entry 0 enabled, entry 1 stored like an enabled entry switched off (as a shipped-disabled one is).
        image = fixture(device=0x2C02, mutate=set_gr_rail_gating(0xFF, 0xFE))
        fields = descriptors(image)
        switch, idle = fields['lpwr_gr_rail_gating'], fields['lpwr_gr_rail_gating_idle_us']
        self.assertEqual((switch['current'], switch['editable'], switch['lpwr_entries'], switch['lpwr_coverage']),
                         (1, True, [0], LPWR_ENABLED_ENTRIES))
        self.assertIn('keep the original ROM to go back', switch['reason'])
        self.assertEqual((idle['editable'], idle['bounds']['minimum'], idle['bounds']['maximum']), (True, 250, 2000))
        self.assertEqual([len(t) for t in (lpwr_notes(switch), lpwr_notes(switch, 'es'), lpwr_notes(idle))], [1, 1, 0])
        at = lpwr_entry(backend(image), 'gr_rg', 0)['offset']
        off = edit(image, {'lpwr_gr_rail_gating': 0})
        self.assertTrue(off.manifest['integrity']['valid'])
        self.assertEqual(off.manifest['changed_object_ids'], [0x7E])
        changed_bytes_within(self, image, off, [at])
        self.assertEqual(off.blob[at:at + 5], bytes((0xFE, 0xFE, 0xFC, 0xFC, 0xFC)))
        self.assertEqual([a for a in off.manifest['affected_fields'] if a['field'] == 'lpwr_gr_rail_gating'],
                         [dict(field='lpwr_gr_rail_gating', before=1, after=0, units='flag', requested=True)])
        # The Off copy enables no entry: no switch, no idle time, and Stock cannot be requested there.
        after = descriptors(off.image)
        self.assertFalse({'lpwr_gr_rail_gating', 'lpwr_gr_rail_gating_idle_us'} & set(after))
        with self.assertRaises(VbiosError) as exc:
            edit(off.image, {'lpwr_gr_rail_gating': 1})
        self.assertEqual(exc.exception.code, 'UNKNOWN_FIELD')
        # The idle time edits while the switch is Stock and is refused with Off in the same edit.
        result = edit(image, {'lpwr_gr_rail_gating_idle_us': 1000})
        self.assertEqual(descriptors(result.image)['lpwr_gr_rail_gating_idle_us']['current'], 1000)
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'lpwr_gr_rail_gating': 0, 'lpwr_gr_rail_gating_idle_us': 1000})
        self.assertEqual(exc.exception.code, 'DEPENDENT_FIELD_DISABLED')
        # Off with the idle time requested again at its stored value: the same copy as Off alone, as on a listed
        # product, and the idle time is not listed as changed.
        same = edit(image, {'lpwr_gr_rail_gating': 0, 'lpwr_gr_rail_gating_idle_us': idle['current']})
        self.assertEqual(same.blob, off.blob)
        self.assertEqual([a['field'] for a in same.manifest['affected_fields'] if a['field'].startswith('lpwr_')],
                         ['lpwr_gr_rail_gating'])
        # Every enabled entry: entries 0..2 as on the laptops.
        field = descriptors(fixture(device=0x2C58, mutate=set_gr_rail_gating(0xFF, 0xFF, 0xFF)))['lpwr_gr_rail_gating']
        self.assertEqual((field['editable'], field['lpwr_entries']), (True, [0, 1, 2]))
        # An enabled entry with an unreviewed form: read-only, with its idle time.
        fields = descriptors(fixture(device=0x2C02, mutate=set_gr_rail_gating(0xFF, 0x7F)))
        switch = fields['lpwr_gr_rail_gating']
        self.assertEqual((switch['editable'], switch['reason'], switch['lpwr_entries']),
                         (False, LPWR_GR_RG_ENABLED_UNRECOGNIZED_REASON, [0, 1]))
        self.assertEqual(fields['lpwr_gr_rail_gating_idle_us']['reason'], LPWR_TIME_SWITCH_REASON)
        self.assertEqual(lpwr_notes(fields['lpwr_gr_rail_gating']), [])
        with self.assertRaises(VbiosError) as exc:
            edit(fixture(device=0x2C02, mutate=set_gr_rail_gating(0xFF, 0x7F)), {'lpwr_gr_rail_gating': 0})
        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')
        # No enabled entry: no switch (an entry shipped disabled looks like one switched off).
        self.assertNotIn('lpwr_gr_rail_gating', descriptors(fixture(device=0x2C02, mutate=set_gr_rail_gating(0xFE))))

    def test_difr_idle_times_bounds_units_and_dependency(self):
        image = fixture()
        fields = descriptors(image)
        self.assertEqual([(fields[k]['current'], fields[k]['units'], fields[k]['bounds']['minimum'],
                           fields[k]['bounds']['maximum']) for k in DIFR_TIMES],
                         [(1000, 'ms', 500, 4000), (15, 'us', 8, 60), (15, 'us', 8, 60)])
        header = backend(image).lpwr_table('difr')['offset']
        result = edit(image, {'lpwr_difr_dfpr_idle_ms': 4000, 'lpwr_difr_sw_asr_idle_us': 8,
                              'lpwr_difr_cg_idle_us': 60})
        self.assertEqual(struct.unpack_from('<HHH', result.blob, header + 5), (4000, 8, 60))
        changed_bytes_within(self, image, result, [header + 5, header + 7, header + 9], width=2)
        self.assertEqual(result.manifest['changed_object_ids'], [0x8E])
        self.assertEqual(edit(result.image, {'lpwr_difr_dfpr_idle_ms': 1000, 'lpwr_difr_sw_asr_idle_us': 15,
                                             'lpwr_difr_cg_idle_us': 15}).blob, image.blob)
        for key, value in (('lpwr_difr_dfpr_idle_ms', 499), ('lpwr_difr_dfpr_idle_ms', 4001),
                           ('lpwr_difr_sw_asr_idle_us', 7), ('lpwr_difr_cg_idle_us', 61)):
            with self.subTest(key=key, value=value):
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {key: value})
                self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        off = edit(image, {'lpwr_difr': 0}).image
        with self.assertRaises(VbiosError) as exc:
            edit(off, {'lpwr_difr_dfpr_idle_ms': 2000})
        self.assertEqual(exc.exception.code, 'DEPENDENT_FIELD_DISABLED')
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'lpwr_difr': 0, 'lpwr_difr_cg_idle_us': 30})
        self.assertEqual(exc.exception.code, 'DEPENDENT_FIELD_DISABLED')
        result = edit(off, {'lpwr_difr': 1, 'lpwr_difr_dfpr_idle_ms': 2000})
        self.assertEqual(descriptors(result.image)['lpwr_difr_dfpr_idle_ms']['current'], 2000)
        # A DIFR entry 0 stored disabled reads Off; its times stay listed and depend on the switch.
        def disabled(blob, parser):
            blob[lpwr_entry(parser, 'difr', 0)['offset']] = 0xBE
        fields = descriptors(fixture(mutate=disabled))
        self.assertEqual((fields['lpwr_difr']['current'], fields['lpwr_difr']['editable']), (0, True))
        self.assertTrue(all(fields[k]['editable'] for k in DIFR_TIMES))

    def test_only_the_reviewed_bindings_write_the_tables(self):
        image = fixture()
        parser = backend(image)
        probes = ((lpwr_entry(parser, 'gr_pg', 0)['offset'] + 4, '<B'),      # rail mask byte
                  (lpwr_entry(parser, 'ms', 2)['offset'], '<I'),              # a covered enable word, other bits
                  (lpwr_entry(parser, 'ms', 3)['offset'], '<B'),              # a disabled entry
                  (parser.lpwr_table('difr')['offset'] + 4, '<B'),           # a header byte
                  (lpwr_entry(parser, 'nvjpg', 4)['offset'], '<H'))
        for offset, encoding in probes:
            with self.subTest(offset=offset):
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {'probe': 3}, field_registry=custom_registry('probe', [offset], encoding=encoding,
                                                                            scale=1))
                self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')


class SectionTests(unittest.TestCase):
    def test_import_sections_leave_the_advanced_section_out(self):
        self.assertEqual(IMPORT_SECTIONS, ('power', 'voltage', 'clocks', 'current', 'fans'))
        self.assertEqual(SECTION_NAMES[-2:], ('other', 'advanced'))
        image = fixture()
        donor = edit(image, {'perf_cf_gpc_target_pct': 60, 'lpwr_mscg': 0}).image
        with self.assertRaises(VbiosError) as exc:
            import_fields(image, donor, ['advanced'])
        self.assertEqual(exc.exception.code, 'INVALID_SECTIONS')
        report, result = import_fields(image, donor, IMPORT_SECTIONS, include_opt_in=True)
        self.assertEqual((report['changes'], result), ({}, None))
        self.assertFalse([e for e in report['skipped'] if e['section'] == 'advanced'])

    def test_section_order_puts_the_advanced_section_last(self):
        fields = inspect_image(fixture())['fields']
        ordered = [field_section(f) for f in section_order(fields)]
        self.assertEqual(ordered[-1], 'advanced')
        self.assertEqual(ordered.index('advanced'), len(ordered) - len([f for f in fields
                                                                       if f.get('section') == 'advanced']))

    def test_labels_reasons_and_dependency_text_in_both_languages(self):
        image = fixture(device=0x2C33, mutate=set_gr_rail_gating(0xFF))
        fields = descriptors(image)
        keys = [f['key'] for f in inspect_image(image)['fields'] if f.get('section') == 'advanced']
        self.assertEqual(len(keys), 25)
        for key in keys:
            with self.subTest(key=key):
                english, spanish = field_label(fields[key], 'en'), field_label(fields[key], 'es')
                self.assertNotEqual(english, fields[key]['label'])
                self.assertTrue('experimental' in english and 'experimental' in spanish)
        self.assertEqual(field_label(fields['perf_cf_dram_target_pct']), 'DRAM utilization target (experimental)')
        self.assertEqual(field_label(fields['perf_cf_vid_hysteresis_down'], 'es'),
                         'Histéresis de bajada VID (muestras, experimental)')
        self.assertEqual((value_text(fields['lpwr_mscg'], 1), value_text(fields['lpwr_mscg'], 0, 'es')),
                         ('Stock', 'Desactivado'))
        self.assertEqual(value_text(fields['perf_cf_util_policy'], 1), 'On')
        self.assertEqual(dependency_reason(fields['perf_cf_gpc_target_pct'], fields),
                         'Turn on "Utilization clock policy" to change this value. While it is off, the stored '
                         'value is kept.')
        self.assertIn('deja el interruptor "Rail gating de GR" en De fábrica',
                      dependency_reason(fields['lpwr_gr_rail_gating_idle_us'], fields, 'es'))
        self.assertIn('10 µs steps', field_label(fields['lpwr_gr_rail_gating_idle_us']))
        self.assertIn('pasos de 10 µs', field_label(fields['lpwr_gr_rail_gating_idle_us'], 'es'))
        self.assertIsNone(dependency_reason(fields['lpwr_mscg'], fields))
        for reason in (PERF_CF_POLICY_UNRECOGNIZED_REASON, PERF_CF_CONTROLLER_UNRECOGNIZED_REASON, LPWR_MIXED_REASON,
                       LPWR_GR_RG_UNRECOGNIZED_REASON, LPWR_TIME_SWITCH_REASON):
            with self.subTest(reason=reason):
                english, spanish = (read_only_reason(dict(reason=reason), lang) for lang in ('en', 'es'))
                self.assertTrue(english and spanish and english != spanish)
                self.assertNotEqual(spanish, read_only_reason(dict(reason='unmapped'), 'es'))
        for key in ('section.advanced', 'section.advanced_note', 'section.advanced_perf', 'section.advanced_lpwr',
                    'error.DEPENDENT_FIELD_DISABLED', 'flag_stock', 'lpwr.enabled_entries'):
            self.assertIn(key, MESSAGES_EN)
            self.assertIn(key, MESSAGES_ES)
        self.assertEqual(MESSAGES_EN['section.advanced'], 'Advanced: performance controllers and idle power')
        self.assertEqual(MESSAGES_ES['section.advanced'], 'Avanzado: controladores de rendimiento y ahorro en reposo')

    def test_cli_fields_list_the_section_and_the_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'advanced.rom'
            path.write_bytes(synthetic_blackwell(perf_cf=True, lpwr=True))
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = cli.main(['fields', str(path)])
        self.assertEqual(code, 0)
        fields = {f['key']: f for f in json.loads(stream.getvalue())['result']['fields']}
        self.assertEqual(fields['perf_cf_vid_jump_pct']['section'], 'advanced')
        self.assertEqual(fields['perf_cf_vid_jump_pct']['depends_on'], {'field': 'perf_cf_util_policy', 'value': 1})
        self.assertEqual(fields['lpwr_difr_cg_idle_us']['depends_on'], {'field': 'lpwr_difr', 'value': 1})
        self.assertEqual((fields['lpwr_difr']['section'], fields['lpwr_difr']['switch']), ('advanced', 'stock-off'))


class LegacyAdvancedTests(unittest.TestCase):
    """Turing, Ampere and Ada: the same Advanced fields, read from their own table layouts."""
    SWITCHES = {'turing': {'lpwr_gr_power_gating': [0, 1, 4], 'lpwr_mscg': [0, 1]},
                'ampere': {'lpwr_gr_power_gating': [0, 1, 3], 'lpwr_mscg': [0, 1], 'lpwr_gr_rail_gating': [0, 1]},
                'ada': {'lpwr_gr_power_gating': [0, 1, 2], 'lpwr_mscg': [0, 1], 'lpwr_difr': [0]}}
    TIMES = {'turing': {}, 'ampere': {'lpwr_gr_rail_gating_idle_us': (5000, 2500, 20000)},
             'ada': {'lpwr_difr_dfpr_idle_ms': (1000, 500, 4000), 'lpwr_difr_sw_asr_idle_us': (15, 8, 60),
                     'lpwr_difr_cg_idle_us': (15, 8, 60)}}
    PERCENTS = {'turing': (40, 55, 40, 55, 60, 80), 'ampere': (40, 75, 65, 80, 65, 85), 'ada': (40, 75, 65, 80, 65, 85)}

    def test_fields_per_family(self):
        for family, switches in self.SWITCHES.items():
            with self.subTest(family=family):
                image = legacy_advanced(family)
                parser = backend(image)
                fields = {k: f for k, f in descriptors(image).items() if f.get('section') == 'advanced'}
                self.assertEqual(set(fields), set(PERF_CF_KEYS) | set(switches) | set(self.TIMES[family]))
                self.assertTrue(all(f['editable'] and f['experimental'] for f in fields.values()))
                self.assertEqual([fields[f'perf_cf_{d}_{k}']['current'] for d in DOMAINS
                                  for k in ('target_pct', 'jump_pct')], list(self.PERCENTS[family]))
                self.assertEqual([fields[f'perf_cf_{d}_hysteresis_{k}']['current'] for d in DOMAINS
                                  for k in ('down', 'up')], [9, 1, 4, 1, 9, 1])
                self.assertEqual([fields[f'perf_cf_{d}_target_pct']['clock_domain'] for d in DOMAINS],
                                 ['GPC', 'DRAM', 'VID'])
                # The targets and jump thresholds vary per product here: no stock value is claimed.
                self.assertNotIn('stock', fields['perf_cf_gpc_target_pct'])
                self.assertIn('Turing, Ampere and Ada', fields['perf_cf_util_policy']['reason'])
                self.assertEqual({k: fields[k]['lpwr_entries'] for k in switches}, switches)
                for key, (current, low, high) in self.TIMES[family].items():
                    self.assertEqual((fields[key]['current'], fields[key]['bounds']['minimum'],
                                      fields[key]['bounds']['maximum']), (current, low, high))
                image_bindings = bindings(image)
                chains = len(parser.chains)
                for key, field in fields.items():
                    covered = len(field.get('lpwr_entries', [0]))
                    self.assertEqual(len(image_bindings[key].offsets), chains * covered, key)

    def test_edits_write_every_chain_and_revert(self):
        changes = {'perf_cf_gpc_target_pct': 30, 'perf_cf_gpc_jump_pct': 95, 'perf_cf_dram_hysteresis_down': 16,
                   'perf_cf_vid_hysteresis_up': 4, 'lpwr_mscg': 0, 'lpwr_gr_power_gating': 0}
        extra = {'turing': {}, 'ampere': {'lpwr_gr_rail_gating_idle_us': 2500},
                 'ada': {'lpwr_difr_dfpr_idle_ms': 4000, 'lpwr_difr_cg_idle_us': 8}}
        for family in LEGACY_DEVICES:
            with self.subTest(family=family):
                image = legacy_advanced(family)
                request = {**changes, **extra[family]}
                result = edit(image, request)
                self.assertTrue(result.manifest['integrity']['valid'])
                self.assertTrue(inspect_image(result.image)['integrity']['valid'])
                after = descriptors(result.image)
                for key, value in request.items():
                    self.assertEqual(Decimal(str(after[key]['current'])), Decimal(value), key)
                image_bindings = bindings(image)
                allowed = {at for key in request for start in image_bindings[key].offsets
                           for at in range(start, start + struct.calcsize(image_bindings[key].encoding))}
                self.assertLessEqual(changed(image, result), allowed | {r['offset'] for r in
                                                                        result.manifest['integrity_repairs']})
                before = descriptors(image)
                self.assertEqual(edit(result.image, {key: before[key]['current'] for key in request}).blob, image.blob)

    def test_stock_percents_store_the_stored_fractions(self):
        """Turing, Ampere and Ada store 55, 60 and 80 % truncated (0x8cc, 0x999, 0xccc): going back to them gives the
        stock bytes."""
        image = legacy_advanced('turing')
        parser = backend(image)
        gpc, vid = controller(parser, 0), controller(parser, 2)
        lowered = edit(image, {'perf_cf_gpc_jump_pct': 50, 'perf_cf_vid_target_pct': 50, 'perf_cf_vid_jump_pct': 70})
        self.assertEqual([struct.unpack_from('<I', lowered.blob, at)[0]
                          for at in (gpc['jump_offset'], vid['target_offset'], vid['jump_offset'])],
                         [0x800, 0x800, percent_fxp(70)])
        back = edit(lowered.image, {'perf_cf_gpc_jump_pct': 55, 'perf_cf_vid_target_pct': 60,
                                    'perf_cf_vid_jump_pct': 80})
        self.assertEqual(back.blob, image.blob)
        # GB20x keeps its own rule: the stock fraction of each field (the DRAM target's 0x851 for 52 %) and the
        # nearest fraction for any other percent, so these percents store their nearest fractions there.
        gb20x = fixture()
        gpc, dram = controller(backend(gb20x), 0), controller(backend(gb20x), 1)
        for changes, at, raw in (({'perf_cf_gpc_jump_pct': 80}, gpc['jump_offset'], 0xCCD),
                                 ({'perf_cf_dram_target_pct': 55}, dram['target_offset'], 0x8CD),
                                 ({'perf_cf_gpc_target_pct': 52}, gpc['target_offset'], 0x852),
                                 ({'perf_cf_gpc_jump_pct': 60}, gpc['jump_offset'], 0x99A),
                                 ({'perf_cf_gpc_target_pct': 58}, gpc['target_offset'], 0x948)):
            with self.subTest(changes=changes):
                self.assertEqual(struct.unpack_from('<I', edit(gb20x, changes).blob, at)[0], raw)

    def test_reviewed_entry_sizes(self):
        for size in (24, 28, 32, 49):
            with self.subTest(size=size):
                image = legacy_advanced('ampere', entry_size=size)
                parser = backend(image)
                self.assertEqual(controller(parser, 2)['offset'],
                                 parser.perf_cf()['controllers']['offset'] + 6 + 2 * size)
                result = edit(image, {'perf_cf_vid_target_pct': 50})
                at = controller(parser, 2)['target_offset']
                self.assertEqual([struct.unpack_from('<I', result.blob, a)[0] for a in parser.copy_offsets(at, 4)],
                                 [0x800, 0x800])
        for size in (23, 40):
            with self.subTest(size=size):
                report = inspect_image(legacy_advanced('ampere', entry_size=size))
                self.assertFalse(set(PERF_CF_KEYS) & {f['key'] for f in report['fields']})
                self.assertIn('perf_cf_controllers', {d.get('resolver') for d in report['diagnostics']})
                self.assertEqual(unsupported_notes(report).keys(), {'advanced'})

    def test_the_clock_table_row_names_the_controller_domain(self):
        image = legacy_advanced('ada')
        parser = backend(image)
        # Byte 19 = 4 is the GB20x video domain, but the HUB row of these clocks tables.
        fields = descriptors(legacy_advanced('ada', mutate=in_every_chain(parser, controller(parser, 2)['offset'] + 19,
                                                                          b'\x04')))
        for kind in CONTROLLER_KINDS:
            self.assertEqual((fields[f'perf_cf_vid_{kind}']['editable'], fields[f'perf_cf_vid_{kind}']['reason']),
                             (False, PERF_CF_CONTROLLER_UNRECOGNIZED_REASON))
            self.assertTrue(fields[f'perf_cf_gpc_{kind}']['editable'])
        # The type 5 subclass is read where it was traced (gsp_ga10x.bin), not on Turing.
        for family, editable in (('ampere', True), ('turing', False)):
            parser = backend(legacy_advanced(family))
            fields = descriptors(legacy_advanced(family, mutate=in_every_chain(parser, controller(parser, 0)['offset'],
                                                                               b'\x05')))
            self.assertEqual(fields['perf_cf_gpc_target_pct']['editable'], editable, family)
        # A policy entry 0 that does not run controllers 0..2 leaves every PERF_CF field read-only.
        at = parser.perf_cf()['policies']['entries'][0]['offset'] + 6
        fields = descriptors(legacy_advanced('turing', mutate=in_every_chain(backend(legacy_advanced('turing')), at,
                                                                             b'\x03')))
        self.assertTrue(all(fields[k]['reason'] == PERF_CF_POLICY_UNRECOGNIZED_REASON for k in PERF_CF_KEYS))

    def test_switches_of_stock_disabled_values(self):
        """Ampere and Ada GR power gating and MSCG: disabled entries keep their own values, so Off stays readable."""
        for family in ('ampere', 'ada'):
            for key in ('lpwr_gr_power_gating', 'lpwr_mscg'):
                with self.subTest(family=family, key=key):
                    image = legacy_advanced(family)
                    covered = self.SWITCHES[family][key]
                    off = edit(image, {key: 0})
                    parser = backend(image)
                    table = parser.lpwr_table(LPWR_SWITCHES[key])
                    after = backend(off.image).lpwr_table(LPWR_SWITCHES[key])['entries']
                    self.assertEqual([e['value'] for e in after], [e['value'] & ~1 if e['index'] in covered else
                                                                   e['value'] for e in table['entries']])
                    field = descriptors(off.image)[key]
                    self.assertEqual((field['current'], field['lpwr_entries'], field['editable']), (0, covered, True))
                    self.assertEqual(edit(off.image, {key: 1}).blob, image.blob)
        # An Ada image whose stock-disabled entry 2 stores an enabled entry switched off (two RTX 4090 images).
        mixed = legacy_advanced('ada', lpwr={0x80: ['e7ffffff00', 'e7ffffff00', 'e6ffffff00', 'e7ffffff00',
                                                    'c0ffffff00']})
        field = descriptors(mixed)['lpwr_gr_power_gating']
        self.assertEqual((field['editable'], field['current'], field['reason']), (False, None, LPWR_MIXED_REASON))

    def test_switches_of_reviewed_products(self):
        """Where a stock-disabled entry looks like a switched-off one, a reviewed product's switch covers the entries
        it enables in stock, also in a copy saved with Off; any other product's switch covers the entries the image
        enables (test_switches_of_unlisted_products)."""
        # Turing: a desktop TU106 (entries 0, 1 and 4) and a laptop TU106 (also entry 3).
        laptop = legacy_advanced('turing', device=0x1F11, lpwr={0x80: ['efffffff01', 'e7ffffff01', 'e6ffffff00',
                                                                       'e7ffffff00', 'e5ffffff00']})
        fields = descriptors(laptop)
        self.assertEqual(fields['lpwr_gr_power_gating']['lpwr_entries'], [0, 1, 3, 4])
        off = edit(laptop, {'lpwr_gr_power_gating': 0, 'lpwr_mscg': 0})
        table = backend(off.image).lpwr_table('gr_pg')['entries']
        self.assertEqual([e['value'] & 0xFF for e in table], [0xEE, 0xE6, 0xE6, 0xE6, 0xE4])
        self.assertEqual((descriptors(off.image)['lpwr_gr_power_gating']['current'],
                          descriptors(off.image)['lpwr_mscg']['current']), (0, 0))
        self.assertEqual(edit(off.image, {'lpwr_gr_power_gating': 1, 'lpwr_mscg': 1}).blob, laptop.blob)
        # A reviewed product whose entry stores another value: read-only.
        fields = descriptors(legacy_advanced('turing', lpwr={0x80: ['c1ffffff01', 'e7ffffff01', 'e6ffffff01',
                                                                    'e6ffffff01', 'e5ffffff01']}))
        self.assertEqual(fields['lpwr_gr_power_gating']['reason'], LPWR_STOCK_UNRECOGNIZED_REASON)
        # The RTX 2000 Ada enables entry 0: a stored Off reads 0 and Stock enables exactly entry 0.
        disabled = ['00feffff00ffffffffffffffffffffffff'] * 4
        stored_off = legacy_advanced('ada', lpwr={0xE8: ['feffffff026400fa002c01640096009600'] + disabled})
        self.assertEqual(descriptors(stored_off)['lpwr_difr']['current'], 0)
        self.assertEqual(edit(stored_off, {'lpwr_difr': 1}).blob, legacy_advanced('ada').blob)
        # An RTX 3090 enables GR rail gating entries 0..1: its Off copy keeps the switch, at Off.
        off = edit(legacy_advanced('ampere'), {'lpwr_gr_rail_gating': 0})
        field = descriptors(off.image)['lpwr_gr_rail_gating']
        self.assertEqual((field['current'], field['editable'], field['lpwr_entries']), (0, True, [0, 1]))
        self.assertNotIn('lpwr_coverage', field)
        self.assertEqual(edit(off.image, {'lpwr_gr_rail_gating': 1}).blob, legacy_advanced('ampere').blob)
        self.assertEqual(descriptors(legacy_advanced('ampere', lpwr={0xD4: ['7f', 'ff', 'fe', 'fe', 'fe']}))
                         ['lpwr_gr_rail_gating']['reason'], LPWR_GR_RG_UNRECOGNIZED_REASON)

    def test_switches_of_unlisted_products(self):
        """A product LPWR_STOCK does not list: each switch covers the entries the image enables, while each stores a
        reviewed form; Off clears exactly them, so the Off copy enables none and shows no switch (nor its idle
        times); an image that enables none has no switch."""
        # (family, device, switch, BIT P offset, entries the image enables, enable bytes after Off, idle times).
        cases = (('turing', 0x1F95, 'lpwr_gr_power_gating', 0x80, [0, 1, 4], [0xEE, 0xE6, 0xE6, 0xE6, 0xE4], ()),
                 ('turing', 0x1F95, 'lpwr_mscg', 0x84, [0, 1], [0xFC, 0xEC, 0xEC, 0xEC, 0xCC], ()),
                 ('ampere', 0x2203, 'lpwr_gr_rail_gating', 0xD4, [0, 1], [0xFE] * 5, ('lpwr_gr_rail_gating_idle_us',)),
                 ('ada', 0x28E0, 'lpwr_difr', 0xE8, [0], [0xFE, 0x00, 0x00, 0x00, 0x00], DIFR_TIMES))
        for family, device, key, pointer, enabled, after, times in cases:
            with self.subTest(family=family, key=key):
                self.assertNotIn(device, LPWR_STOCK[LPWR_SWITCHES[key]])
                image = legacy_advanced(family, device=device)
                parser = backend(image)
                fields = descriptors(image)
                field = fields[key]
                self.assertEqual((field['current'], field['editable'], field['lpwr_entries'], field['lpwr_coverage']),
                                 (1, True, enabled, LPWR_ENABLED_ENTRIES))
                self.assertTrue(all(fields[k]['editable'] for k in times))
                self.assertEqual(len(bindings(image)[key].offsets), len(parser.chains) * len(enabled))
                off = edit(image, {key: 0})
                self.assertTrue(off.manifest['integrity']['valid'])
                table = backend(off.image).lpwr_table(LPWR_SWITCHES[key])['entries']
                self.assertEqual([e['value'] & 0xFF for e in table], after)
                stored = parser.lpwr_table(LPWR_SWITCHES[key])['entries']
                self.assertEqual([e['value'] for e in table],
                                 [e['value'] & ~1 if e['index'] in enabled else e['value'] for e in stored])
                allowed = {at for start in bindings(image)[key].offsets
                           for at in range(start, start + struct.calcsize(bindings(image)[key].encoding))}
                self.assertLessEqual(changed(image, off), allowed | {r['offset'] for r in
                                                                     off.manifest['integrity_repairs']})
                self.assertFalse({key, *times} & set(descriptors(off.image)))
                # Its idle times requested again at their stored values with Off: the same copy.
                if times:
                    self.assertEqual(edit(image, {key: 0, **{k: fields[k]['current'] for k in times}}).blob,
                                     off.blob)
                # The other switch of the same image is unaffected.
                others = {k: f['current'] for k, f in descriptors(off.image).items() if k in LPWR_SWITCHES}
                self.assertEqual(others, {k: f['current'] for k, f in fields.items()
                                          if k in LPWR_SWITCHES and k != key})
        # An enabled entry with an unreviewed form: read-only, with its idle times.
        fields = descriptors(legacy_advanced('ada', device=0x28E0, lpwr={
            0xE8: ['fdffffff026400fa002c01640096009600'] + ['00feffff00ffffffffffffffffffffffff'] * 4}))
        self.assertEqual((fields['lpwr_difr']['editable'], fields['lpwr_difr']['reason']),
                         (False, LPWR_ENABLED_UNRECOGNIZED_REASON))
        self.assertTrue(all(fields[k]['reason'] == LPWR_TIME_SWITCH_REASON for k in DIFR_TIMES))
        fields = descriptors(legacy_advanced('turing', device=0x1F95, lpwr={0x80: ['c1ffffff01', 'e7ffffff01',
                                                                                  'e6ffffff01', 'e6ffffff01',
                                                                                  'e5ffffff01']}))
        self.assertEqual((fields['lpwr_gr_power_gating']['editable'], fields['lpwr_gr_power_gating']['reason']),
                         (False, LPWR_ENABLED_UNRECOGNIZED_REASON))
        self.assertTrue(fields['lpwr_mscg']['editable'])
        self.assertEqual(descriptors(legacy_advanced('ampere', device=0x2203, lpwr={0xD4: ['7f', 'ff', 'fe', 'fe',
                                                                                          'fe']}))
                         ['lpwr_gr_rail_gating']['reason'], LPWR_GR_RG_ENABLED_UNRECOGNIZED_REASON)
        # Shipped disabled: GR rail gating on an RTX 3090 Ti, Ada DIFR entry 0 stored 0xfffffffe or 0xffffffee (as
        # on the RTX 4070 and RTX 4090, like a switched-off entry 0): no switch and no idle time.
        self.assertFalse({'lpwr_gr_rail_gating', 'lpwr_gr_rail_gating_idle_us'} &
                         set(descriptors(legacy_advanced('ampere', device=0x2203, lpwr={0xD4: ['fe'] * 5}))))
        for value in ('feffffff', 'eeffffff'):
            entries = [value + '026400fa002c01640096009600'] + ['00feffff00ffffffffffffffffffffffff'] * 4
            fields = descriptors(legacy_advanced('ada', device=0x28E0, lpwr={0xE8: entries}))
            self.assertFalse({'lpwr_difr', *DIFR_TIMES} & set(fields))

    def test_unlisted_products_cover_enabled_entries_only_on_the_reviewed_tables(self):
        """A table no corpus image of the family references (Ampere DIFR, Turing GR rail gating and DIFR): on a
        product LPWR_STOCK does not list, an enabled entry keeps the switch read-only, whatever it stores."""
        for family, device, name, enabled, disabled in (('ampere', 0x2203, 'difr', 0xFFFFFFFF, 0xFFFFFFFE),
                                                        ('turing', 0x1F95, 'gr_rg', 0xFF, 0xFE),
                                                        ('turing', 0x1F95, 'difr', 0xFFFFFFFF, 0xFFFFFFFE)):
            with self.subTest(family=family, name=name):
                parser = backend(legacy_advanced(family, device=device))
                self.assertIsNone(parser.lpwr_table(name))
                table = dict(entries=[dict(index=i, offset=0, value=enabled if i == 0 else disabled) for i in range(5)])
                covered, reason, structural = lpwr_covered(parser, family, name, table)
                self.assertEqual(([e['index'] for e in covered], reason, structural),
                                 ([0], LPWR_TABLE_UNREVIEWED_REASON, True))
                table = dict(entries=[dict(index=i, offset=0, value=disabled) for i in range(5)])
                self.assertEqual(lpwr_covered(parser, family, name, table)[:2], ([], None))
        # The same entries on the tables the forms were reviewed on: a switch over the enabled entry.
        for family, device, name, enabled, disabled in (('ampere', 0x2203, 'gr_rg', 0xFF, 0xFE),
                                                        ('ada', 0x28E0, 'difr', 0xFFFFFFFF, 0xFFFFFFFE)):
            with self.subTest(family=family, name=name):
                parser = backend(legacy_advanced(family, device=device))
                table = dict(entries=[dict(index=i, offset=0, value=enabled if i == 0 else disabled) for i in range(5)])
                covered, reason, structural = lpwr_covered(parser, family, name, table)
                self.assertEqual(([e['index'] for e in covered], reason, structural), ([0], None, True))

    def test_dependent_fields_change_only_while_their_switch_is_on(self):
        for family, switch, key, value in (('turing', 'perf_cf_util_policy', 'perf_cf_gpc_target_pct', 50),
                                           ('ampere', 'lpwr_gr_rail_gating', 'lpwr_gr_rail_gating_idle_us', 3000),
                                           ('ada', 'lpwr_difr', 'lpwr_difr_sw_asr_idle_us', 30)):
            with self.subTest(family=family, key=key):
                image = legacy_advanced(family)
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {switch: 0, key: value})
                self.assertEqual(exc.exception.code, 'DEPENDENT_FIELD_DISABLED')
                off = edit(image, {switch: 0}).image
                with self.assertRaises(VbiosError) as exc:
                    edit(off, {key: value})
                self.assertEqual(exc.exception.code, 'DEPENDENT_FIELD_DISABLED')
                self.assertEqual(descriptors(edit(off, {switch: 1, key: value}).image)[key]['current'], value)
        image = legacy_advanced('ada')
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'perf_cf_dram_target_pct': 85, 'perf_cf_dram_jump_pct': 70})
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_only_the_reviewed_bindings_write_the_tables(self):
        for family in LEGACY_DEVICES:
            image = legacy_advanced(family)
            parser = backend(image)
            gpc = controller(parser, 0)
            probes = [(gpc['offset'] + 11, '<I'), (gpc['offset'] + 22, '<B'),          # a gain, a topology index
                      (controller(parser, 3)['target_offset'], '<I'),                   # another controller
                      (parser.perf_cf()['controllers']['offset'] + 4, '<B'),            # a header byte
                      (policy(parser)['offset'] + 1, '<B'),                             # policy entry 0, not bit 7
                      (lpwr_entry(parser, 'gr_pg', 0)['offset'] + 4, '<B'),             # a GR rail mask byte
                      (lpwr_entry(parser, 'ms', 0)['offset'], '<I'),                    # a covered word, other bits
                      (lpwr_entry(parser, 'ms', 4)['offset'], '<B'),                    # a disabled entry
                      (parser.lpwr_table('ms')['offset'] + 5, '<B')]                    # the MSCG idle word
            if family == 'ampere':
                probes += [(parser.lpwr_table('gr_rg')['offset'] + 7, '<H'), (lpwr_entry(parser, 'gr_rg', 3)['offset'],
                                                                             '<B')]
            if family == 'ada':
                probes += [(lpwr_entry(parser, 'difr', 1)['offset'], '<B'),
                           (lpwr_entry(parser, 'difr', 0)['offset'] + 4, '<B'),
                           (parser.lpwr_table('gr_rg')['offset'] + 5, '<H')]
            for offset, encoding in probes:
                with self.subTest(family=family, offset=offset):
                    probe(self, image, parser.copy_offsets(offset, 1), encoding)
            # The reviewed key over other bytes is refused.
            with self.assertRaises(VbiosError) as exc:
                edit(image, {'perf_cf_gpc_hysteresis_up': 2}, field_registry=custom_registry(
                    'perf_cf_gpc_hysteresis_up', parser.copy_offsets(gpc['offset'] + 1, 1), encoding='<B', scale=1))
            self.assertEqual(exc.exception.code, 'INVALID_FIELD_EVIDENCE')

    def test_import_and_texts(self):
        image = legacy_advanced('ampere')
        donor = edit(image, {'perf_cf_gpc_target_pct': 60, 'lpwr_mscg': 0, 'lpwr_gr_rail_gating_idle_us': 3000}).image
        report, result = import_fields(image, donor, IMPORT_SECTIONS, include_opt_in=True)
        self.assertEqual((report['changes'], result), ({}, None))
        english, spanish = (read_only_reason(dict(reason=LPWR_STOCK_UNRECOGNIZED_REASON), language)
                            for language in ('en', 'es'))
        self.assertTrue(english and spanish and english != spanish)
        self.assertNotEqual(spanish, read_only_reason(dict(reason='unmapped'), 'es'))
        # The reasons of a product LPWR_STOCK does not list read as their listed counterparts in the window.
        for reason, same in ((LPWR_ENABLED_UNRECOGNIZED_REASON, LPWR_STOCK_UNRECOGNIZED_REASON),
                             (LPWR_GR_RG_ENABLED_UNRECOGNIZED_REASON, LPWR_GR_RG_UNRECOGNIZED_REASON),
                             (LPWR_TABLE_UNREVIEWED_REASON, None)):
            for language in ('en', 'es'):
                text = read_only_reason(dict(reason=reason), language)
                self.assertNotEqual(text, read_only_reason(dict(reason='unmapped'), language))
                if same:
                    self.assertEqual(text, read_only_reason(dict(reason=same), language))
        self.assertNotEqual(*(read_only_reason(dict(reason=LPWR_TABLE_UNREVIEWED_REASON), language)
                              for language in ('en', 'es')))
        self.assertTrue(MESSAGES_EN['section.advanced_note'].startswith('Blackwell, Ada, Ampere and Turing.'))
        self.assertTrue(MESSAGES_ES['section.advanced_note'].startswith('Blackwell, Ada, Ampere y Turing.'))
        fields = descriptors(legacy_advanced('ada'))
        self.assertEqual(field_label(fields['perf_cf_vid_jump_pct']), 'VID jump threshold (experimental)')
        self.assertEqual(value_text(fields['lpwr_difr'], 0, 'es'), 'Desactivado')


if __name__ == '__main__':
    unittest.main()
