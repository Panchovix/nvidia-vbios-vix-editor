"""Ada and GB20x auxiliary power connector input limits (connector_1_power_*, opt-in): generated images and,
where available, the reference ROMs."""
import os
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nvidia_vbios.editor import edit
from nvidia_vbios.rom import VbiosError, from_bytes, inspect_image, load
from nvidia_vbios.rom.image import backend
from nvidia_vbios.rom.tables import TableRom
from test_ada_fields import patched, sense_profiles
from test_extended_fields import changed_bytes_within, descriptors, repair_fixture, sff_fixture, single_rail_fixture
from test_rom_formats import synthetic_rom

KEYS = ('connector_1_power_max_w', 'connector_1_power_rated_w')
SECOND = ('connector_2_power_max_w', 'connector_2_power_rated_w')
ENCODING_MAXIMUM = 0x7FFFFFFF / 1000


def summed_by_total(blob, channel):
    """Add channel to the relationship entries of channel 0, the board total (weight 1.0), in both chains.

    The entries are 6 bytes here ({1, channel, weight}; 46 on the corpus images, the rest zero) so that a few
    fit between the synthetic channel and power tables.
    """
    from nvidia_vbios.rom.tables import UNIT_WEIGHT
    parser = backend(from_bytes(blob))
    table = parser.pointer('P', 0x3C)
    if parser.blob[table + 4] != 6:
        blob = patched(blob, table + 4, b'\x06')
        parser = backend(from_bytes(blob))
    hs, size, count, rsize = parser.blob[table + 1:table + 5]
    members = [r[1] for r in parser.relationships(0) if r[0] == 1]
    members += [] if channel in members else [channel]
    for i, member in enumerate(members):
        blob = patched(blob, table + hs + size * count + rsize * i,
                       bytes((1, member)) + UNIT_WEIGHT + bytes(rsize - 6))
    return patched(blob, table + hs + 14, bytes((0, len(members) - 1)))


def ada_connector(blob=None, *, row=6, channel=5, rail=0xFA, provider=1, limits=(1000, 150000, 150000),
                  identity=None, entry=None, summed=True):
    """The synthetic Ada image with an auxiliary connector input row: class 4 mW with the slot row shape on a
    class-5 12 V channel (rail 0xfa and provider byte 1, as on the RTX 4070 image) that channel 0 adds (summed),
    in both chains."""
    blob = synthetic_rom(copies=2, policies=True) if blob is None else blob
    parser = backend(from_bytes(blob))
    at = parser.power_rows()[row]['offset']
    data = bytearray(parser.power_entry_size)
    for offset, value in (identity or {0: 0x04, 1: channel, 41: 1}).items():
        data[offset] = value
    struct.pack_into('<III', data, 2, *limits)
    blob = patched(blob, at, bytes(data))
    if entry is None:
        entry = bytes.fromhex(f'05 {rail:02x} 00 1b b7 00 00 10') + bytes(7) + bytes((provider,)) + bytes(10)
    blob = patched(blob, parser.pointer('P', 0x3C) + 6 + 26 * channel, entry)
    return summed_by_total(blob, channel) if summed else blob


def gb20x_connector(*, device=0x2D04, rows=(17,), monitor=2, channel=None, shape=None, limits=(0, 150000, 150000)):
    """The single-rail 5060 Ti fixture (slot row 18) with row 17 as the RTX 5060 Ti stores it: the SFF slot row
    shape on monitor 2, whose power channel holds the auxiliary connector input bytes."""
    from nvidia_vbios.rom.blackwell import CONNECTOR_INPUT_CHANNEL
    blob = bytearray(single_rail_fixture(slot_row=18, device=device))
    parsed = backend(from_bytes(bytes(blob)))
    for row in rows:
        at = parsed.power_rows()[row]['offset']
        blob[at:at + 102] = bytes(102)
        for offset, value in (shape or {0: 2, 5: monitor, 6: 1, 33: 10, 34: 10}).items():
            blob[at + offset] = value
        struct.pack_into('<III', blob, at + 13, *limits)
    at = parsed.pointer('P', 0x3C) + 0x11 + 0x1A * 2
    blob[at:at + 0x1A] = CONNECTOR_INPUT_CHANNEL if channel is None else channel
    return repair_fixture(blob)


class AdaConnectorInputTests(unittest.TestCase):
    def setUp(self):
        self.blob = ada_connector()
        self.image = from_bytes(self.blob)
        self.parser = backend(self.image)
        self.rows = self.parser.power_rows()

    def offsets(self, row, parser=None):
        parser = parser or self.parser
        return [at for o in (6, 10) for at in parser.copy_offsets(parser.power_rows()[row]['offset'] + o, 4)]

    def test_the_connector_row_is_an_opt_in_pair_and_absent_without_it(self):
        from nvidia_vbios.editor.sections import opt_in_field_keys
        report = inspect_image(self.image)
        fields = {f['key']: f for f in report['fields']}
        ceiling, rated = (fields[k] for k in KEYS)
        for field in (ceiling, rated):
            self.assertEqual((field['current'], field['units'], field['stored_units']), (150, 'W', 'mW'))
            self.assertTrue(field['editable'] and field['experimental'] and field['opt_in'])
            self.assertEqual((field['policy_indices'], field['power_channel'], field['channel_rail'],
                              field['connector'], field['power_input'], field['ordering_group']),
                             ([6], 5, 0xFA, 1, 'auxiliary-connector', 'connector-1-power'))
            self.assertNotIn('same_channel_rows', field)
            for text in ('experimental, opt-in', 'power channel 5, rail 0xfa', 'the connector type is not stored',
                         'a PCIe 8-pin connector is rated 150 W, a 12V-2x6 cable at the level its sense pins report',
                         'puts the cable, the connector and the power supply at risk, and is your call',
                         'the board power limit, the PCIe slot limit (slot_power_max_w, slot_power_rated_w) and the '
                         '12 V input current threshold (input_current_rated_ma, input_current_max_ma) still apply '
                         'and may bind next'):
                self.assertIn(text, field['reason'])
            self.assertNotIn('threshold_rows', field)
        self.assertEqual((ceiling['bounds']['minimum'], ceiling['bounds']['maximum']), (150, ENCODING_MAXIMUM))
        self.assertEqual((rated['bounds']['minimum'], rated['bounds']['maximum']), (1, 150))
        self.assertEqual([e['kind'] for e in rated['evidence']], ['structural-row-comparison', 'owner-report'])
        self.assertLessEqual(set(KEYS), opt_in_field_keys(report))
        self.assertFalse(any(k.startswith('connector_') for k in descriptors(from_bytes(synthetic_rom(
            copies=2, policies=True)))))

    def test_an_edit_writes_only_the_row_in_both_chains_and_round_trips(self):
        changes = {'connector_1_power_max_w': 200, 'connector_1_power_rated_w': 200}
        result = edit(self.image, changes)
        self.assertTrue(result.manifest['integrity']['valid'])
        for index, (before, after) in enumerate(zip(self.rows, backend(result.image).power_rows())):
            self.assertEqual(after, dict(before, default_raw=200000, maximum_raw=200000) if index == 6 else before)
        changed_bytes_within(self, self.image, result, self.offsets(6))
        self.assertTrue(all(result.blob[at:at + 4] == struct.pack('<I', 200000) for at in self.offsets(6)))
        self.assertEqual(result.manifest['preservation']['changed_rated_defaults'], ['connector_1_power_rated_w'])
        self.assertEqual(edit(result.image, {k: 150 for k in KEYS}).blob, self.image.blob)
        # No cap past the stored ceiling but the encoding; the rated value follows the ceiling of the result.
        far = edit(self.image, {'connector_1_power_max_w': 2000, 'connector_1_power_rated_w': 2000})
        self.assertEqual(backend(far.image).power_rows()[6]['default_raw'], 2000000)
        for changes in ({'connector_1_power_rated_w': 200}, {'connector_1_power_max_w': 140},
                        {'connector_1_power_rated_w': 200, 'connector_1_power_max_w': 180}):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(self.image, changes)
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_the_channel_and_the_row_shape_gate_the_fields(self):
        channel = bytes.fromhex('05 fa 00 1b b7 00 00 10') + bytes(7) + b'\x01' + bytes(10)
        cases = {'rail 0xda': (dict(rail=0xDA), True), 'provider byte 0': (dict(rail=0xDA, provider=0), True),
                 'rail 0xdb': (dict(rail=0xDB), True), 'rail 0xfb': (dict(rail=0xFB), True),
                 'rail 0xe4': (dict(rail=0xE4), True), 'provider byte 2': (dict(provider=2), True),
                 'rail 0xe8': (dict(rail=0xE8), False), 'slot rail': (dict(rail=0xFF), False),
                 '12 V input rail': (dict(rail=0xE0), False), 'provider byte 3': (dict(provider=3), False),
                 'not added by channel 0': (dict(summed=False), False),
                 'current correction byte': (dict(entry=channel[:10] + b'\xc8' + channel[11:]), False),
                 'class-2 channel': (dict(entry=b'\x02' + channel[1:]), False),
                 'class 0 row': (dict(identity={0: 0x00, 1: 5, 41: 1}), False),
                 'mA row': (dict(identity={0: 0x14, 1: 5, 41: 1}), False),
                 'other parameter byte': (dict(identity={0: 0x04, 1: 5, 20: 1, 41: 1}), False),
                 'slot shape on the slot channel': (dict(identity={0: 0x04, 1: 4, 41: 1}), False)}
        for name, (options, present) in cases.items():
            with self.subTest(case=name):
                fields = descriptors(from_bytes(ada_connector(**options)))
                self.assertEqual(all(k in fields for k in KEYS), present)
                self.assertFalse(any(k.startswith('connector_') for k in fields) and not present)
                if present:
                    self.assertTrue(fields[KEYS[1]]['editable'])
        # Bytes past the 0x53-byte entry prefix must stay zero, as for the other Ada policy rows.
        blob = patched(self.blob, self.rows[6]['offset'] + 0x53, b'\x01')
        self.assertNotIn(KEYS[0], descriptors(from_bytes(blob)))
        # A notebook image has no auxiliary connector: its DC input channel holds the same bytes.
        notebook = ada_connector(synthetic_rom(copies=2, policies=True, notebook=True), rail=0xDA, provider=0)
        self.assertFalse(any(k.startswith('connector_') for k in descriptors(from_bytes(notebook))))

    def test_a_current_threshold_on_the_connector_input_is_named(self):
        # A class-5 mA row (hardware current threshold) on the connector channel, as row 9 of the RTX 4000 Ada.
        blob = ada_connector(ada_connector(), row=7, identity={0: 0x15, 1: 5, 41: 1}, limits=(1000, 12340, 12340))
        fields = descriptors(from_bytes(blob))
        from nvidia_vbios.gui.presentation import connector_input_notes
        for key in KEYS:
            with self.subTest(key=key):
                field = fields[key]
                self.assertTrue(field['editable'])
                self.assertEqual(field['threshold_rows'], [{'row': 7, 'parameter_byte_0': 0, 'minimum': 1000,
                                                            'rated': 12340, 'maximum': 12340, 'units': 'mA'}])
                self.assertIn('; row 7, a 12.34 A current threshold (rated) on this connector input, about 148 W at '
                              '12 V, has no field and may hold the connector first', field['reason'])
        notes = connector_input_notes(fields[KEYS[0]], list(fields.values()))
        self.assertEqual(notes[2], 'Row 7 also holds a 12.34 A current threshold on this connector input (about 148 W '
                                   'at 12 V). It cannot be edited here and may hold the connector first.')
        self.assertIn('umbral de corriente de 12.34 A', connector_input_notes(fields[KEYS[0]], list(fields.values()),
                                                                             'es')[2])

    def test_an_unrecognized_policy_on_another_connector_input_keeps_the_fields_read_only(self):
        # Row 7: class 4 mW of another shape (parameter byte 0 = 1) on a second connector input (channel 6, 0xfb).
        blob = ada_connector(ada_connector(), row=7, channel=6, rail=0xFB, identity={0: 0x04, 1: 6, 14: 1, 41: 1},
                             limits=(1000, 150000, 150000))
        image = from_bytes(blob)
        fields = descriptors(image)
        self.assertFalse(any(k.startswith('connector_2_') for k in fields))
        for key in KEYS:
            with self.subTest(key=key):
                field = fields[key]
                self.assertEqual((field['current'], field['editable']), (150, False))
                self.assertEqual(field['unrecognized_connector_rows'],
                                 [{'row': 7, 'power_channel': 6, 'channel_rail': 0xFB, 'minimum': 1000,
                                   'rated': 150000, 'maximum': 150000, 'units': 'mW'}])
                self.assertIn('read-only: row 7 (class 4 mW on power channel 6, rail 0xfb, rated 150 W, maximum '
                              '150 W) is another connector input policy without a recognized shape', field['reason'])
                with self.assertRaises(VbiosError):
                    edit(image, {key: 150})
        # Not added by channel 0, channel 6 is no board input and row 7 does not block.
        blob = ada_connector(ada_connector(), row=7, channel=6, rail=0xFB, identity={0: 0x04, 1: 6, 14: 1, 41: 1},
                             summed=False)
        self.assertTrue(all(descriptors(from_bytes(blob))[k]['editable'] for k in KEYS))

    def test_another_row_on_the_channel_keeps_both_values_read_only(self):
        # A second class-4 mW row (another shape) on channel 5.
        blob = ada_connector(ada_connector(), row=7, identity={0: 0x04, 1: 5, 14: 1, 41: 1},
                             limits=(1000, 120000, 120000))
        image = from_bytes(blob)
        fields = descriptors(image)
        self.assertFalse(any(k.startswith('connector_2_') for k in fields))
        for key in KEYS:
            with self.subTest(key=key):
                field = fields[key]
                self.assertEqual((field['current'], field['editable']), (150, False))
                self.assertEqual(field['same_channel_rows'], [{'row': 7, 'parameter_byte_0': 1, 'minimum': 1000,
                                                               'rated': 120000, 'maximum': 120000, 'units': 'mW'}])
                self.assertIn('is another policy row of the same class and unit on this power channel', field['reason'])
                with self.assertRaises(VbiosError):
                    edit(image, {key: 160})

    def test_two_connector_channels_are_numbered_in_row_order(self):
        blob = ada_connector(ada_connector(), row=7, channel=6, rail=0xDA, limits=(1000, 300000, 300000))
        image = from_bytes(blob)
        fields = descriptors(image)
        self.assertEqual([(fields[k]['current'], fields[k]['policy_indices'], fields[k]['channel_rail'])
                          for k in KEYS + SECOND],
                         [(150, [6], 0xFA), (150, [6], 0xFA), (300, [7], 0xDA), (300, [7], 0xDA)])
        self.assertTrue(all(fields[k]['editable'] for k in KEYS + SECOND))
        result = edit(image, {'connector_2_power_max_w': 330, 'connector_2_power_rated_w': 330})
        changed_bytes_within(self, image, result, self.offsets(7, backend(image)))
        self.assertEqual(backend(result.image).power_rows()[6], backend(image).power_rows()[6])

    def test_undecoded_profiles_keep_the_fields_read_only(self):
        image = from_bytes(patched(self.blob, self.parser.pointer('P', 0xF4) + 0xFE, b'\x01'))
        fields = descriptors(image)
        for key in KEYS:
            with self.subTest(key=key):
                self.assertEqual((fields[key]['current'], fields[key]['editable']), (150, False))
                self.assertIn('override profiles do not decode', fields[key]['reason'])
                with self.assertRaises(VbiosError):
                    edit(image, {key: 150})

    def test_cable_sense_profiles_bind_the_connector_row_like_the_other_policy_rows(self):
        # Profile 7 (top sense level, equal to the base) also holds the connector row; profile 6 (a lower level)
        # replaces its maximum and rated value with 120 and 100 W.
        blob = sense_profiles(self.blob)
        at = self.parser.profile_table()
        for profile, j, selector, value in ((7, 2, 0x006, 150000), (7, 3, 0x106, 150000),
                                            (6, 4, 0x006, 120000), (6, 5, 0x106, 100000)):
            blob = patched(blob, at + 0xFE + 0x49 * profile + 1 + 9 * j, struct.pack('<BII', 1, selector, value))
        image = from_bytes(blob)
        parser = backend(image)
        fields = descriptors(image)
        ceiling, rated = (fields[k] for k in KEYS)
        self.assertTrue(ceiling['editable'] and rated['editable'])
        self.assertEqual((rated['bounds']['minimum'], rated['bounds']['maximum']), (100, 150))
        self.assertIn('firmware-static-analysis', [e['kind'] for e in rated['evidence']])
        self.assertIn('override profile 6 replaces this value with 120 W', ceiling['reason'])
        self.assertIn('override profile 6 replaces this value with 100 W', rated['reason'])
        result = edit(image, {k: 200 for k in KEYS})
        top = [e for p in backend(result.image).power_profiles() if p['index'] == 7 for e in p['entries']
               if e['policy'] == 6]
        self.assertEqual([e['value_raw'] for e in top], [200000, 200000])
        lower = [e for p in backend(result.image).power_profiles() if p['index'] == 6 for e in p['entries']
                 if e['policy'] == 6]
        self.assertEqual([e['value_raw'] for e in lower], [120000, 100000])
        tied = [at for p in parser.power_profiles() if p['index'] == 7 for e in p['entries'] if e['policy'] == 6
                for at in parser.copy_offsets(e['value_offset'], 4)]
        changed_bytes_within(self, image, result, self.offsets(6, parser) + tied)
        self.assertEqual(edit(result.image, {k: 150 for k in KEYS}).blob, image.blob)
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'connector_1_power_rated_w': 90})
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_gui_labels_and_notes(self):
        from nvidia_vbios.gui.presentation import connector_input_notes, field_label, field_section, shunt_scaled
        fields = descriptors(self.image)
        values = list(fields.values())
        self.assertEqual(field_label(fields[KEYS[0]]), 'Connector power channel 1 ceiling (advanced, experimental)')
        self.assertEqual(field_label(fields[KEYS[1]], 'es'),
                         'Límite del canal de potencia de conector 1, nominal (avanzado, experimental)')
        self.assertTrue(all(shunt_scaled(fields[k]) and field_section(fields[k]) == 'power' for k in KEYS))
        notes = connector_input_notes(fields[KEYS[0]], values)
        self.assertEqual(len(notes), 2)
        self.assertIn('The ROM does not store the connector type: a PCIe 8-pin connector is rated for 150 W, a '
                      '12V-2x6 (16-pin) cable for the level its sense pins report.', notes[0])
        self.assertIn('puts the cable, the connector and the power supply at risk. That is your call.', notes[0])
        self.assertIn('12 V input current limit or threshold still apply', notes[1])
        spanish = connector_input_notes(fields[KEYS[0]], values, 'es')
        self.assertIn('un conector PCIe de 8 pines admite 150 W', spanish[0])
        self.assertIn('pone en riesgo el cable, el conector y la fuente. Es decisión tuya.', spanish[0])
        self.assertIn('El límite de potencia de la placa', spanish[1])
        self.assertEqual(connector_input_notes(fields[KEYS[1]], values), [])
        # With the ceiling read-only the rated row carries the notes; read-only rows carry none.
        partial = [dict(f, editable=False) if f['key'] == KEYS[0] else f for f in values]
        self.assertEqual(len(connector_input_notes(fields[KEYS[1]], partial)), 2)
        self.assertEqual(connector_input_notes(dict(fields[KEYS[0]], editable=False), values), [])
        # The Ampere connector channel fields keep their labels and get no note.
        ampere = descriptors(from_bytes(synthetic_rom(family='ampere', policies=True)))
        self.assertEqual(field_label(ampere[KEYS[0]]), 'Connector power channel 1 ceiling (experimental)')
        self.assertNotIn('opt_in', ampere[KEYS[0]])
        self.assertEqual(connector_input_notes(ampere[KEYS[0]], list(ampere.values())), [])


class GB20xConnectorInputTests(unittest.TestCase):
    def setUp(self):
        self.image = from_bytes(gb20x_connector())
        self.rows = backend(self.image).power_rows()

    def test_row17_is_an_opt_in_pair(self):
        fields = descriptors(self.image)
        ceiling, rated = (fields[k] for k in KEYS)
        for field in (ceiling, rated):
            self.assertEqual((field['current'], field['units'], field['stored_units']), (150, 'W', 'mW'))
            self.assertTrue(field['editable'] and field['experimental'] and field['opt_in'])
            self.assertEqual((field['policy_indices'], field['vbios_policy_index'], field['monitor'],
                              field['power_channel'], field['channel_rail'], field['power_input']),
                             ([17], 17, {'index': 2, 'class': 8}, 2, 0xDA, 'auxiliary-connector'))
            self.assertEqual([e['kind'] for e in field['evidence']],
                             ['structural-row-comparison', 'saved-get-monitor-correlation', 'owner-report'])
            self.assertIn('the board power limit and the PCIe slot limit (slot_power_max_w, slot_power_rated_w) still '
                          'apply and may bind next', field['reason'])
            self.assertIn('a PCIe 8-pin connector is rated 150 W, a 12V-2x6 cable', field['reason'])
            self.assertIn('98.06.39.00.B2 (row 17)', field['evidence'][0]['scope'])
        self.assertEqual((ceiling['bounds']['minimum'], ceiling['bounds']['maximum']), (150, ENCODING_MAXIMUM))
        self.assertEqual((rated['bounds']['minimum'], rated['bounds']['maximum']), (0, 150))
        self.assertEqual(fields['slot_power_rated_w']['policy_indices'], [18])
        for blob in (sff_fixture(), single_rail_fixture(slot_row=18)):
            self.assertFalse(any(k.startswith('connector_') for k in descriptors(from_bytes(blob))))

    def test_an_edit_writes_row17_with_its_hashes_and_round_trips(self):
        result = edit(self.image, {k: 200 for k in KEYS})
        self.assertTrue(result.manifest['integrity']['valid'])
        for index, (before, after) in enumerate(zip(self.rows, backend(result.image).power_rows())):
            self.assertEqual(after, dict(before, default_raw=200000, maximum_raw=200000) if index == 17 else before)
        row = self.rows[17]['offset']
        changed_bytes_within(self, self.image, result, [row + 17, row + 21])
        self.assertIn('object_sha384', [r['kind'] for r in result.manifest['integrity_repairs']])
        self.assertEqual(edit(result.image, {k: 150 for k in KEYS}).blob, self.image.blob)
        for changes in ({'connector_1_power_rated_w': 200}, {'connector_1_power_max_w': 140}):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(self.image, changes)
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_recognition_follows_the_row_and_channel_not_the_device(self):
        for device in (0x2D05, 0x2C02):
            with self.subTest(device=device):
                fields = descriptors(from_bytes(gb20x_connector(device=device)))
                self.assertTrue(all(fields[k]['editable'] for k in KEYS))
                self.assertNotIn('slot_power_rated_w', fields)
                # No slot field: the slot limit is not named.
                self.assertIn('the board power limit', fields[KEYS[1]]['reason'])
                self.assertNotIn('slot', fields[KEYS[1]]['reason'])
        from nvidia_vbios.rom.blackwell import CONNECTOR_INPUT_CHANNEL as channel
        cases = {'second input rail': dict(channel=channel[:1] + b'\xdb' + channel[2:15] + b'\x02' + channel[16:]),
                 'provider byte 0': dict(channel=channel[:15] + b'\x00' + channel[16:]),
                 'disabled channel': dict(channel=b'\x00' + channel[1:]),
                 'slot monitor': dict(monitor=1),
                 'mA row': dict(shape={0: 2, 1: 1, 5: 2, 6: 1, 33: 10, 34: 10}),
                 'other row type': dict(shape={0: 11, 5: 2, 6: 1, 33: 10, 34: 10}),
                 'other parameter byte': dict(shape={0: 2, 5: 2, 6: 1, 33: 10, 34: 11})}
        for name, options in cases.items():
            with self.subTest(case=name):
                fields = descriptors(from_bytes(gb20x_connector(**options)))
                self.assertFalse(any(k.startswith('connector_') for k in fields))

    def test_rows_an_override_profile_may_name_never_qualify(self):
        # Rows 2/7/8/9 are the only policies an override profile entry names; editing the base row alone there
        # would leave a profile value in force.
        for row in (2, 7, 8, 9):
            with self.subTest(row=row):
                fields = descriptors(from_bytes(gb20x_connector(rows=(row,))))
                self.assertFalse(any(k.startswith('connector_') for k in fields))

    def test_two_rows_on_the_channel_are_read_only(self):
        image = from_bytes(gb20x_connector(rows=(16, 17)))
        fields = descriptors(image)
        for key in KEYS + SECOND:
            with self.subTest(key=key):
                self.assertEqual((fields[key]['current'], fields[key]['editable']), (150, False))
                self.assertIn('rows 16, 17 all read the auxiliary connector input channel', fields[key]['reason'])
        self.assertEqual(fields[SECOND[0]]['policy_indices'], [17])
        with self.assertRaises(VbiosError) as exc:
            edit(image, {KEYS[0]: 200})
        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')

    def test_undecodable_profiles_keep_the_fields_read_only(self):
        blob = bytearray(self.image.blob)
        entry = backend(self.image).power_profiles()[0]['entries'][0]
        struct.pack_into('<I', blob, entry['value_offset'] - 4, 13 | 1 << 8)
        image = from_bytes(repair_fixture(blob))
        fields = descriptors(image)
        for key in KEYS:
            with self.subTest(key=key):
                self.assertFalse(fields[key]['editable'])
                self.assertIn('override profiles do not decode', fields[key]['reason'])
                with self.assertRaises(VbiosError):
                    edit(image, {key: 150})


if __name__ == '__main__':
    unittest.main()
