"""Ada editable fields: generated images, and reference ROMs where they are available."""
from decimal import Decimal
import os
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nvidia_vbios.editor import edit, plan
from nvidia_vbios.editor.registry import registry
from nvidia_vbios.rom import VbiosError, from_bytes, inspect_image, load
from nvidia_vbios.rom.image import backend
from test_extended_fields import changed_bytes_within, curve_step, custom_registry, descriptors
from test_rom_formats import synthetic_blackwell, synthetic_rom

GV_HAL = ['GPC', 'XBAR', 'DRAM', 'SYS', 'HUB', 'VID', 'PWR', 'DISP', 'PCIEGEN', 'HOST']


def patched(blob, at, data):
    """Write data at the same place in every duplicate chain and repair the image checksums."""
    blob = bytearray(blob)
    parser = backend(from_bytes(bytes(blob)))
    for copy in parser.copy_offsets(at, len(data)):
        blob[copy:copy + len(data)] = data
    for start, end in parser.image_regions:
        blob[end - 1] = (blob[end - 1] - sum(blob[start:end])) & 255
    return bytes(blob)


def messages(image):
    return [d.get('message', '') for d in inspect_image(image)['diagnostics']]


def fan_limits(channels, sides=('min_rpm', 'max_rpm', 'min_pct', 'max_pct')):
    """Per-channel fan limit keys, by default all four of each channel."""
    return [f'fan_{n}_{side}' for n in range(1, channels + 1) for side in sides]


def fan_curves(channels, extras, skip=()):
    """Curve point keys of the channel curves and the extra curves, except those in skip."""
    owners = [f'fan_{n}' for n in range(1, channels + 1)] + [f'fan_extra_{m}' for m in range(1, extras + 1)]
    return [key for owner in owners for k in (1, 2, 3) for unit in ('temp_c', 'rpm', 'pct')
            if (key := f'{owner}_curve_{k}_{unit}') not in skip]


class AdaPowerTests(unittest.TestCase):
    def test_every_power_variant_writes_the_tgp_row_in_both_chains(self):
        for variant in (0x53, 0x5B, 0x4B):
            with self.subTest(variant=variant):
                image = from_bytes(synthetic_rom(copies=2, power_variant=variant))
                parser = backend(image)
                tgp = parser.power_rows()[parser.tgp_index]
                result = edit(image, {'power_max_w': 100, 'power_default_w': 80, 'power_min_w': 20})
                self.assertTrue(result.manifest['integrity']['valid'])
                changed_bytes_within(self, image, result, [at for o in (2, 6, 10)
                                                           for at in parser.copy_offsets(tgp['offset'] + o, 4)])
                row = backend(result.image).power_rows()[2]
                self.assertEqual((row['minimum_raw'], row['default_raw'], row['maximum_raw']), (20000, 80000, 100000))
                self.assertEqual(edit(result.image, {'power_max_w': 70, 'power_default_w': 70,
                                                     'power_min_w': 30}).blob, image.blob)

    def test_reference_identity_keeps_reviewed_status_and_other_boards_are_experimental(self):
        reference = descriptors(from_bytes(synthetic_rom()))
        other = descriptors(from_bytes(synthetic_rom(version=b'95.07.47.00.20')))
        for key in ('power_max_w', 'power_min_w', 'nvvdd_rel_max_mv', 'nvvdd_rel_equation_max_mv'):
            with self.subTest(key=key):
                self.assertNotIn('experimental', reference[key])
                self.assertTrue(other[key]['experimental'] and other[key]['editable'])
                self.assertTrue(other[key]['reason'].startswith('experimental:'))
        self.assertTrue(reference['power_default_w']['experimental'])

    def test_notebook_header_names_row_2(self):
        image = from_bytes(synthetic_rom(copies=2, notebook=True))
        fields = descriptors(image)
        self.assertEqual([fields[k]['current'] for k in ('power_min_w', 'power_default_w', 'power_max_w')], [30, 70, 70])
        self.assertTrue(fields['power_max_w']['experimental'])
        self.assertIn('notebook', fields['power_max_w']['reason'])
        self.assertEqual(backend(edit(image, {'power_max_w': 90}).image).power_rows()[2]['maximum_raw'], 90000)

    def test_tgp_identity_gates(self):
        blob = synthetic_rom(copies=2)
        parser = backend(from_bytes(blob))
        table, row = parser.pointer('P', 0x2C), parser.power_rows()[2]['offset']
        cases = ((parser.pointer('P', 0x3C) + 7, b'\xf6', 'total board power channel'),
                 (row + 1, b'\x01', 'total board power channel'),
                 (row, b'\x11', 'unknown identity, units'),
                 (table + 10, b'\xff', 'TGP policy index exceeds'),
                 (table + 2, b'\x5a', 'unvalidated 3x power table variant'))
        for at, data, message in cases:
            with self.subTest(message=message, at=at):
                image = from_bytes(patched(blob, at, data))
                self.assertTrue(inspect_image(image)['integrity']['valid'])
                self.assertNotIn('power_max_w', descriptors(image))
                self.assertTrue(any(message in m for m in messages(image)), messages(image))
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {'power_max_w': 90})
                self.assertEqual(exc.exception.code, 'UNKNOWN_FIELD')

    def test_unpadded_data_image_keeps_fields_read_only(self):
        blob = bytearray(synthetic_rom(copies=2))
        parser = backend(from_bytes(bytes(blob)))
        image_end = parser.owner(parser.pointer('P', 0x2C), 1)['end']
        image = from_bytes(patched(blob, image_end - 8, b'\x00'))
        self.assertTrue(inspect_image(image)['integrity']['valid'])
        self.assertFalse(any(f['editable'] for f in inspect_image(image)['fields']))
        self.assertTrue(any('checksum padding' in m for m in messages(image)))


class AdaShortPowerTableTests(unittest.TestCase):
    """30/2c/4b: rows are matched as the 0x53 rows they truncate; other header/entry pairs stay refused."""

    def test_truncated_rows_match_the_same_policies_and_a_changed_byte_does_not(self):
        full = backend(from_bytes(synthetic_rom(copies=2, policies=True, power_variant=0x53)))
        short_blob = synthetic_rom(copies=2, policies=True, power_variant=0x4B)
        short = backend(from_bytes(short_blob))
        self.assertEqual(short.power_entry_size if short.power_rows() else None, 0x4B)
        for role in ('slot_power', 'slot_current', 'input_current_0', 'input_current_1', 'nvvdd_power',
                     'nvvdd_current'):
            with self.subTest(role=role):
                found, reference = short.ada_policy(role), full.ada_policy(role)
                self.assertIsNotNone(found)
                self.assertEqual((found['vbios_row_index'], found['immutable_row_sha256']),
                                 (reference['vbios_row_index'], reference['immutable_row_sha256']))
        row = short.ada_policy('slot_power')['offset']
        for at in (14, 41, 0x4A):
            changed = bytearray(short_blob)
            for copy in short.copy_offsets(row + at, 1):
                changed[copy] ^= 0x40
            with self.subTest(byte=at):
                self.assertIsNone(backend(from_bytes(bytes(changed))).ada_policy('slot_power'))

    def test_other_header_and_entry_pairs_are_refused(self):
        for header, entry in ((0x2C, 0x53), (0x34, 0x4B), (0x32, 0x4B)):
            blob = bytearray(synthetic_rom(power_variant=0x4B))
            parser = backend(from_bytes(bytes(blob)))
            at = parser.pointer('P', 0x2C)
            blob[at + 1:at + 3] = bytes((header, entry))
            with self.subTest(header=header, entry=entry), self.assertRaisesRegex(Exception, 'unvalidated 3x power'):
                backend(from_bytes(bytes(blob))).power_rows()


class AdaPolicyTests(unittest.TestCase):
    def setUp(self):
        self.blob = synthetic_rom(copies=2, policies=True)
        self.image = from_bytes(self.blob)
        self.parser = backend(self.image)
        self.rows = self.parser.power_rows()

    def test_policy_rows_by_shape_and_channel(self):
        fields = descriptors(self.image)
        expected = {'slot_power_rated_w': 66, 'slot_power_max_w': 66, 'slot_current_threshold_rated_ma': 8250,
                    'slot_current_threshold_max_ma': 8250, 'input_current_rated_ma': 30000,
                    'input_current_max_ma': 30000, 'nvvdd_power_threshold_rated_w': 125.983,
                    'nvvdd_power_threshold_max_w': 125.983}
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertEqual(fields[key]['current'], value)
                self.assertTrue(fields[key]['editable'] and fields[key]['experimental'])
                # Class-5 hardware thresholds (slot current, 12 V input, NVVDD power) are opt-in.
                threshold = 'threshold' in key or key.startswith('input_current')
                self.assertEqual(fields[key].get('opt_in', False), threshold)
                self.assertEqual(fields[key].get('policy_class'), 'hardware-threshold' if threshold else None)
                self.assertNotIn('same_channel_rows', fields[key])
        self.assertEqual(fields['input_current_rated_ma']['policy_indices'], [9, 10])
        self.assertEqual(fields['slot_power_rated_w']['bounds'], dict(fields['slot_power_rated_w']['bounds'],
                                                                      minimum=1, maximum=66))
        ocp = fields['nvvdd_output_ocp_max_ma']
        self.assertEqual((ocp['current'], ocp['editable']), (108000, False))
        self.assertIn('unproven', ocp['reason'])

    def test_policy_edits_write_their_rows_in_both_chains(self):
        changes = {'slot_power_max_w': 80, 'slot_power_rated_w': 75, 'input_current_max_ma': 35000,
                   'input_current_rated_ma': 32000, 'slot_current_threshold_max_ma': 9000,
                   'slot_current_threshold_rated_ma': 8500, 'nvvdd_power_threshold_max_w': 150,
                   'nvvdd_power_threshold_rated_w': 140}
        result = edit(self.image, changes)
        self.assertTrue(result.manifest['integrity']['valid'])
        expected = {5: (75000, 80000), 8: (8500, 9000), 9: (32000, 35000), 10: (32000, 35000), 16: (140000, 150000)}
        for index, (before, after) in enumerate(zip(self.rows, backend(result.image).power_rows())):
            if index in expected:
                self.assertEqual((after['default_raw'], after['maximum_raw']), expected[index])
                self.assertEqual(after['minimum_raw'], before['minimum_raw'])
            else:
                self.assertEqual(after, before)
        changed_bytes_within(self, self.image, result, [at for i in expected for o in (6, 10)
                                                        for at in self.parser.copy_offsets(self.rows[i]['offset'] + o, 4)])
        self.assertEqual(result.manifest['preservation']['changed_rated_defaults'],
                         sorted(k for k in changes if 'rated' in k))
        original = {key: descriptors(self.image)[key]['current'] for key in changes}
        self.assertEqual(edit(result.image, original).blob, self.image.blob)

    def test_joint_order_and_rated_exceptions_are_enforced(self):
        for changes in ({'slot_power_rated_w': 90}, {'slot_power_rated_w': 90, 'slot_power_max_w': 80},
                        {'input_current_rated_ma': 31000}, {'nvvdd_power_threshold_max_w': 100}):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(self.image, changes)
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        # A rated exception covers only its own rows, not the NVVDD current row.
        from nvidia_vbios.editor.registry import slot_power
        other = tuple(self.parser.copy_offsets(self.rows[13]['offset'] + 6, 4))
        with self.assertRaises(VbiosError) as exc:
            edit(self.image, {'slot_power_rated_w': 60, 'alias': 100},
                 field_registry=custom_registry('alias', other, include=(slot_power,)))
        self.assertEqual(exc.exception.code, 'FACTORY_DEFAULT_CHANGED')

    def test_shape_channel_and_equal_thresholds_gate_the_fields(self):
        slot, channels = self.rows[5]['offset'], self.parser.pointer('P', 0x3C) + 6
        cases = (('parameter byte', slot + 20, b'\x01', ('slot_power_rated_w',), ('slot_current_threshold_rated_ma',)),
                 ('slot channel', channels + 26 * 4 + 1, b'\xfe', ('slot_power_rated_w', 'slot_current_threshold_rated_ma'),
                  ('input_current_rated_ma',)),
                 ('second slot shape', self.rows[7]['offset'], bytes((4, 4)), ('slot_power_rated_w',),
                  ('slot_current_threshold_rated_ma',)),
                 ('extended entry bytes', slot + 0x53, b'\x01', ('slot_power_rated_w',), ('input_current_rated_ma',)))
        for name, at, data, absent, present in cases:
            with self.subTest(case=name):
                blob = self.blob
                if name == 'second slot shape':
                    blob = patched(blob, at + 41, b'\x01')
                fields = descriptors(from_bytes(patched(blob, at, data)))
                for key in absent:
                    self.assertNotIn(key, fields)
                for key in present:
                    self.assertTrue(fields[key]['editable'])
        fields = descriptors(from_bytes(patched(self.blob, self.rows[10]['offset'] + 10, struct.pack('<I', 31000))))
        self.assertIsNone(fields['input_current_max_ma']['current'])
        self.assertFalse(fields['input_current_max_ma']['editable'])
        self.assertIn('different values', fields['input_current_max_ma']['reason'])
        self.assertEqual((fields['input_current_rated_ma']['current'], fields['input_current_rated_ma']['bounds']['maximum']),
                         (30000, 30000))

    def test_second_row_of_the_same_class_on_the_channel_keeps_both_values_read_only(self):
        # Row 17 as the RTX 4060 stores it: class 5 mW on the NVVDD power channel 18,
        # parameter byte 0 = 4, another shape, 1/100/100 W.
        at = self.rows[17]['offset']
        blob = patched(self.blob, at, bytes((0x05, 0x12)) + struct.pack('<III', 1000, 100000, 100000))
        image = from_bytes(patched(blob, at + 14, b'\x04'))
        fields = descriptors(image)
        for key in ('nvvdd_power_threshold_max_w', 'nvvdd_power_threshold_rated_w'):
            with self.subTest(key=key):
                field = fields[key]
                self.assertEqual((field['current'], field['editable']), (125.983, False))
                self.assertEqual(field['same_channel_rows'], [{'row': 17, 'parameter_byte_0': 4, 'minimum': 1000,
                                                               'rated': 100000, 'maximum': 100000, 'units': 'mW'}])
                self.assertIn('row 17 (parameter byte 0 = 4, rated 100 W, maximum 100 W) is another hardware '
                              'threshold', field['reason'])
                with self.assertRaises(VbiosError):
                    edit(image, {key: 130})
        # The other policies keep their fields; a class-5 mA row would not block the mW threshold.
        self.assertTrue(fields['slot_current_threshold_rated_ma']['editable'])
        self.assertTrue(fields['input_current_rated_ma']['editable'])
        other_unit = descriptors(from_bytes(patched(blob, at, b'\x15')))
        self.assertTrue(other_unit['nvvdd_power_threshold_rated_w']['editable'])

    def test_undecoded_profiles_keep_policy_fields_read_only(self):
        image = from_bytes(patched(self.blob, self.parser.pointer('P', 0xF4) + 0xFE, b'\x01'))
        fields = descriptors(image)
        self.assertNotIn('power_max_w', fields)
        changes = {'slot_power_rated_w': 60, 'input_current_rated_ma': 29000, 'nvvdd_power_threshold_rated_w': 120,
                   'slot_current_threshold_max_ma': 9000}
        for key, value in changes.items():
            with self.subTest(key=key):
                field = fields[key]
                self.assertIsNotNone(field['current'])
                self.assertFalse(field['editable'])
                self.assertIn('override profiles do not decode', field['reason'])
                with self.assertRaises(VbiosError):
                    edit(image, {key: value})

    def test_ada_input_thresholds_use_threshold_labels_and_blackwell_keeps_limit(self):
        from nvidia_vbios.gui.presentation import field_label
        ada_fields = descriptors(self.image)
        blackwell = {'key': 'input_current_rated_ma'}
        self.assertEqual(field_label(ada_fields['input_current_rated_ma']),
                         '12 V input current threshold, rated (advanced, experimental)')
        self.assertEqual(field_label(ada_fields['input_current_max_ma'], 'es'),
                         'Techo del umbral de corriente de entrada de 12 V (avanzado, experimental)')
        self.assertEqual(field_label(blackwell), '12 V input current limit, rated (experimental)')

    def test_ampere_and_blackwell_offer_no_ada_policy_fields(self):
        for blob in (synthetic_rom(family='ampere'), synthetic_blackwell()):
            fields = descriptors(from_bytes(blob))
            self.assertFalse(any('threshold' in key for key in fields))
            self.assertFalse(any('equation_kind' in f and f['editable'] for f in fields.values()))


class AdaVoltageTests(unittest.TestCase):
    def test_temperature_derated_rel_and_alt_take_ceiling_edits(self):
        image = from_bytes(synthetic_rom(copies=2, alt=True))
        parser = backend(image)
        fields = descriptors(image)
        alt = fields['nvvdd_alt_equation_max_mv']
        self.assertEqual((alt['current'], alt['editable'], alt['experimental'], alt['equation_kind']),
                         (975, True, True, 'temperature-derated'))
        self.assertEqual((fields['nvvdd_vmin_selector_index']['current'], fields['nvvdd_ov_selector_index']['current']), (4, 5))
        roles = {r['role']: r for r in parser.rail_equations()}
        result = edit(image, {'nvvdd_rel_equation_max_mv': 1000, 'nvvdd_alt_equation_max_mv': 1020})
        changed_bytes_within(self, image, result, [at for role in ('REL', 'ALT')
                                                   for at in parser.copy_offsets(roles[role]['maximum_offset'], 4)])
        after = {r['role']: r for r in backend(result.image).rail_equations()}
        self.assertEqual((after['REL']['output_maximum_uv'], after['ALT']['output_maximum_uv']), (1000000, 1020000))
        self.assertEqual(edit(result.image, {'nvvdd_rel_equation_max_mv': 955, 'nvvdd_alt_equation_max_mv': 975}).blob,
                         image.blob)

    def test_other_equation_kinds_stay_read_only(self):
        for rel, kind, reason in (('constant', 'constant', 'constant equation'), ('compare', 'compare', 'compare expression'),
                                  ('chained', 'chained', 'temperature-derated form'),
                                  ('shared', 'shared', 'temperature-derated form')):
            with self.subTest(rel=rel):
                image = from_bytes(synthetic_rom(copies=2, rel=rel))
                fields = descriptors(image)
                role = fields['nvvdd_rel_equation_max_mv']
                self.assertFalse(role['editable'])
                self.assertEqual(role['equation_kind'], kind)
                self.assertIn(reason, role['reason'])
                if rel == 'compare':
                    self.assertIsNone(role['current'])
                    self.assertNotIn('nvvdd_rel_max_mv', fields)
                    self.assertTrue(any('compare expression' in m for m in messages(image)))
                else:
                    self.assertFalse(fields['nvvdd_rel_max_mv']['editable'])
                for key in ('nvvdd_rel_equation_max_mv', 'nvvdd_rel_max_mv'):
                    with self.assertRaises(VbiosError) as exc:
                        edit(image, {key: 1000})
                    self.assertIn(exc.exception.code, ('FIELD_READ_ONLY', 'UNKNOWN_FIELD'))

    def test_selector_order_and_equation_count_gate_the_rail(self):
        blob = synthetic_rom(copies=2)
        parser = backend(from_bytes(blob))
        row, vfe = parser.pointer('P', 0x68) + 5, parser.pointer('P', 0x20)
        for name, at, data in (('VMIN', row + 11, b'\x02'), ('OV', row + 6, b'\x09'), ('ALT', row + 5, b'\x04'),
                               ('count', vfe + 5, b'\x00')):
            with self.subTest(selector=name):
                image = from_bytes(patched(blob, at, data))
                fields = descriptors(image)
                self.assertNotIn('nvvdd_rel_max_mv', fields)
                self.assertNotIn('nvvdd_rel_equation_max_mv', fields)
                self.assertTrue(any('unvalidated Ada rail selectors' in m or 'no equations' in m for m in messages(image)))


class AdaClockTests(unittest.TestCase):
    def test_rows_are_named_by_gv_hal_position_and_both_chains_are_written(self):
        image = from_bytes(synthetic_rom(copies=2))
        parser = backend(image)
        rows = parser.clock_ranges()
        self.assertEqual([r['domain'] for r in rows], GV_HAL)
        fields = descriptors(image)
        for key, value in {'gpc_offset_max_mhz': 3000, 'gpc_offset_min_mhz': -1000, 'memory_offset_max_mhz': 6000,
                           'memory_offset_min_mhz': -2000, 'dram_max_table_mhz': 3000, 'xbar_max_table_mhz': 3000,
                           'sys_min_table_mhz': -1000, 'vid_max_table_mhz': 3000}.items():
            with self.subTest(key=key):
                self.assertEqual(fields[key]['current'], value)
                self.assertTrue(fields[key]['editable'] and fields[key]['experimental'])
        changes = {'gpc_offset_max_mhz': 1500, 'memory_offset_min_mhz': -5000, 'sys_max_table_mhz': 2000,
                   'vid_min_table_mhz': -1500, 'memory_offset_max_mhz': 8000}
        result = edit(image, changes)
        after = {r['domain']: (r['minimum_mhz'], r['maximum_mhz']) for r in backend(result.image).clock_ranges()}
        self.assertEqual((after['GPC'], after['DRAM'], after['SYS'], after['VID'], after['XBAR']),
                         ((-1000, 1500), (-2500, 4000), (-1000, 2000), (-1500, 3000), (-1000, 3000)))
        named = {r['domain']: r for r in rows}
        offsets = [named['GPC']['maximum_offset'], named['DRAM']['minimum_offset'], named['SYS']['maximum_offset'],
                   named['VID']['minimum_offset'], named['DRAM']['maximum_offset']]
        changed_bytes_within(self, image, result, [at for o in offsets for at in parser.copy_offsets(o, 2)], width=2)
        self.assertEqual(edit(result.image, {'gpc_offset_max_mhz': 3000, 'memory_offset_min_mhz': -2000,
                                             'sys_max_table_mhz': 3000, 'vid_min_table_mhz': -1000,
                                             'memory_offset_max_mhz': 6000}).blob, image.blob)
        for changes, code in (({'memory_offset_min_mhz': -4001}, 'UNREPRESENTABLE_VALUE'),
                              ({'gpc_offset_max_mhz': -1}, 'OUT_OF_BOUNDS'),
                              ({'memory_offset_max_mhz': 7000, 'dram_max_table_mhz': 3500}, 'CONFLICTING_FIELDS')):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes)
            self.assertEqual(exc.exception.code, code)

    def test_shifted_programming_indices_keep_positions_and_gates_refuse_other_rows(self):
        blob = synthetic_rom(copies=2)
        parser = backend(from_bytes(blob))
        rows = parser.clock_ranges()
        shifted = blob
        for row in rows:  # the RTX 4080 Laptop image numbers its programming entries from 1
            at = row['minimum_offset'] - 3
            first, last = blob[at + 1:at + 3]
            shifted = patched(shifted, at + 1, bytes((first + 1, last + 1)))
            if blob[at + 15] == 1 and blob[at] == 1:
                shifted = patched(shifted, at + 16, bytes((first + 1, last + 1)))
        self.assertEqual([r['domain'] for r in backend(from_bytes(shifted)).clock_ranges()], GV_HAL)
        sys_row = rows[3]['minimum_offset'] - 3
        for name, at, data in (('ordering', sys_row + 7, b'\x45'), ('usage', sys_row, b'\x00'),
                               ('rail type', sys_row + 15, b'\x01'), ('fixed bytes', sys_row + 9, b'\x00'),
                               ('header', parser.pointer('C', 8) + 6, b'\x02')):
            with self.subTest(gate=name):
                image = from_bytes(patched(blob, at, data))
                fields = descriptors(image)
                self.assertNotIn('gpc_offset_max_mhz', fields)
                self.assertFalse(fields['memory_offset_max_mhz']['editable'])
                self.assertTrue(any('GV HAL' in m or 'clock table variant' in m for m in messages(image)))


class AdaFanTests(unittest.TestCase):
    def test_two_channels_round_trip_in_both_chains(self):
        image = from_bytes(synthetic_rom(copies=2, fans=2))
        fields = descriptors(image)
        channels, pwm = fields['fan_channels'], fields['fan_pwm_frequency_hz']
        self.assertEqual((channels['current'], channels['bounds']['minimum'], channels['bounds']['maximum']), (2, 1, 2))
        self.assertTrue(channels['editable'] and channels['experimental'] and pwm['editable'])
        self.assertEqual(pwm['current'], 27000)
        lowered = edit(image, {'fan_channels': 1})
        self.assertEqual(backend(lowered.image).fan_coolers()['channels'], [0])
        bindings = {b.descriptor['key']: b for b in registry.bindings(image, backend(image))[0]}
        changed_bytes_within(self, image, lowered, bindings['fan_channels'].offsets, width=1)
        self.assertEqual(len(bindings['fan_channels'].offsets), 2 * (2 + 5 * 2))
        self.assertEqual(edit(lowered.image, {'fan_channels': 2}).blob, image.blob)
        slower = edit(image, {'fan_pwm_frequency_hz': 25000})
        changed_bytes_within(self, image, slower, bindings['fan_pwm_frequency_hz'].offsets, width=2)
        self.assertEqual({r['pwm_frequency_hz'] for r in backend(slower.image).fan_coolers()['rows']}, {25000})
        self.assertEqual(edit(slower.image, {'fan_pwm_frequency_hz': 27000}).blob, image.blob)

    def test_channel_layouts_laptops_and_guard(self):
        one = descriptors(from_bytes(synthetic_rom(copies=2, fans=1)))
        self.assertFalse(one['fan_channels']['editable'])
        self.assertTrue(one['fan_pwm_frequency_hz']['editable'])
        stored = from_bytes(synthetic_rom(copies=2, fans=3))
        self.assertEqual(descriptors(stored)['fan_channels']['bounds']['maximum'], 2)
        raised = edit(stored, {'fan_channels': 2})
        self.assertEqual(backend(raised.image).fan_coolers()['channels'], [0, 1])
        self.assertEqual(edit(raised.image, {'fan_channels': 1}).blob, stored.blob)
        laptop = descriptors(from_bytes(synthetic_rom(copies=2, fans=-1)))
        self.assertFalse(any(key.startswith('fan_') for key in laptop))
        parser = backend(stored)
        control = parser.fan_coolers()['rows'][1]['control_offset'] + 5
        with self.assertRaises(VbiosError) as exc:
            edit(stored, {'probe': 7}, field_registry=custom_registry('probe', tuple(parser.copy_offsets(control, 1)),
                                                                       encoding='<B', scale=1))
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')

    def test_channel_limits_write_both_chains_and_revert(self):
        image = from_bytes(synthetic_rom(copies=2, fans=2))
        parser = backend(image)
        bindings = {b.descriptor['key']: b for b in registry.bindings(image, parser)[0]}
        rows = [r['offset'] for r in parser.fan_coolers()['rows']]
        fields = descriptors(image)
        self.assertEqual([(fields[k]['current'], fields[k]['editable']) for k in
                          ('fan_2_min_rpm', 'fan_2_max_rpm', 'fan_2_min_pct', 'fan_2_max_pct')],
                         [(1000, True), (3300, True), (20, True), (100, True)])
        for key, at, width, value in (('fan_1_min_rpm', rows[0] + 14, 2, 900), ('fan_2_max_rpm', rows[1] + 16, 2, 3500),
                                      ('fan_1_min_pct', rows[0] + 2, 1, 15)):
            with self.subTest(key=key):
                offsets = bindings[key].offsets
                self.assertEqual(offsets, tuple(parser.copy_offsets(at, width)))
                self.assertEqual(len(offsets), 2)
                result = edit(image, {key: value})
                changed_bytes_within(self, image, result, offsets, width=width)
                self.assertEqual({struct.unpack_from(bindings[key].encoding, result.blob, o)[0] for o in offsets}, {value})
                self.assertEqual(edit(result.image, {key: fields[key]['current']}).blob, image.blob)

    def test_an_extra_curve_above_a_channel_maximum_keeps_that_maximum_read_only(self):
        # As on the RTX 4080 Super: channel 2 and its own curve top out at 3000 RPM, the extra curve at 3300.
        # Entry 3 is disabled, so entry 2 alone (the only extra one on the RTX 4060 and 4060 Ti) has to stop it.
        image = from_bytes(synthetic_rom(copies=2, fans=2))
        row = backend(image).fan_coolers()['rows'][1]
        blob = patched(patched(image.blob, row['offset'] + 16, struct.pack('<H', 3000)),
                       row['policy_offset'] + 28, struct.pack('<H', 3000))
        blob = patched(blob, row['policy_offset'] + 2 * 0x33, b'\x00')
        self.assertEqual([c['index'] for c in backend(from_bytes(blob)).fan_coolers()['extra_curves']], [2])
        fields = descriptors(from_bytes(blob))
        self.assertFalse(fields['fan_2_max_rpm']['editable'])
        self.assertEqual(fields['fan_2_max_rpm']['reason'], 'fan row or policy curves hold values outside the reviewed shape')
        self.assertEqual((fields['fan_2_max_rpm']['bounds']['minimum'], fields['fan_2_max_rpm']['bounds']['maximum']),
                         (3300, 32767))
        self.assertTrue(fields['fan_2_min_rpm']['editable'] and fields['fan_1_max_rpm']['editable'])

    def test_curve_points_write_both_chains_and_move_with_the_maximum(self):
        image = from_bytes(synthetic_rom(copies=2, fans=2))
        parser = backend(image)
        table = parser.fan_coolers()
        bindings = {b.descriptor['key']: b for b in registry.bindings(image, parser)[0]}
        fields = descriptors(image)
        # Channel curves 55/70/85 C, extra curves (entries 2 and 3) 98/103/108 and 92/97/102 C, 1000/2000/3300 RPM.
        self.assertEqual([fields[k]['current'] for k in ('fan_2_curve_2_temp_c', 'fan_extra_1_curve_3_temp_c',
                                                         'fan_extra_2_curve_1_temp_c', 'fan_extra_2_curve_3_rpm')],
                         [70, 108, 92, 3300])
        self.assertEqual(sum(1 for k, f in fields.items() if '_curve_' in k and f['editable']), 4 * 9)
        self.assertEqual(bindings['fan_extra_2_curve_3_rpm'].offsets,
                         tuple(parser.copy_offsets(table['extra_curves'][1]['policy_offset'] + 28, 2)))
        top = ['fan_1_max_rpm', 'fan_1_curve_3_rpm', 'fan_extra_1_curve_3_rpm', 'fan_extra_2_curve_3_rpm']
        lowered = edit(image, {key: 3000 for key in top})
        offsets = [o for key in top for o in bindings[key].offsets]
        self.assertEqual(len(offsets), 2 * len(top))
        changed_bytes_within(self, image, lowered, offsets, width=2)
        self.assertEqual({struct.unpack_from('<H', lowered.blob, o)[0] for o in offsets}, {3000})
        self.assertEqual(edit(lowered.image, {key: 3300 for key in top}).blob, image.blob)
        # Without the extra curves, or below the speed value (2295 RPM), the maximum stays.
        for changes in ({key: 3000 for key in top[:2]}, {key: 2200 for key in top}):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes)
            self.assertEqual((exc.exception.code, exc.exception.details['field']), ('OUT_OF_BOUNDS', 'fan_1_max_rpm'))
        warmer = edit(image, {'fan_2_curve_1_temp_c': '55.5'})
        changed_bytes_within(self, image, warmer, bindings['fan_2_curve_1_temp_c'].offsets, width=2)
        self.assertEqual({struct.unpack_from('<H', warmer.blob, o)[0] for o in bindings['fan_2_curve_1_temp_c'].offsets},
                         {1776})


if __name__ == '__main__':
    unittest.main()
