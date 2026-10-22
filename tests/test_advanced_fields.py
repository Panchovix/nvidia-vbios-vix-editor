"""GB20x Advanced section (PERF_CF controllers, LPWR idle power): synthetic images and opt-in reference ROMs."""
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
from nvidia_vbios.editor.registry import (LPWR_GR_RG_UNRECOGNIZED_REASON, LPWR_GR_RG_UNREVIEWED_REASON,
                                          LPWR_MIXED_REASON, LPWR_TIME_SWITCH_REASON,
                                          PERF_CF_CONTROLLER_UNRECOGNIZED_REASON, PERF_CF_POLICY_UNRECOGNIZED_REASON,
                                          registry)
from nvidia_vbios.gui.i18n import MESSAGES_EN
from nvidia_vbios.gui.messages_es import MESSAGES_ES
from nvidia_vbios.gui.presentation import (SECTION_NAMES, dependency_reason, field_label, field_section,
                                           read_only_reason, section_order, unsupported_notes, value_text)
from nvidia_vbios.rom import from_bytes, inspect_image, load, VbiosError
from nvidia_vbios.rom.image import backend
from test_extended_fields import changed_bytes_within, custom_registry, descriptors, repair_fixture, set_device
from test_rom_formats import synthetic_blackwell

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
        # The notebook enables entries 0..2; a stored Off reads 0 and Stock enables exactly those.
        notebook = fixture(device=0x2C59, mutate=set_gr_rail_gating(0xFE, 0xFE, 0xFE))
        field = descriptors(notebook)['lpwr_gr_rail_gating']
        self.assertEqual((field['current'], field['lpwr_entries']), (0, [0, 1, 2]))
        stock = edit(notebook, {'lpwr_gr_rail_gating': 1})
        at = lpwr_entry(backend(notebook), 'gr_rg', 0)['offset']
        self.assertEqual(stock.blob[at:at + 5], bytes((0xFF, 0xFF, 0xFF, 0xFC, 0xFC)))
        # Another product with an enabled entry: read-only, with its idle time.
        fields = descriptors(fixture(device=0x2C02, mutate=set_gr_rail_gating(0xFF)))
        self.assertEqual((fields['lpwr_gr_rail_gating']['editable'], fields['lpwr_gr_rail_gating']['reason']),
                         (False, LPWR_GR_RG_UNREVIEWED_REASON))
        self.assertEqual((fields['lpwr_gr_rail_gating_idle_us']['editable'],
                          fields['lpwr_gr_rail_gating_idle_us']['reason']), (False, LPWR_TIME_SWITCH_REASON))
        # A reviewed product whose entry stores another value: read-only.
        field = descriptors(fixture(device=0x2C33, mutate=set_gr_rail_gating(0x7F)))['lpwr_gr_rail_gating']
        self.assertEqual((field['editable'], field['reason']), (False, LPWR_GR_RG_UNRECOGNIZED_REASON))

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
                       LPWR_GR_RG_UNREVIEWED_REASON, LPWR_GR_RG_UNRECOGNIZED_REASON, LPWR_TIME_SWITCH_REASON):
            with self.subTest(reason=reason):
                english, spanish = (read_only_reason(dict(reason=reason), lang) for lang in ('en', 'es'))
                self.assertTrue(english and spanish and english != spanish)
                self.assertNotEqual(spanish, read_only_reason(dict(reason='unmapped'), 'es'))
        for key in ('section.advanced', 'section.advanced_note', 'section.advanced_perf', 'section.advanced_lpwr',
                    'error.DEPENDENT_FIELD_DISABLED', 'flag_stock'):
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


if __name__ == '__main__':
    unittest.main()
