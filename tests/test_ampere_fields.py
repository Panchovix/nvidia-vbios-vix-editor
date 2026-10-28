"""Ampere (GA10x) fields: generated images, and reference ROMs where they are available."""
from decimal import Decimal
import os
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nvidia_vbios.editor import edit, plan
from nvidia_vbios.editor.registry import (FAN_LOW_EXTRA_CHANNELS_REASON, FAN_POLICY_COPY_CHANNELS_REASON,
                                          FAN_ZERO_RPM_NO_BLOCK_REASON, fan_layouts, registry)
from nvidia_vbios.rom import VbiosError, from_bytes, inspect_image, load
from nvidia_vbios.rom.image import backend
from test_ada_fields import (GV_HAL, REFERENCE_BLOCK, checked_elsewhere, dram_points, fan_curves, fan_limits, messages,
                             patched, with_low_extra, with_policy_copy, with_zero_rpm, zero_rpm_temps)
from test_extended_fields import changed_bytes_within, curve_step, descriptors, fan_stop_refusals
from test_rom_formats import synthetic_rom

POWER = ['power_max_w', 'power_default_w', 'power_min_w']
SLOT = ['slot_power_max_w', 'slot_power_rated_w']
INPUT = ['input_current_max_ma', 'input_current_rated_ma']
SLOT_CURRENT = ['slot_current_threshold_max_ma', 'slot_current_threshold_rated_ma']
CLOCKS = ['dram_max_table_mhz', 'memory_offset_max_mhz', 'memory_offset_min_mhz', 'dram_min_table_mhz',
          'gpc_offset_max_mhz', 'gpc_offset_min_mhz', 'xbar_max_table_mhz', 'xbar_min_table_mhz', 'sys_max_table_mhz',
          'sys_min_table_mhz', 'vid_max_table_mhz', 'vid_min_table_mhz']
FANS = ['fan_channels', 'fan_pwm_frequency_hz']


def connectors(count):
    return [f'connector_{n}_power_{side}_w' for n in range(1, count + 1) for side in ('max', 'rated')]


CONNECTOR_SUM = ['connector_sum_power_max_w', 'connector_sum_power_rated_w']


def connector_sum(blob, members=(5, 6), weight=0x1000, rows=(11,)):
    """Channel 16 as a class-2 sum (rail 0xe4, the 12 V bytes of a connector channel) of relationship entries 1..
    (members, each with weight; 0x1000 = 1.0) and each of rows a class-4 mW row on it at 280 W."""
    parser = backend(from_bytes(blob))
    table = parser.pointer('P', 0x3C)
    relationships = table + 6 + 22 * 32
    blob = patched(blob, table + 6 + 22 * 16, bytes.fromhex('02 e4 00 1b b7 00 00 10') + bytes(6) +
                   bytes((1, len(members))))
    for entry, channel in enumerate(members, 1):
        blob = patched(blob, relationships + 46 * entry, bytes((1, channel)) + struct.pack('<I', weight))
    for row in rows:
        blob = patched(blob, parser.power_rows()[row]['offset'],
                       bytes((0x04, 16)) + struct.pack('<III', 1000, 280000, 280000))
    return blob


def connector_currents(count):
    return [f'connector_{n}_current_threshold_{side}_ma' for n in range(1, count + 1) for side in ('max', 'rated')]


NVVDD_OCP = ['nvvdd_output_ocp_max_ma', 'nvvdd_output_ocp_rated_ma']


def nvvdd_rows(blob, row18=(1, 5001000, 5001000), row18_class=0x10):
    """The NVVDD rows of the RTX 3050 Ti Laptop GPU stock image on a synthetic Ampere image (policies=True): channel
    18 as the other NVVDD channel (sensor byte 14 = 5), rows 16 and 17 on it (class 5 mW, 18.75 and 12.5 W; row 17
    with parameter byte 0 = 7), and on the NVVDD current channel 19 row 12 (class 1 mA, 5001 A) and row 18 (row18
    limits, class 0 mA by default: the 5001 A no-limit row)."""
    parser = backend(from_bytes(blob))
    table, rows = parser.pointer('P', 0x3C), parser.power_rows()
    blob = patched(blob, table + 6 + 22 * 18, bytes.fromhex('01 01 00 1b b7 00 00 10 00 00 00 00 00 00 05 02'))
    for row, data in ((12, bytes((0x11, 19)) + struct.pack('<III', 1000, 5001000, 5001000)),
                      (16, bytes((0x05, 18)) + struct.pack('<III', 1000, 18750, 18750)),
                      (17, bytes((0x05, 18)) + struct.pack('<III', 1, 12500, 12500) + b'\x07'),
                      (18, bytes((row18_class, 19)) + struct.pack('<III', *row18) + b'\x01')):
        blob = patched(blob, rows[row]['offset'], data)
    return blob


def with_connector_current(blob, channel=5, threshold=1):
    """Row 9 of a synthetic Ampere image (policies=True) as a class-5 mA current threshold on a power channel."""
    row = backend(from_bytes(blob)).power_rows()[9]['offset']
    blob = patched(blob, row, bytes((0x15, channel)) + struct.pack('<III', 1000, 16000, 19200))
    return patched(blob, row + 14, bytes((threshold,)))


def recomputed(blob):
    """Repair the additive checksum of every image of every chain after a raw patch."""
    blob = bytearray(blob)
    for start, end in backend(from_bytes(bytes(blob))).image_regions:
        blob[end - 1] = (blob[end - 1] - sum(blob[start:end])) & 255
    return bytes(blob)


def assert_written(test, image, result, changes):
    """result wrote each requested value at every chain copy of its field, and changed no other byte but the
    integrity bytes."""
    parser = backend(image)
    bindings = {b.descriptor['key']: b for b in registry.bindings(image, parser)[0]}
    allowed = {at for r in result.manifest['integrity_repairs']
               for at in range(r['offset'], r['offset'] + (48 if 'sha384' in r['kind'] else 1))}
    for key, value in changes.items():
        binding = bindings[key]
        size = struct.calcsize(binding.encoding)
        test.assertEqual(tuple(binding.offsets), tuple(parser.copy_offsets(binding.offsets[0], size)), key)
        test.assertEqual({struct.unpack_from(binding.encoding, result.blob, at)[0] for at in binding.offsets}, {value},
                         key)
        allowed.update(at for start in binding.offsets for at in range(start, start + size))
    test.assertLessEqual({i for i, (a, b) in enumerate(zip(image.blob, result.blob)) if a != b}, allowed)


class AmpereStructureTests(unittest.TestCase):
    def test_efi_less_chain_and_the_ga10x_npds_stamp(self):
        # A GA104 legacy ID (0x2484) with data images stamped 0x2200, without EFI image.
        image = from_bytes(synthetic_rom(family='ampere', efi_image=False, rails=1, device=0x2484, copies=2))
        parser = backend(image)
        self.assertIsNone(parser.efi)
        self.assertEqual([p['type'] for p in parser.chains[0]], [0, 0xE0, 0xE0])
        self.assertEqual({p['device'] for p in parser.chains[0][1:]}, {0x2200})
        fields = descriptors(image)
        self.assertEqual([fields[k]['current'] for k in POWER], [70, 70, 30])
        result = edit(image, {'power_max_w': 90})
        self.assertEqual(len(result.manifest['edits']), 2)
        self.assertEqual(backend(result.image).power_rows()[2]['maximum_raw'], 90000)

    def test_foreign_or_mixed_npds_identities_are_refused(self):
        blob = bytearray(synthetic_rom(family='ampere', device=0x2484))
        # Data images at 2560 (small) and 3072 (last) after the 512-byte prefix.
        for starts, device in (((3072,), 0x2580), ((2560,), 0x2580), ((2560, 3072), 0x2400)):
            with self.subTest(starts=starts, device=device):
                bad = bytearray(blob)
                for start in starts:
                    struct.pack_into('<H', bad, 512 + start + 32 + 6, device)
                report = inspect_image(from_bytes(bytes(bad)))
                self.assertEqual(report['fields'], [])
                self.assertIn('NPDS chip identity disagrees', report['capabilities']['edit']['reason'])

    def test_editor_only_pci_id_has_its_own_evidence(self):
        # The loader-side refusal of the same ID is in test_payload.
        from nvidia_vbios.families import architecture
        self.assertEqual(architecture(0x2501)['family'], 'unknown')
        editor = architecture(0x2501, ('94.06.2F.00.9A',), editor=True)
        self.assertEqual((editor['family'], editor['in_scope'], editor['bios_family_consistent']), ('ampere', True, True))
        self.assertEqual((editor['evidence'][0]['kind'], editor['evidence'][0]['source'][:8]), ('pci-ids-entry', 'pci.ids:'))
        self.assertEqual(architecture(0x2503, editor=True)['evidence'][0]['kind'], 'explicit-pci-id')
        blob = synthetic_rom(family='ampere', device=0x2501)
        self.assertEqual(inspect_image(from_bytes(blob))['architecture']['evidence'][0]['kind'], 'pci-ids-entry')

    def test_ada_keeps_requiring_the_efi_image(self):
        report = inspect_image(from_bytes(synthetic_rom(efi_image=False)))
        self.assertEqual(report['fields'], [])
        self.assertIn('lacks a contiguous EFI image', report['capabilities']['edit']['reason'])

    def test_power_variants_and_a_null_profile_pointer(self):
        for variant in (0x47, 0x43, 0x32):
            with self.subTest(variant=variant):
                image = from_bytes(synthetic_rom(family='ampere', copies=2, power_variant=variant))
                self.assertTrue(descriptors(image)['power_max_w']['editable'])
                self.assertEqual(backend(edit(image, {'power_max_w': 95}).image).power_rows()[2]['maximum_raw'],
                                 95000)
        # The 0xfc-byte P token of the GDDR6X, 3060 8GB and GA107 images stores a null profile pointer.
        blob = synthetic_rom(family='ampere', copies=2)
        token = backend(from_bytes(blob)).legacy['start'] + 128 + 12
        image = from_bytes(patched(blob, token + 2, struct.pack('<H', 0xFC)))
        parser = backend(image)
        self.assertEqual((parser.tokens['P']['size'], parser.profile_table(), parser.power_profiles()), (0xFC, None, []))
        self.assertTrue(edit(image, {'power_max_w': 95}).manifest['integrity']['valid'])

    def test_unknown_variants_and_identity_gates_keep_power_read_only(self):
        blob = synthetic_rom(family='ampere', copies=2)
        parser = backend(from_bytes(blob))
        table, row = parser.pointer('P', 0x2C), parser.power_rows()[2]['offset']
        cases = ((parser.pointer('P', 0x3C) + 7, b'\xf6', 'total board power channel'),
                 (row + 1, b'\x01', 'total board power channel'),
                 (row, b'\x11', 'unknown identity, units'),
                 (table + 2, b'\x46', 'unvalidated 3x power table variant'),
                 (parser.pointer('P', 0x3C) + 2, b'\x18', 'power channel table'))
        for at, data, message in cases:
            with self.subTest(message=message):
                image = from_bytes(patched(blob, at, data))
                self.assertNotIn('power_max_w', descriptors(image))
                self.assertTrue(any(message in m for m in messages(image)), messages(image))


class AmperePowerTests(unittest.TestCase):
    def setUp(self):
        self.image = from_bytes(synthetic_rom(family='ampere', copies=2, policies=True))
        self.parser = backend(self.image)
        self.rows = self.parser.power_rows()

    def test_policy_rows_by_class_unit_and_channel(self):
        fields = descriptors(self.image)
        expected = {'slot_power_max_w': 78, 'slot_power_rated_w': 66, 'connector_1_power_max_w': 175,
                    'connector_1_power_rated_w': 150, 'connector_2_power_max_w': 175,
                    'connector_2_power_rated_w': 150, 'slot_current_threshold_rated_ma': 11350,
                    'slot_current_threshold_max_ma': 12500, 'input_current_rated_ma': 37800,
                    'input_current_max_ma': 37800}
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertEqual(fields[key]['current'], value)
                self.assertTrue(fields[key]['editable'] and fields[key]['experimental'])
                threshold = 'threshold' in key or key.startswith('input_current')
                self.assertEqual(fields[key].get('opt_in', False), threshold)
        self.assertEqual((fields['connector_1_power_max_w']['channel_rail'], fields['connector_2_power_max_w']['channel_rail']),
                         (0xFA, 0xFB))
        self.assertEqual(fields['input_current_rated_ma']['policy_indices'], [10])
        self.assertEqual([(fields[k]['current'], fields[k]['editable'], fields[k]['opt_in']) for k in NVVDD_OCP],
                         [(226800, True, True)] * 2)
        self.assertTrue(all(fields[k]['experimental'] for k in POWER))
        self.assertNotIn('nvvdd_power_threshold_max_w', fields)

    def test_policy_edits_write_their_rows_in_both_chains(self):
        changes = {'power_max_w': 400, 'power_default_w': 380, 'slot_power_max_w': 80, 'slot_power_rated_w': 75,
                   'connector_1_power_max_w': 200, 'connector_1_power_rated_w': 190, 'connector_2_power_rated_w': 160,
                   'input_current_max_ma': 40000, 'input_current_rated_ma': 39000,
                   'slot_current_threshold_rated_ma': 12000}
        result = edit(self.image, changes)
        self.assertTrue(result.manifest['integrity']['valid'])
        expected = {2: (380000, 400000), 5: (75000, 80000), 6: (190000, 200000), 7: (160000, 175000),
                    8: (12000, 12500), 10: (39000, 40000)}
        for index, (before, after) in enumerate(zip(self.rows, backend(result.image).power_rows())):
            if index in expected:
                self.assertEqual((after['default_raw'], after['maximum_raw']), expected[index])
                self.assertEqual(after['minimum_raw'], before['minimum_raw'])
            else:
                self.assertEqual(after, before)
        offsets = [at for i in expected for o in (6, 10) for at in self.parser.copy_offsets(self.rows[i]['offset'] + o, 4)]
        changed_bytes_within(self, self.image, result, offsets)
        self.assertEqual(len({r['offset'] for r in result.manifest['integrity_repairs']}), 2)
        revert = {key: descriptors(self.image)[key]['current'] for key in changes}
        self.assertEqual(edit(result.image, revert).blob, self.image.blob)

    def test_joint_order_and_rated_exceptions(self):
        for changes in ({'connector_1_power_rated_w': 176}, {'connector_1_power_max_w': 149},
                        {'connector_1_power_max_w': 100, 'connector_1_power_rated_w': 120}):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(self.image, changes)
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        result = edit(self.image, {'connector_2_power_max_w': 140, 'connector_2_power_rated_w': 130})
        self.assertEqual(result.manifest['preservation']['changed_rated_defaults'], ['connector_2_power_rated_w'])

    def test_second_row_on_a_connector_channel_keeps_both_values_read_only(self):
        # Row 9 as a second class-4 mW row on connector 1's channel 5.
        row = self.rows[9]['offset']
        image = from_bytes(patched(self.image.blob, row, bytes((0x04, 5)) + struct.pack('<III', 1000, 120000, 120000)))
        fields = descriptors(image)
        # Connectors are numbered in row order: rows 6 (channel 5), 7 (channel 6) and 9 (channel 5).
        for key in connectors(3):
            with self.subTest(key=key):
                self.assertEqual(fields[key]['editable'], key.startswith('connector_2'))
                if not key.startswith('connector_2'):
                    self.assertIn('same class and unit on this power channel', fields[key]['reason'])
        self.assertEqual(fields['connector_3_power_max_w']['channel_rail'], 0xFA)

    def test_unordered_rows_are_not_exposed(self):
        # Row 6 (connector channel 5) rated above its maximum, as ada_policy refuses.
        image = from_bytes(patched(self.image.blob, self.rows[6]['offset'] + 6, struct.pack('<I', 200000)))
        fields = descriptors(image)
        self.assertNotIn('connector_2_power_max_w', fields)
        self.assertEqual(fields['connector_1_power_max_w']['policy_indices'], [7])

    def test_a_cap_on_a_sum_of_connector_channels_is_named_and_editable(self):
        # Channel 16: class-2 sum of relationship entries 1..2 (channels 5 and 6); row 11 caps it at 280 W.
        image = from_bytes(connector_sum(self.image.blob))
        self.assertEqual(backend(image).summed_channels(16), [5, 6])
        fields = descriptors(image)
        for key in connectors(2):
            with self.subTest(key=key):
                self.assertTrue(fields[key]['editable'])
                self.assertEqual(fields[key]['summed_cap_rows'],
                                 [{'row': 11, 'power_channel': 16, 'summed_channels': [5, 6], 'minimum': 1000,
                                   'rated': 280000, 'maximum': 280000, 'units': 'mW'}])
                self.assertIn('row 11 caps the sum of power channels 5, 6 at 280 W rated', fields[key]['reason'])
                self.assertIn('raise connector_sum_power_rated_w and connector_sum_power_max_w too',
                              fields[key]['reason'])
        for key in CONNECTOR_SUM:
            with self.subTest(key=key):
                self.assertEqual((fields[key]['current'], fields[key]['policy_indices'], fields[key]['summed_channels'],
                                  fields[key]['channel_rail']), (280, [11], [5, 6], 0xE4))
                self.assertTrue(fields[key]['editable'] and fields[key]['experimental'])
                self.assertNotIn('opt_in', fields[key])
        self.assertIn('per-connector and slot limits', fields['connector_sum_power_rated_w']['reason'])
        self.assertNotIn('summed_cap_rows', fields['slot_power_max_w'])
        self.assertNotIn('summed_cap_rows', descriptors(self.image)['connector_1_power_max_w'])
        self.assertFalse(set(CONNECTOR_SUM) & set(descriptors(self.image)))
        # Only row 11 changes, in both chains, with the image checksums.
        rows = backend(image).power_rows()
        result = edit(image, {'connector_sum_power_max_w': 500, 'connector_sum_power_rated_w': 450})
        self.assertTrue(result.manifest['integrity']['valid'])
        after = backend(result.image).power_rows()
        self.assertEqual((after[11]['minimum_raw'], after[11]['default_raw'], after[11]['maximum_raw']),
                         (1000, 450000, 500000))
        self.assertEqual([r for i, r in enumerate(after) if i != 11], [r for i, r in enumerate(rows) if i != 11])
        offsets = [at for o in (6, 10) for at in backend(image).copy_offsets(rows[11]['offset'] + o, 4)]
        self.assertEqual(len(offsets), 4)
        changed_bytes_within(self, image, result, offsets)
        self.assertEqual(len({r['offset'] for r in result.manifest['integrity_repairs']}), 2)
        self.assertEqual(result.manifest['preservation']['changed_rated_defaults'], ['connector_sum_power_rated_w'])
        self.assertEqual(edit(result.image, {'connector_sum_power_max_w': 280, 'connector_sum_power_rated_w': 280}).blob,
                         image.blob)
        for changes in ({'connector_sum_power_rated_w': 300}, {'connector_sum_power_max_w': 270},
                        {'connector_sum_power_max_w': 400, 'connector_sum_power_rated_w': 420}):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes)
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_a_sum_row_gets_a_field_only_with_unit_weight_connector_members(self):
        # Weight -1.0, a slot member, one member, a repeated member, a member past the channel table, an entry with
        # byte 0 = 2 or a nonzero byte 6, a sum channel scaled in bytes 6..7 (0x11c7, as on a real sum of connector
        # channels) or with a parameter in byte 10, or two rows on the sum: named, no field.
        table = self.parser.pointer('P', 0x3C)
        channel, entry, base = table + 6 + 22 * 16, table + 6 + 22 * 32 + 46, connector_sum(self.image.blob)
        for name, blob in (('negative weight', connector_sum(self.image.blob, weight=0xFFFFF000)),
                           ('slot member', connector_sum(self.image.blob, members=(4, 5, 6))),
                           ('one member', connector_sum(self.image.blob, members=(5,))),
                           ('repeated member', connector_sum(self.image.blob, members=(5, 5, 6))),
                           ('member past the table', connector_sum(self.image.blob, members=(5, 6, 32))),
                           ('entry byte 0', patched(base, entry, b'\x02')),
                           ('entry byte 6', patched(base, entry + 6, b'\x01')),
                           ('scaled sum', patched(base, channel + 6, bytes.fromhex('c7 11'))),
                           ('sum parameter', patched(base, channel + 10, b'\x05')),
                           ('two rows', connector_sum(self.image.blob, rows=(11, 12)))):
            with self.subTest(name):
                fields = descriptors(from_bytes(blob))
                self.assertFalse(set(CONNECTOR_SUM) & set(fields))
                self.assertIn('may bind first', fields['connector_1_power_max_w']['reason'])
                self.assertNotIn('connector_sum_power', fields['connector_1_power_max_w']['reason'])

    def test_a_current_threshold_on_a_connector_channel_is_an_opt_in_pair(self):
        image = from_bytes(with_connector_current(self.image.blob))
        fields = descriptors(image)
        keys = connector_currents(1)
        self.assertEqual([fields[k]['current'] for k in keys], [19200, 16000])
        for key in keys:
            with self.subTest(key=key):
                field = fields[key]
                self.assertTrue(field['editable'] and field['experimental'] and field['opt_in'])
                self.assertEqual((field['policy_indices'], field['power_channel'], field['channel_rail'],
                                  field['threshold_index'], field['policy_class']),
                                 ([9], 5, 0xFA, 1, 'hardware-threshold'))
                self.assertIn('no Ampere reading', field['reason'])
                self.assertEqual(field['evidence'][0]['source'], 'Ampere VBIOS corpus, 35 parseable GA102-GA107 images')
        self.assertNotIn('connector_2_current_threshold_max_ma', fields)
        # The 12 V input row (rail 0xe0) stays the input current field.
        self.assertEqual(fields['input_current_rated_ma']['policy_indices'], [10])
        result = edit(image, {'connector_1_current_threshold_max_ma': 25000,
                              'connector_1_current_threshold_rated_ma': 20000})
        parser = backend(image)
        row = parser.power_rows()[9]['offset']
        changed_bytes_within(self, image, result, parser.copy_offsets(row + 6, 4) + parser.copy_offsets(row + 10, 4))
        self.assertEqual((backend(result.image).power_rows()[9]['default_raw'],
                          backend(result.image).power_rows()[9]['maximum_raw']), (20000, 25000))
        self.assertEqual(result.manifest['preservation']['changed_rated_defaults'],
                         ['connector_1_current_threshold_rated_ma'])
        self.assertEqual(edit(result.image, {k: fields[k]['current'] for k in keys}).blob, image.blob)
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'connector_1_current_threshold_rated_ma': 19300})
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_a_current_threshold_needs_one_connector_power_row_on_its_channel(self):
        # Channel 7 (rail 0xfc) has no connector power row: no field, as on the Ampere laptops.
        table = self.parser.pointer('P', 0x3C)
        blob = patched(self.image.blob, table + 6 + 22 * 7, bytes.fromhex('05 fc 00 1b b7 00 00 10'))
        fields = descriptors(from_bytes(with_connector_current(blob, channel=7)))
        self.assertFalse(any('_current_threshold_' in k and k.startswith('connector_') for k in fields))
        # Two connector power rows on channel 5 (connectors 1 and 3): no field for either.
        row = self.rows[11]['offset']
        blob = patched(self.image.blob, row, bytes((0x04, 5)) + struct.pack('<III', 1000, 120000, 120000))
        fields = descriptors(from_bytes(with_connector_current(blob)))
        self.assertIn('connector_3_power_max_w', fields)
        self.assertFalse(any(k.startswith('connector_') and '_current_' in k for k in fields))
        # A second current threshold on the channel: none either.
        blob = patched(with_connector_current(self.image.blob), self.rows[12]['offset'],
                       bytes((0x15, 5)) + struct.pack('<III', 1000, 16000, 19200))
        self.assertNotIn('connector_1_current_threshold_max_ma', descriptors(from_bytes(blob)))

    def test_the_nvvdd_output_current_limit_is_an_opt_in_pair(self):
        fields = descriptors(self.image)
        for key in NVVDD_OCP:
            with self.subTest(key=key):
                field = fields[key]
                self.assertTrue(field['editable'] and field['experimental'] and field['opt_in'])
                self.assertEqual((field['current'], field['units'], field['policy_indices'], field['power_channel'],
                                  field['ordering_group']), (226800, 'mA', [13], 19, 'nvvdd-output-ocp'))
                self.assertEqual((field['bounds']['encoding_minimum'], field['bounds']['encoding_maximum']),
                                 (0, 5000999))
                for text in ('experimental, opt-in', 'row 13, class 0 mA', 'NVVDD output current channel',
                             'whether the firmware enforces it is unproven on Ampere',
                             'it likely protects the core VRM, which was sized for the stock value',
                             'not hardware-tested', 'reliability voltage ceiling (nvvdd_rel_max_mv) may be the next',
                             'values stay below 5001 A', 'stored value, not a hardware-safe VRM rating'):
                    self.assertIn(text, field['reason'])
                self.assertFalse({'same_channel_rows', 'unlimited_rows', 'other_nvvdd_rows'} & set(field))
        self.assertEqual([fields[k]['label'] for k in NVVDD_OCP],
                         ['NVVDD output current limit ceiling', 'NVVDD output current limit (rated)'])
        # The ceiling from the stored rated value up to below 5001 A; the rated value from the stored minimum up to
        # the stored ceiling.
        self.assertEqual([(fields[k]['bounds']['minimum'], fields[k]['bounds']['maximum']) for k in NVVDD_OCP],
                         [(226800, 5000999), (1, 226800)])
        # Both raised in one edit: row 13 rated and maximum in both chains with the image checksums, minimum kept.
        result = edit(self.image, {'nvvdd_output_ocp_max_ma': 453600, 'nvvdd_output_ocp_rated_ma': 453600})
        self.assertTrue(result.manifest['integrity']['valid'])
        after = backend(result.image).power_rows()
        self.assertEqual((after[13]['minimum_raw'], after[13]['default_raw'], after[13]['maximum_raw']),
                         (1, 453600, 453600))
        self.assertEqual([r for i, r in enumerate(after) if i != 13], [r for i, r in enumerate(self.rows) if i != 13])
        offsets = [at for o in (6, 10) for at in self.parser.copy_offsets(self.rows[13]['offset'] + o, 4)]
        self.assertEqual(len(offsets), 4)
        changed_bytes_within(self, self.image, result, offsets)
        self.assertEqual(len({r['offset'] for r in result.manifest['integrity_repairs']}), 2)
        self.assertEqual(result.manifest['preservation']['changed_rated_defaults'], ['nvvdd_output_ocp_rated_ma'])
        self.assertEqual(descriptors(result.image)['nvvdd_output_ocp_rated_ma']['bounds']['maximum'], 453600)
        self.assertEqual(edit(result.image, {k: 226800 for k in NVVDD_OCP}).blob, self.image.blob)
        # Up to 5000.999 A, and back.
        top = edit(self.image, {k: 5000999 for k in NVVDD_OCP})
        self.assertEqual(descriptors(top.image)['nvvdd_output_ocp_max_ma']['current'], 5000999)
        self.assertEqual(edit(top.image, {k: 226800 for k in NVVDD_OCP}).blob, self.image.blob)
        # 5001 A (the no-limit value) or more, a rated value above the ceiling, a ceiling below the rated value, and
        # a rated value below the stored minimum are refused.
        for changes in ({'nvvdd_output_ocp_max_ma': 5001000}, {k: 5001000 for k in NVVDD_OCP},
                        {'nvvdd_output_ocp_max_ma': 6000000, 'nvvdd_output_ocp_rated_ma': 300000},
                        {'nvvdd_output_ocp_rated_ma': 226801}, {'nvvdd_output_ocp_max_ma': 226799},
                        {'nvvdd_output_ocp_max_ma': 300000, 'nvvdd_output_ocp_rated_ma': 300001},
                        {'nvvdd_output_ocp_rated_ma': 0}):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(self.image, changes)
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_a_no_limit_row_on_the_nvvdd_current_channel_does_not_block_the_limit(self):
        # Rows 12 and 18 hold 5001 A as rated and maximum on channel 19, rows 16 and 17 read channel 18.
        image = from_bytes(nvvdd_rows(self.image.blob))
        parser, rows = backend(image), backend(image).power_rows()
        fields = descriptors(image)
        named = [{'row': 16, 'class': 5, 'power_channel': 18, 'minimum': 1000, 'rated': 18750, 'maximum': 18750,
                  'units': 'mW'},
                 {'row': 17, 'class': 5, 'power_channel': 18, 'minimum': 1, 'rated': 12500, 'maximum': 12500,
                  'units': 'mW'}]
        for key in NVVDD_OCP:
            with self.subTest(key=key):
                field = fields[key]
                self.assertTrue(field['editable'])
                self.assertEqual(field['policy_indices'], [13])
                self.assertNotIn('same_channel_rows', field)
                self.assertEqual(field['unlimited_rows'],
                                 [{'row': 18, 'minimum': 1, 'rated': 5001000, 'maximum': 5001000, 'units': 'mA'}])
                self.assertEqual(field['other_nvvdd_rows'], named)
                self.assertIn('row 18 on the same channel holds that value as rated and maximum and is not counted '
                              'as a second limit', field['reason'])
                self.assertIn('row 16 is a class-5 mW row on another NVVDD channel (18; 18.75 W rated, 18.75 W '
                              'maximum; a hardware threshold, meaning unknown, no field) and may bind first',
                              field['reason'])
                self.assertIn('a hardware threshold that trips would show as a hardware slowdown, not as a power '
                              'limit', field['reason'])
                self.assertIn('row 17 is a class-5 mW row on another NVVDD channel (18; 12.5 W rated, 12.5 W '
                              'maximum', field['reason'])
                self.assertNotIn('row 12', field['reason'])
        # The 90 A / 90 A edit of the RTX 3050 Ti Laptop GPU report writes row 13 only.
        result = edit(image, {k: 90000 for k in NVVDD_OCP})
        self.assertTrue(result.manifest['integrity']['valid'])
        after = backend(result.image).power_rows()
        self.assertEqual((after[13]['minimum_raw'], after[13]['default_raw'], after[13]['maximum_raw']),
                         (1, 90000, 90000))
        self.assertEqual([r for i, r in enumerate(after) if i != 13], [r for i, r in enumerate(rows) if i != 13])
        changed_bytes_within(self, image, result,
                             [at for o in (6, 10) for at in parser.copy_offsets(rows[13]['offset'] + o, 4)])
        self.assertEqual(edit(result.image, {k: 226800 for k in NVVDD_OCP}).blob, image.blob)
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'nvvdd_output_ocp_max_ma': 5001000})
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        # Only rated and maximum both 5001 A is the no-limit row: 4000 A rated under a 5001 A maximum is a limit.
        near = descriptors(from_bytes(nvvdd_rows(self.image.blob, row18=(1, 4000000, 5001000))))
        self.assertFalse(near['nvvdd_output_ocp_max_ma']['editable'])
        self.assertNotIn('unlimited_rows', near['nvvdd_output_ocp_max_ma'])
        # A row of another class on the same channel neither blocks nor is the field (row 18 as class 1 mA, 300 A).
        other = descriptors(from_bytes(nvvdd_rows(self.image.blob, row18=(1, 300000, 300000), row18_class=0x11)))
        self.assertTrue(other['nvvdd_output_ocp_rated_ma']['editable'])
        self.assertIn('row 18 is a class-1 mA row on this NVVDD channel (19; 300 A rated, 300 A maximum',
                      other['nvvdd_output_ocp_rated_ma']['reason'])

    def test_a_second_real_limit_on_the_nvvdd_current_channel_keeps_both_values_read_only(self):
        # Row 18 as a class-0 mA row on channel 19 with a real value: which row binds is unknown.
        for limits, own, second in (((1, 300000, 300000), 13, 18), ((1, 100000, 120000), 18, 13)):
            with self.subTest(limits=limits):
                fields = descriptors(from_bytes(nvvdd_rows(self.image.blob, row18=limits)))
                for key in NVVDD_OCP:
                    field = fields[key]
                    self.assertFalse(field['editable'])
                    self.assertTrue(field['opt_in'])
                    # The lowest row has the field; the other one is named.
                    self.assertEqual(field['policy_indices'], [own])
                    self.assertEqual([o['row'] for o in field['same_channel_rows']], [second])
                    self.assertIn(f'row {second} (parameter byte 0 = ', field['reason'])
                    self.assertIn('is another policy row of the same class and unit on this power channel; which row '
                                  'binds is unknown', field['reason'])
                    self.assertNotIn('unlimited_rows', field)
        # No class-0 mA row below 5001 A on an NVVDD channel: no field.
        blob = patched(self.image.blob, self.rows[13]['offset'] + 2, struct.pack('<III', 1, 5001000, 5001000))
        self.assertFalse(set(NVVDD_OCP) & set(descriptors(from_bytes(blob))))

    def test_a_current_row_on_another_nvvdd_channel_never_takes_the_field(self):
        # Row 12 as a class-0 mA row on the other NVVDD channel 18 (sensor byte 14 = 5), 60 A: below row 13 and at a
        # lower row index, but not on the output current channel. It is named and may bind first; row 13 keeps the
        # field through edits that pass it, and going back writes row 13 again.
        rows = self.rows
        blob = patched(nvvdd_rows(self.image.blob), rows[12]['offset'],
                       bytes((0x10, 18)) + struct.pack('<III', 1, 60000, 60000))
        image = from_bytes(blob)
        fields = descriptors(image)
        for key in NVVDD_OCP:
            self.assertTrue(fields[key]['editable'])
            self.assertEqual(fields[key]['policy_indices'], [13])
            self.assertEqual(fields[key]['other_nvvdd_rows'][0], {'row': 12, 'class': 0, 'power_channel': 18,
                                                                  'minimum': 1, 'rated': 60000, 'maximum': 60000,
                                                                  'units': 'mA'})
            self.assertIn('row 12 is a class-0 mA row on another NVVDD channel (18; 60 A rated, 60 A maximum; '
                          'meaning unknown, no field) and may bind first', fields[key]['reason'])
        low = edit(image, {k: 45000 for k in NVVDD_OCP})
        high = edit(low.image, {k: 60000 for k in NVVDD_OCP})
        for result, value in ((low, 45000), (high, 60000)):
            after = backend(result.image).power_rows()
            self.assertEqual((after[12]['default_raw'], after[12]['maximum_raw']), (60000, 60000))
            self.assertEqual((after[13]['default_raw'], after[13]['maximum_raw']), (value, value))
            self.assertEqual(descriptors(result.image)['nvvdd_output_ocp_max_ma']['policy_indices'], [13])
        self.assertEqual(edit(high.image, {k: 226800 for k in NVVDD_OCP}).blob, image.blob)
        # The same row on a second output current channel (channel 18 with sensor byte 14 = 6, not byte-identical to
        # channel 19) is a second limit: both values stay read-only, so no edit can move the field.
        table = backend(image).pointer('P', 0x3C)
        rival = from_bytes(patched(blob, table + 6 + 22 * 18 + 14, b'\x06'))
        fields = descriptors(rival)
        for key in NVVDD_OCP:
            field = fields[key]
            self.assertFalse(field['editable'])
            self.assertEqual(field['policy_indices'], [12])
            self.assertEqual(field['reason'], 'read-only: row 13 (power channel 19, rated 226.8 A, maximum 226.8 A) '
                                              'is another class-0 mA row on an NVVDD output current channel; which '
                                              'row binds is unknown, so editing this row alone may have no effect')
        with self.assertRaises(VbiosError):
            edit(rival, {k: 70000 for k in NVVDD_OCP})

    def test_notebook_header_names_row_2(self):
        image = from_bytes(synthetic_rom(family='ampere', copies=2, notebook=True))
        fields = descriptors(image)
        self.assertEqual([fields[k]['current'] for k in ('power_min_w', 'power_default_w', 'power_max_w')], [30, 70, 70])
        self.assertTrue(all(fields[key]['experimental'] for key in POWER))
        for key in ('power_max_w', 'power_default_w'):
            self.assertIn('notebook', fields[key]['reason'])
        self.assertIn('Ampere laptop', fields['power_max_w']['reason'])
        self.assertEqual(backend(edit(image, {'power_max_w': 90}).image).power_rows()[2]['maximum_raw'], 90000)


class AmpereVoltageTests(unittest.TestCase):
    def test_constant_rail_equations_stay_read_only_on_both_rails(self):
        image = from_bytes(synthetic_rom(family='ampere', copies=2))
        fields = descriptors(image)
        for rail in ('nvvdd', 'msvdd'):
            for role, value in (('rel', 1081.25), ('alt', 1100), ('ov', 1100)):
                field = fields[f'{rail}_{role}_equation_max_mv']
                with self.subTest(rail=rail, role=role):
                    self.assertEqual((field['current'], field['editable'], field['equation_kind']),
                                     (value, False, 'constant'))
                    self.assertIn('constant equation', field['reason'])
            self.assertFalse(fields[f'{rail}_rel_max_mv']['editable'])
            self.assertEqual(fields[f'{rail}_boot_voltage_uv']['current'], 750000)
        self.assertEqual(fields['msvdd_ov_selector_index']['current'], 7)
        for key in ('nvvdd_rel_max_mv', 'nvvdd_rel_equation_max_mv', 'msvdd_alt_equation_max_mv'):
            with self.assertRaises(VbiosError) as exc:
                edit(image, {key: 1100})
            self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')

    def test_single_rail_reports_msvdd_absent_and_gates_refuse_other_layouts(self):
        blob = synthetic_rom(family='ampere', rails=1, copies=2)
        fields = descriptors(from_bytes(blob))
        self.assertIsNone(fields['msvdd_rel_max_mv']['current'])
        self.assertFalse(any(k.startswith('msvdd_') and k != 'msvdd_rel_max_mv' for k in fields))
        parser = backend(from_bytes(blob))
        row, vfe = parser.pointer('P', 0x68) + 5, parser.pointer('P', 0x20)
        for name, at, data in (('VMIN', row + 11, b'\x02'), ('rail header', row - 2, b'\x13'),
                               ('VFE', vfe + 4, b'\x19')):
            with self.subTest(gate=name):
                image = from_bytes(patched(blob, at, data))
                self.assertNotIn('nvvdd_rel_equation_max_mv', descriptors(image))
                self.assertTrue(any('Ampere rail' in m or 'Ampere VFE' in m for m in messages(image)), messages(image))


class AmpereClockTests(unittest.TestCase):
    def test_rows_are_named_by_gv_hal_position_and_every_chain_is_written(self):
        for rails in (1, 2):
            with self.subTest(rails=rails):
                image = from_bytes(synthetic_rom(family='ampere', copies=2, rails=rails))
                parser = backend(image)
                rows = parser.clock_ranges()
                self.assertEqual([r['domain'] for r in rows], GV_HAL)
                fields = descriptors(image)
                self.assertTrue(all(fields[k]['editable'] and fields[k]['experimental'] for k in CLOCKS))
                self.assertEqual(fields['memory_offset_max_mhz']['current'], 6000)
                changes = {'gpc_offset_max_mhz': 1500, 'memory_offset_min_mhz': -5000, 'vid_min_table_mhz': -1500}
                result = edit(image, changes)
                named = {r['domain']: r for r in rows}
                offsets = [named['GPC']['maximum_offset'], named['DRAM']['minimum_offset'], named['VID']['minimum_offset']]
                changed_bytes_within(self, image, result, [at for o in offsets for at in parser.copy_offsets(o, 2)], width=2)
                after = {r['domain']: (r['minimum_mhz'], r['maximum_mhz']) for r in backend(result.image).clock_ranges()}
                self.assertEqual((after['GPC'], after['DRAM'], after['VID']), ((-1000, 1500), (-2500, 3000), (-1500, 3000)))

    def test_a_range_may_not_collapse_to_0_0(self):
        # 0..0 reads as disabled (read-only), so an edit reaching it could not be reverted.
        image = from_bytes(synthetic_rom(family='ampere', copies=2))
        for changes in ({'gpc_offset_max_mhz': 0, 'gpc_offset_min_mhz': 0},
                        {'memory_offset_min_mhz': 0, 'memory_offset_max_mhz': 0},
                        {'xbar_max_table_mhz': 0, 'xbar_min_table_mhz': 0}):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes)
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        half = edit(image, {'gpc_offset_max_mhz': 0})
        self.assertTrue(descriptors(half.image)['gpc_offset_min_mhz']['editable'])
        with self.assertRaises(VbiosError) as exc:
            edit(half.image, {'gpc_offset_min_mhz': 0})
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        stock = descriptors(image)['gpc_offset_max_mhz']['current']
        self.assertEqual(edit(half.image, {'gpc_offset_max_mhz': stock}).blob, image.blob)

    def test_disabled_ranges_and_other_rows_stay_read_only(self):
        blob = synthetic_rom(family='ampere', copies=2)
        parser = backend(from_bytes(blob))
        gpc = parser.clock_ranges()[0]
        fields = descriptors(from_bytes(patched(blob, gpc['minimum_offset'], bytes(4))))
        for key in ('gpc_offset_max_mhz', 'gpc_offset_min_mhz'):
            self.assertFalse(fields[key]['editable'])
            self.assertIn('0..0', fields[key]['reason'])
        self.assertTrue(fields['memory_offset_max_mhz']['editable'])
        vid = parser.clock_ranges()[5]['minimum_offset'] - 3
        for name, at, data in (('VID rail type 1', vid + 13 + 3, b'\x01'), ('ordering', vid + 7, b'\x45'),
                               ('header', parser.pointer('C', 8) + 6, b'\x02')):
            with self.subTest(gate=name):
                image = from_bytes(patched(blob, at, data))
                self.assertNotIn('gpc_offset_max_mhz', descriptors(image))
                self.assertTrue(any('GV HAL' in m or 'clock table variant' in m for m in messages(image)))


class AmpereFanTests(unittest.TestCase):
    def test_an_unused_speed_table_keeps_both_fan_fields(self):
        image = from_bytes(synthetic_rom(family='ampere', copies=2, fans=2, fan_speed=False))
        fields = descriptors(image)
        self.assertTrue(fields['fan_channels']['editable'] and fields['fan_pwm_frequency_hz']['editable'])
        lowered = edit(image, {'fan_channels': 1})
        table = backend(lowered.image).fan_coolers()
        self.assertEqual(table['channels'], [0])
        self.assertEqual([r['speed_enable'] for r in table['rows']], [0, 0])
        self.assertEqual(edit(lowered.image, {'fan_channels': 2}).blob, image.blob)
        slower = edit(image, {'fan_pwm_frequency_hz': 25000})
        self.assertEqual({r['pwm_frequency_hz'] for r in backend(slower.image).fan_coolers()['rows']}, {25000})
        # A speed table enabled on one active channel only still has to agree.
        speed = backend(image).fan_coolers()['rows'][0]['speed_offset']
        self.assertNotIn('fan_channels', descriptors(from_bytes(patched(image.blob, speed, b'\x01'))))
        laptop = descriptors(from_bytes(synthetic_rom(family='ampere', fans=-1)))
        self.assertFalse(any(key.startswith('fan_') for key in laptop))

    def test_a_stopped_fan_row_raises_its_minimum_only_with_the_curve(self):
        # As on the RTX 3080/3090 boards: 0 % and 0 RPM as row minimum and curve start.
        image = from_bytes(synthetic_rom(family='ampere', copies=2, fans=2))
        row = backend(image).fan_coolers()['rows'][0]
        blob = image.blob
        for at, data in ((row['offset'] + 2, b'\x00'), (row['offset'] + 14, bytes(2)),
                         (row['policy_offset'] + 14, b'\x00'), (row['policy_offset'] + 20, bytes(2))):
            blob = patched(blob, at, data)
        stopped = from_bytes(blob)
        fields = descriptors(stopped)
        # The minimums (0..0) and the level maximum (100..100) stay where they are alone, and move with the curve.
        for key in ('fan_1_min_rpm', 'fan_1_min_pct', 'fan_1_max_pct', 'fan_1_max_rpm', 'fan_2_min_rpm'):
            with self.subTest(key=key):
                self.assertTrue(fields[key]['editable'])
                self.assertTrue(fields[key]['reason'].startswith('experimental:'))
        self.assertEqual((fields['fan_1_min_rpm']['current'], fields['fan_1_min_rpm']['bounds']['maximum']), (0, 0))
        with self.assertRaises(VbiosError) as exc:
            edit(stopped, {'fan_1_min_rpm': 500})
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        spinning = edit(stopped, {'fan_1_min_rpm': 500, 'fan_1_curve_1_rpm': 500, 'fan_1_min_pct': 10,
                                  'fan_1_curve_1_pct': 10})
        self.assertEqual(backend(spinning.image).fan_coolers()['rows'][0]['rpm_minimum'], 500)
        self.assertEqual(edit(spinning.image, {'fan_1_min_rpm': 0, 'fan_1_curve_1_rpm': 0, 'fan_1_min_pct': 0,
                                               'fan_1_curve_1_pct': 0}).blob, stopped.blob)
        faster = edit(stopped, {'fan_1_max_rpm': 3600})
        self.assertEqual(backend(faster.image).fan_coolers()['rows'][0]['rpm_maximum'], 3600)
        self.assertEqual(edit(faster.image, {'fan_1_max_rpm': 3300}).blob, stopped.blob)

    def test_an_unused_speed_table_leaves_the_maximum_to_the_curves(self):
        # Both fixtures store 2295 RPM in the speed entries; only enabled ones hold the maximum.
        top = ['fan_1_max_rpm', 'fan_1_curve_3_rpm', 'fan_extra_1_curve_3_rpm', 'fan_extra_2_curve_3_rpm']
        for speed in (True, False):
            with self.subTest(speed=speed):
                image = from_bytes(synthetic_rom(family='ampere', copies=2, fans=2, fan_speed=speed))
                self.assertTrue(all(f['editable'] for k, f in descriptors(image).items() if '_curve_' in k))
                if speed:
                    with self.assertRaises(VbiosError) as exc:
                        edit(image, {key: 2100 for key in top})
                    self.assertEqual(exc.exception.details['bounds']['minimum'], 2295)
                    continue
                lowered = edit(image, {key: 2100 for key in top})
                self.assertEqual(backend(lowered.image).fan_coolers()['rows'][0]['rpm_maximum'], 2100)
                self.assertEqual(edit(lowered.image, {key: 3300 for key in top}).blob, image.blob)

    def test_extra_curves_may_start_below_the_channel_minimums(self):
        # As on a stock RTX 3090 blower image: both channels run from 2500 RPM and 60 %, where their own curves start
        # (2500/2900/3300 RPM, 60/75/100 %), while the extra curves (entries 2 and 3) start at 1000 RPM and 20 %. Only
        # the channel curves hold the minimums; the extra curves stay at or below the lowest maximum and may sit below
        # the minimums.
        blob = synthetic_rom(family='ampere', copies=2, fans=2, fan_speed=False)
        for row in backend(from_bytes(blob)).fan_coolers()['rows']:
            for at, data in ((row['offset'] + 2, bytes((60,))), (row['offset'] + 14, struct.pack('<H', 2500)),
                             (row['policy_offset'] + 14, bytes((60, 75, 100))),
                             (row['policy_offset'] + 20, struct.pack('<H', 2500)),
                             (row['policy_offset'] + 24, struct.pack('<H', 2900))):
                blob = patched(blob, at, data)
        image = from_bytes(blob)
        fields = descriptors(image)
        bounds = lambda key: (fields[key]['current'], fields[key]['bounds']['minimum'],
                              fields[key]['bounds']['maximum'], fields[key]['editable'])
        for n in (1, 2):
            self.assertEqual([bounds(f'fan_{n}_{side}') for side in ('min_rpm', 'min_pct', 'max_rpm')],
                             [(2500, 0, 2500, True), (60, 0, 60, True), (3300, 3300, 32767, True)])
            self.assertIn('the extra curves may start below it', fields[f'fan_{n}_min_rpm']['reason'])
            # The speed table is disabled, so the reasons do not name its value.
            for side in ('min', 'max'):
                self.assertNotIn('speed-table value', fields[f'fan_{n}_{side}_rpm']['reason'])
        for m in (1, 2):
            self.assertEqual([bounds(f'fan_extra_{m}_curve_{k}') for k in ('1_rpm', '1_pct', '3_rpm', '3_pct')],
                             [(1000, 0, 2000, True), (20, 0, 50, True), (3300, 2000, 3300, True), (100, 50, 100, True)])
            self.assertIn('may sit below their minimums', fields[f'fan_extra_{m}_curve_1_rpm']['reason'])
        # A minimum still moves past its own curve only with it.
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_1_min_rpm': 2600})
        self.assertEqual((exc.exception.code, exc.exception.details['bounds']['maximum']), ('OUT_OF_BOUNDS', 2500))
        lower = {'fan_1_min_rpm': 2000, 'fan_1_min_pct': 30, 'fan_1_curve_1_rpm': 2000, 'fan_1_curve_1_pct': 40}
        result = edit(image, lower)
        assert_written(self, image, result, lower)
        self.assertEqual(edit(result.image, {key: fields[key]['current'] for key in lower}).blob, image.blob)
        # An extra curve point goes below every minimum alone, but not above the lowest maximum.
        below = {'fan_extra_1_curve_1_rpm': 500, 'fan_extra_2_curve_1_pct': 10}
        lowered = edit(image, below)
        assert_written(self, image, lowered, below)
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_extra_1_curve_3_rpm': 3400})
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        # The channel count stays offered, before and after: a stored channel needs only its maximums at or above
        # the extra curves, which may start below its minimums.
        self.assertEqual(bounds('fan_channels'), (2, 1, 2, True))
        count = descriptors(lowered.image)['fan_channels']
        self.assertEqual((count['bounds']['minimum'], count['bounds']['maximum'], count['editable']), (1, 2, True))
        self.assertEqual(edit(edit(image, {'fan_channels': 1}).image, {'fan_channels': 2}).blob, image.blob)

    def test_an_unused_copy_of_the_fan_1_policy_entry_is_written_with_it(self):
        # As on an HP OEM RTX 3060 12 GB: channel 2 is disabled in every table but the policy table, whose entry 1
        # is byte for byte the channel 1 entry, and no enabled control entry sets bit 1 of byte 5 (0x0d here).
        stock = with_zero_rpm(synthetic_rom(family='ampere', copies=2, fans=1), flags=(0x11, 0x01),
                              pairs=((45, 55), (90, 95), (85, 90)))
        image = from_bytes(with_policy_copy(stock))
        parser = backend(image)
        table = parser.fan_coolers()
        source, copy = table['rows']
        self.assertEqual((source['active'], copy['active'], copy['policy_copy_of'], source['policy_copy_offsets'],
                          source['policy_copy_of'], copy['policy_copy_offsets']),
                         (True, False, 0, [copy['policy_offset']], None, []))
        self.assertEqual(([c['index'] for c in table['extra_curves']], table['channels']), ([2, 3], [0]))
        fields = descriptors(image)
        self.assertEqual((fields['fan_channels']['editable'], fields['fan_channels']['reason']),
                         (False, FAN_POLICY_COPY_CHANNELS_REASON))
        bindings = {b.descriptor['key']: b for b in registry.bindings(image, parser)[0]}
        pairs = [(a, a - source['policy_offset'] + copy['policy_offset'])
                 for a in parser.copy_offsets(source['policy_offset'], 0x33)]

        def mirrored(blob):
            return all(blob[a:a + 0x33] == blob[c:c + 0x33] for a, c in pairs)
        # Every field inside the channel 1 entry also writes the copy, in both chains; the extra curves do not.
        for key in ('fan_1_curve_1_temp_c', 'fan_1_curve_3_pct', 'fan_1_zero_rpm_high_temp_c'):
            with self.subTest(key=key):
                field = fields[key]
                offsets = bindings[key].offsets
                self.assertEqual(len(offsets), 4)
                self.assertEqual(field['fan_policy_copies'], [{'entry': 1, 'copy_of': 0}])
                self.assertIn('also keeps a copy of the channel 1 fan policy entry in entry 1 (fan channel 2, '
                              'disabled), most likely unused, and the editor writes the same bytes there',
                              field['reason'])
                value = Decimal(str(field['current'])) - (1 if field['units'] != 'C' else Decimal(1) / 2)
                result = edit(image, {key: value})
                self.assertTrue(mirrored(result.blob) and result.blob != image.blob)
                self.assertEqual({result.blob[a] for a in offsets}, {result.blob[offsets[0]]})
                self.assertEqual(backend(result.image).fan_coolers()['rows'][1]['policy_copy_of'], 0)
                self.assertEqual(edit(result.image, {key: field['current']}).blob, image.blob)
        self.assertEqual(len(bindings['fan_extra_1_curve_1_temp_c'].offsets), 2)
        self.assertNotIn('fan_policy_copies', fields['fan_extra_1_curve_1_temp_c'])
        # Zero RPM: the copy's flag byte takes the same bits as its source (0x11 -> 0x17), the extra curves 0x07.
        flag = fields['fan_zero_rpm']
        self.assertEqual((flag['current'], flag['editable'], flag['fan_entries']), (0, True, [0, 1, 2, 3]))
        on = edit(image, {'fan_zero_rpm': 1})
        policy = table['policy_offset'] + 4
        self.assertEqual([on.blob[c + 0x33 * k + 0x32] for k in range(4)
                          for c in parser.copy_offsets(policy, 1)], [0x17] * 4 + [0x07] * 4)
        self.assertTrue(mirrored(on.blob))
        self.assertEqual(descriptors(on.image)['fan_zero_rpm']['current'], 1)
        self.assertEqual(edit(on.image, {'fan_zero_rpm': 0}).blob, image.blob)
        # Anything else stays refused: a copy one byte off, or a disabled entry enabled with its own curve.
        for name, blob in (('flag byte', patched(image.blob, copy['policy_offset'] + 0x32, b'\x13')),
                           ('curve point', patched(image.blob, copy['policy_offset'] + 18, struct.pack('<H', 50 * 32))),
                           ('own entry', patched(stock, copy['policy_offset'], b'\x01')),
                           ('enabled mapping', patched(image.blob, copy['mapping_offset'], b'\x01'))):
            with self.subTest(refused=name):
                broken = from_bytes(blob)
                self.assertFalse(any(key.startswith('fan_') for key in descriptors(broken)))
                self.assertTrue(any('fan channel enables disagree' in m for m in messages(broken)))
        # Bit 1 in an enabled control entry's first mask: the control entry combines entry 1 for its cooler, so it is
        # an extra curve (as on the RTX 3050 6GB and 8GB), not a copy; in the second mask (bytes 9..12) the copy rule
        # refuses it.
        masked = from_bytes(patched(image.blob, source['control_offset'] + 5, b'\x0f'))
        table = backend(masked).fan_coolers()
        self.assertEqual(([c['index'] for c in table['extra_curves']], table['rows'][1]['policy_copy_of']),
                         ([1, 2, 3], None))
        fields = descriptors(masked)
        self.assertEqual(fields['fan_channels']['reason'], FAN_LOW_EXTRA_CHANNELS_REASON)
        self.assertNotIn('fan_policy_copies', fields['fan_1_curve_1_temp_c'])
        masked = from_bytes(patched(image.blob, source['control_offset'] + 9, b'\x03'))
        self.assertFalse(any(key.startswith('fan_') for key in descriptors(masked)))
        self.assertTrue(any('fan channel enables disagree' in m for m in messages(masked)))
        # The copy's channel stored in every table with its own cooler configuration: a channel count would clear the
        # copy's enable byte (the stored count) or enable its channel, so none is offered.
        stored = from_bytes(patched(image.blob, copy['control_offset'] + 5, b'\x0e'))
        table = backend(stored).fan_coolers()
        self.assertEqual((table['rows'][1]['stored'], table['rows'][1]['policy_copy_of']), (True, 0))
        self.assertEqual(fan_layouts(backend(stored), table), (1, 1, [], ()))
        channels = descriptors(stored)['fan_channels']
        self.assertEqual((channels['editable'], channels['reason']), (False, FAN_POLICY_COPY_CHANNELS_REASON))

    def test_an_extra_fan_curve_in_a_disabled_channels_policy_entry(self):
        # As on the RTX 3050 6GB and 8GB: channel 2 is disabled in every table but the policy table, whose entry 1
        # holds its own curve (thermal channel 1) and is named in the first mask of the enabled control entry (0x0f
        # here, 0x03 there): an extra curve at entry 1, numbered before the entries past the cooler rows.
        stock = with_low_extra(synthetic_rom(family='ampere', copies=2, fans=1))
        image = from_bytes(with_zero_rpm(stock, pairs=((40, 50), (60, 70), (53, 63), (60, 70))))
        parser = backend(image)
        table = parser.fan_coolers()
        channel, low = table['rows']
        self.assertEqual((table['channels'], [c['index'] for c in table['extra_curves']], channel['stored'],
                          low['active'], low['policy_copy_of']), ([0], [1, 2, 3], True, False, None))
        self.assertEqual(fan_layouts(parser, table), (1, 1, [], ()))
        fields = descriptors(image)
        self.assertEqual((fields['fan_channels']['current'], fields['fan_channels']['editable'],
                          fields['fan_channels']['reason']), (1, False, FAN_LOW_EXTRA_CHANNELS_REASON))
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_channels': 2})
        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')
        extra = fields['fan_extra_1_curve_1_temp_c']
        self.assertEqual((extra['current'], extra['fan_policy'], extra['fan_rows'], extra['editable']),
                         (95.0, 1, [0], True))
        self.assertEqual([fields[f'fan_extra_{m}_curve_1_temp_c']['fan_policy'] for m in (2, 3)], [2, 3])
        # The extra curve takes its points in both chains and bounds the channel maximum like the others.
        entry = low['policy_offset']
        result = edit(image, {'fan_extra_1_curve_1_temp_c': 90})
        changed_bytes_within(self, image, result, parser.copy_offsets(entry + 18, 2), width=2)
        self.assertEqual([c['index'] for c in backend(result.image).fan_coolers()['extra_curves']], [1, 2, 3])
        self.assertEqual(edit(result.image, {'fan_extra_1_curve_1_temp_c': 95}).blob, image.blob)
        self.assertEqual(fields['fan_extra_1_curve_3_rpm']['bounds']['maximum'], 3300)  # the channel maximum
        # Zero RPM covers entry 1 with the channel and extra entries; 0 clears both bits and 1 restores the bytes.
        flag = fields['fan_zero_rpm']
        self.assertEqual((flag['current'], flag['editable'], flag['fan_entries']), (1, True, [0, 1, 2, 3]))
        off = edit(image, {'fan_zero_rpm': 0})
        flags = [e['policy_offset'] + 0x32 for e in [channel] + table['extra_curves']]
        self.assertEqual([off.blob[c] for at in flags for c in parser.copy_offsets(at, 1)],
                         [0x11] * 4 + [0x01] * 4)
        self.assertEqual(descriptors(off.image)['fan_zero_rpm']['current'], 0)
        self.assertEqual(edit(off.image, {'fan_zero_rpm': 1}).blob, image.blob)
        self.assertEqual(fields['fan_extra_1_zero_rpm_high_temp_c']['current'], 70.0)
        # Anything else stays refused: entry 1 left out of the mask (and not a copy of entry 0, so the enables
        # disagree); channel 2 enabled in the mapping (fan test), control or speed table (in use here), or entry 1
        # disabled, while the mask names it (entry 1 is then no extra curve, and the channel 1 control entry, whose
        # mask names it, is not stored).
        control = low['control_offset']
        self.assertEqual([r['speed_enable'] for r in table['rows']], [1, 0])
        for name, blob, error in (('not in the mask', patched(stock, channel['control_offset'] + 5, b'\x0d'),
                                   'fan channel enables disagree'),
                                  ('enabled mapping', patched(stock, low['mapping_offset'], b'\x01'),
                                   'not stored in every fan table'),
                                  ('enabled control', patched(patched(stock, control + 5, b'\x0e'), control, b'\x01'),
                                   'not stored in every fan table'),
                                  ('enabled speed', patched(stock, low['speed_offset'], b'\x01'),
                                   'not stored in every fan table'),
                                  ('disabled entry', patched(stock, entry, b'\x00'), 'not stored in every fan table')):
            with self.subTest(refused=name):
                broken = from_bytes(blob)
                self.assertFalse(any(key.startswith('fan_') for key in descriptors(broken)))
                self.assertTrue(any(error in m for m in messages(broken)))
        # Without its bit in the mask, entry 1 byte for byte entry 0 is an unused copy (an HP OEM RTX 3060 12 GB).
        copied = backend(from_bytes(patched(with_policy_copy(stock), channel['control_offset'] + 5, b'\x0d')))
        self.assertEqual(copied.fan_coolers()['rows'][1]['policy_copy_of'], 0)

    def test_zero_rpm_with_a_pair_the_editor_does_not_show(self):
        # As on the RTX 3050 6GB: the channel entry and the extra curve at entry 1 store 52/55 C with zero RPM on
        # (0x17) in a block GSP-RM accepts with byte 46 = 0xff, so no pair field is shown. 1 stays offered on a copy
        # saved at 0 (bits clear: a nonzero pair in an accepted block), which comes back byte for byte; a zero lower
        # is no such pair.
        stock = with_low_extra(synthetic_rom(family='ampere', copies=2, fans=1))
        block = REFERENCE_BLOCK[:-1] + b'\xff'
        blob = with_zero_rpm(stock, pairs=((52, 55), (52, 55), (53, 63), (60, 70)), block=block)
        image = from_bytes(blob)
        fields = descriptors(image)
        self.assertFalse([key for key in fields if '_zero_rpm_' in key])
        self.assertEqual((fields['fan_zero_rpm']['current'], fields['fan_zero_rpm']['editable']), (1, True))
        off = edit(image, {'fan_zero_rpm': 0})
        flag = descriptors(off.image)['fan_zero_rpm']
        self.assertEqual((flag['current'], flag['editable']), (0, True))
        self.assertEqual(edit(off.image, {'fan_zero_rpm': 1}).blob, blob)
        zero = with_zero_rpm(stock, flags=(0x11, 0x01), pairs=((0, 55), (0, 55), (0, 63), (0, 70)), block=block)
        flag = descriptors(from_bytes(zero))['fan_zero_rpm']
        self.assertEqual((flag['current'], flag['editable'], flag['reason'].startswith(FAN_ZERO_RPM_NO_BLOCK_REASON)),
                         (0, False, True))
        # The start rule: no field moves the 55 C upper, so point 1 stays at 55 C or more while zero RPM is on, and
        # the refusal names turning zero RPM off (or leaving it off) instead of a pair to lower.
        for source, request, field in ((image, {'fan_1_curve_1_temp_c': 50}, 'fan_1_curve_1_temp_c'),
                                       (edit(off.image, {'fan_1_curve_1_temp_c': 50}).image, {'fan_zero_rpm': 1},
                                        'fan_zero_rpm')):
            with self.subTest(request=request):
                with self.assertRaises(VbiosError) as exc:
                    edit(source, request)
                self.assertEqual((exc.exception.code, exc.exception.details['field'],
                                  exc.exception.details['joint_fields']),
                                 ('ZERO_RPM_ABOVE_CURVE', field, ['fan_1_curve_1_temp_c']))
                self.assertIn('keep fan_1_curve_1_temp_c at 55 C or more', str(exc.exception))
                self.assertIn('or turn fan_zero_rpm off in the same edit' if field != 'fan_zero_rpm' else
                              'the zero RPM pair of this entry is not editable on this image, so its upper stays as '
                              'stored), or leave fan_zero_rpm off', str(exc.exception))
                self.assertNotIn('saved copy', str(exc.exception))
        self.assertEqual(descriptors(edit(image, {'fan_zero_rpm': 0, 'fan_1_curve_1_temp_c': 50}).image)
                         ['fan_1_curve_1_temp_c']['current'], 50)


if __name__ == '__main__':
    unittest.main()
