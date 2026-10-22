"""Max operating temperature and factory GPC and memory offsets (GB20x, Ada, Ampere, Turing): synthetic images and
opt-in reference ROMs."""
from decimal import Decimal
import os
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nvidia_vbios.editor import edit, import_fields
from nvidia_vbios.editor.registry import (FACTORY_BOOST_REASON, FACTORY_OFFSET_FRACTION_REASON,
                                          FACTORY_UNREVIEWED_REASON, MAX_TEMP_DISABLED_REASON,
                                          MAX_TEMP_LOWER_LIMIT_REASON, MAX_TEMP_NO_POLICY_REASON,
                                          MAX_TEMP_UNEQUAL_REASON, MAX_TEMP_UNRECOGNIZED_REASON, registry)
from nvidia_vbios.gui.presentation import field_label, field_section, read_only_reason, unsupported_notes
from nvidia_vbios.rom import from_bytes, inspect_image, load, VbiosError
from nvidia_vbios.rom.image import backend
from nvidia_vbios.rom.tables import ADA_EDITED_TABLES, TURING_EDITED_TABLES
from test_extended_fields import changed_bytes_within, custom_registry, descriptors, repair_fixture, set_device
from test_rom_formats import synthetic_blackwell, synthetic_rom
from test_turing import synthetic_turing

KEYS = ('max_operating_temp_c', 'factory_gpc_offset_mhz', 'factory_memory_offset_mhz', 'factory_rated_boost_mhz')
OFFSETS = ('factory_gpc_offset_mhz', 'factory_memory_offset_mhz')


def fixture(*, thermal=True, factory_clocks=True, device=None, mutate=None):
    """A synthetic GB20x image with both tables; mutate(blob, parser) reshapes them before the rehash."""
    blob = bytearray(synthetic_blackwell(thermal=thermal, factory_clocks=factory_clocks))
    if device is not None:
        set_device(blob, device)
    if mutate is not None:
        mutate(blob, backend(from_bytes(bytes(blob))))
    return from_bytes(repair_fixture(blob))


def thermal_entry(parser, index=0):
    return parser.thermal_policies()['entries'][index]['offset']


def set_temperatures(*celsius_32, index=0):
    def mutate(blob, parser):
        for start in starts(parser, thermal_entry(parser, index)):
            struct.pack_into('<3h', blob, start + 2, *celsius_32)
    return mutate


def starts(parser, at):
    """at in every chain (Turing, Ampere and Ada images may hold several)."""
    return parser.copy_offsets(at, 1) if hasattr(parser, 'copy_offsets') else [at]


def factory_entry(blob, parser, array, index, flag, khz):
    record = parser.factory_clocks()
    entry = record['offsets' if array == 'A' else 'clocks'][index]['offset']
    for at in starts(parser, entry):
        struct.pack_into('<BI' if array == 'B' or khz >= 0 else '<Bi', blob, at, flag, khz)


def entry_bytes(blob, parser, index):
    """The five bytes (flag, kHz) of array-A entry index."""
    at = parser.factory_clocks()['offsets'][index]['offset']
    return bytes(blob[at:at + 5])


def changed(before, after):
    return {i for i, (a, b) in enumerate(zip(before.blob, after.blob)) if a != b}


def probe(test, image, offsets, encoding):
    """An extension binding writing another value at offsets is refused as a preserved-byte change."""
    stored = struct.unpack_from(encoding, image.blob, offsets[0])[0]
    with test.assertRaises(VbiosError) as exc:
        edit(image, {'probe': 0 if stored else 1}, field_registry=custom_registry('probe', offsets, encoding=encoding,
                                                                                  scale=1))
    test.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')


# Generated Turing, Ampere and Ada images: the v0x10 thermal policy table and the factory clock record, placed in
# the data image (offset from the legacy image start) and pointed to from the BIT P token of every chain.
LEGACY_TABLES = {'turing': (0x1F06, 89, 0x1C00, 0x1E00), 'ampere': (0x2204, 93, 5600, 5850),
                 'ada': (0x28B0, 96, 5600, 5850)}
POLICY_WORDS = bytes.fromhex('c8 00 13 40 ff ff ff 7f 20 00 00 00 e0 ff a0 ff 88 13 00 00')


def thermal_table(family, celsius, *, laptop=False):
    """Desktop: entry 0 (named by header byte 9) at celsius on channel 0, entry 1 at 105 C on channel 1 and the
    84/65/88 C target named by header byte 4. Laptop: entry 0 at 105 C on channel 1 (named), entry 1 at 89 C on
    channel 0 that no header byte names, and the 87/75/87 C target named by header byte 5."""
    header_size = 0x0B if family == 'ada' else 0x0A
    roles = (0xFF, 2) if laptop else (2, 0xFF)
    header = bytes((0x10, header_size, 0x28, 4, *roles, 0xFF, 0x00, 0x02, 0x00)) + bytes((3,))[:header_size - 10]
    rows = ([(1, 1, (105,) * 3), (1, 0, (89,) * 3), (1, 0, (87, 75, 87)), (0, 0xFF, (0,) * 3)] if laptop else
            [(1, 0, (celsius,) * 3), (1, 1, (105,) * 3), (1, 0, (84, 65, 88)), (0, 0xFF, (0,) * 3)])
    table = bytearray(header)
    for kind, channel, temperatures in rows:
        table += bytes((kind, channel)) + struct.pack('<3h', *(t * 32 for t in temperatures))
        table += (POLICY_WORDS if kind else bytes(20)) + bytes(12)
    return bytes(table)


def factory_record(family, *, a0=(1, 60000), a1=(0, 0), b1=(1, 1800000)):
    header = bytes.fromhex('10 06 05 02 05 02' if family == 'turing' else '10 07 05 02 05 02 00')
    return header + struct.pack('<BiBiBIBI', *a0, *a1, 0, 0, *b1)


def legacy_fixture(family, *, thermal=True, factory=True, laptop=False, device=None, mutate=None, **factory_entries):
    """A generated Turing, Ampere or Ada image (two chains) with the thermal policy table (thermal_table) and the
    factory clock record (factory_record: A0 flag 1 at 60 MHz, B1 flag 1 at 1800 MHz); mutate(blob, parser) reshapes
    them in every chain before the checksums are repaired."""
    default_device, celsius, thermal_at, factory_at = LEGACY_TABLES[family]
    device = device or default_device
    blob = (synthetic_turing(clocks=True, device=device) if family == 'turing' else
            synthetic_rom(family=family, copies=2, device=device))
    tables = {}
    if thermal:
        tables[0x50] = (thermal_at, thermal_table(family, celsius, laptop=laptop))
    if factory:
        tables[0x98] = (factory_at, factory_record(family, **factory_entries))
    parser = backend(from_bytes(blob))
    out = bytearray(blob)
    if family == 'ada':
        # The generated Ada image always carries the RTX 2000 Ada identity: rewrite its PCI device.
        for image in (image for chain in parser.chains for image in chain if image['type'] in (0, 3)):
            struct.pack_into('<H', out, image['pcir'] + 6, device)
    legacy, efi = parser.legacy, parser.efi
    token = parser.tokens['P']['data'] - legacy['start']
    for pointer, (relative, data) in tables.items():
        value = relative - (efi['size'] if efi is not None and relative >= legacy['size'] else 0)
        for chain in parser.chains:
            out[chain[0]['start'] + relative:chain[0]['start'] + relative + len(data)] = data
            struct.pack_into('<I', out, chain[0]['start'] + token + pointer, value)
    if mutate is not None:
        mutate(out, backend(from_bytes(bytes(out))))
    for image in (image for chain in parser.chains for image in chain):
        out[image['end'] - 1] = (out[image['end'] - 1] - sum(out[image['start']:image['end']])) & 255
    return from_bytes(bytes(out))


def legacy_offsets(binding):
    width = struct.calcsize(binding.encoding)
    return {at for start in binding.offsets for at in range(start, start + width)}


def checksum_bytes(result):
    return {r['offset'] for r in result.manifest['integrity_repairs']}


class MaxOperatingTemperatureTests(unittest.TestCase):
    def test_absent_tables_add_no_field_and_no_diagnostic(self):
        for image in (from_bytes(synthetic_blackwell()), legacy_fixture('ada', thermal=False, factory=False),
                      legacy_fixture('turing', thermal=False, factory=False)):
            with self.subTest(image=backend(image).__class__.__name__):
                report = inspect_image(image)
                self.assertFalse(set(KEYS) & {f['key'] for f in report['fields']})
                self.assertFalse([d for d in report['diagnostics']
                                  if d.get('resolver') in ('max_operating_temperature', 'factory_clocks')])

    def test_descriptor_bounds_and_three_words_written_together(self):
        for header in (12, 22):
            with self.subTest(header=header):
                image = fixture(thermal=header)
                field = descriptors(image)['max_operating_temp_c']
                self.assertEqual((field['current'], field['editable'], field['units'], field['stored_units'],
                                  field['experimental'], field['stock_c']), (90, True, 'C', '1/32 C', True, 90))
                self.assertEqual((field['bounds']['minimum'], field['bounds']['maximum']), (40, 93))
                self.assertNotIn('opt_in', field)
                self.assertEqual(field_section(field), 'power')
                parser = backend(image)
                at = thermal_entry(parser) + 2
                result = edit(image, {'max_operating_temp_c': 85.5})
                self.assertTrue(result.manifest['integrity']['valid'])
                self.assertEqual(struct.unpack_from('<3h', result.blob, at), (85 * 32 + 16,) * 3)
                changed_bytes_within(self, image, result, [at, at + 2, at + 4], width=2)
                self.assertEqual(result.manifest['changed_object_ids'], [0x1B])
                # Byte 0 (class), byte 1 and every other entry keep their bytes.
                self.assertEqual(result.blob[at - 2:at], image.blob[at - 2:at])
                self.assertEqual(descriptors(result.image)['max_operating_temp_c']['current'], 85.5)
                self.assertEqual(edit(result.image, {'max_operating_temp_c': 90}).blob, image.blob)

    def test_range_floor_and_stock_ceiling(self):
        image = fixture()
        self.assertEqual(descriptors(edit(image, {'max_operating_temp_c': 40}).image)['max_operating_temp_c']
                         ['current'], 40)
        self.assertEqual(descriptors(edit(image, {'max_operating_temp_c': 93}).image)['max_operating_temp_c']
                         ['current'], 93)
        for value, code in ((Decimal(40) - Decimal(1) / 32, 'OUT_OF_BOUNDS'),
                            (Decimal(93) + Decimal(1) / 32, 'OUT_OF_BOUNDS'),
                            (85.01, 'UNREPRESENTABLE_VALUE')):
            with self.subTest(value=value):
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {'max_operating_temp_c': value})
                self.assertEqual(exc.exception.code, code)

    def test_ceiling_follows_the_product_stock_value_not_the_stored_one(self):
        # Lowered earlier: raising back up to stock + 3 C is still offered.
        lowered = fixture(mutate=set_temperatures(*(70 * 32,) * 3))
        field = descriptors(lowered)['max_operating_temp_c']
        self.assertEqual((field['current'], field['bounds']['minimum'], field['bounds']['maximum']), (70, 40, 93))
        # Stored above stock + 3 C (another tool): it may stay or go down, not up.
        raised = fixture(mutate=set_temperatures(*(100 * 32,) * 3))
        field = descriptors(raised)['max_operating_temp_c']
        self.assertEqual((field['bounds']['minimum'], field['bounds']['maximum']), (40, 100))
        # Products without a reviewed stock value (here an RTX 5090 D) can only lower it.
        unlisted = fixture(device=0x2B87)
        field = descriptors(unlisted)['max_operating_temp_c']
        self.assertEqual((field['stock_c'], field['bounds']['minimum'], field['bounds']['maximum']), (None, 40, 90))
        with self.assertRaises(VbiosError) as exc:
            edit(unlisted, {'max_operating_temp_c': 91})
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        # Other reviewed products use their own stock value; the stored 90 C stays allowed above it.
        for device, stock, ceiling in ((0x2C02, 88, 91), (0x2C33, 96, 99), (0x2F04, 85, 90)):
            field = descriptors(fixture(device=device))['max_operating_temp_c']
            self.assertEqual((field['stock_c'], field['bounds']['maximum']), (stock, ceiling))

    def test_disabled_unequal_or_unrecognized_entry_is_read_only(self):
        def disabled(blob, parser):
            blob[thermal_entry(parser)] = 0
        def other_byte1(blob, parser):
            blob[thermal_entry(parser) + 1] = 2
        cases = ((disabled, MAX_TEMP_DISABLED_REASON),
                 (set_temperatures(90 * 32, 75 * 32, 90 * 32), MAX_TEMP_UNEQUAL_REASON),
                 (other_byte1, MAX_TEMP_UNRECOGNIZED_REASON))
        for mutate, reason in cases:
            with self.subTest(reason=reason):
                image = fixture(mutate=mutate)
                field = descriptors(image)['max_operating_temp_c']
                self.assertEqual((field['editable'], field['reason'], field['current']), (False, reason, 90))
                self.assertEqual(field['capability']['vbios']['writable'], 'unsupported')
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {'max_operating_temp_c': 85})
                self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')

    def test_another_entry_of_the_same_kind_is_named_in_the_reason(self):
        self.assertNotIn('may have no effect', descriptors(fixture())['max_operating_temp_c']['reason'])
        def second(blob, parser):
            at = thermal_entry(parser, 2)
            blob[at:at + 2] = bytes((1, 1))
            struct.pack_into('<3h', blob, at + 2, 87 * 32, 75 * 32, 87 * 32)
        field = descriptors(fixture(mutate=second))['max_operating_temp_c']
        self.assertTrue(field['editable'])
        self.assertIn('entry 2 (87/75/87 C)', field['reason'])
        self.assertIn('raising this value may have no effect', field['reason'])

    def test_unrecognized_table_is_a_power_section_diagnostic(self):
        def entry_size(blob, parser):
            blob[parser.pointer('P', 0x50) + 2] = 47
        report = inspect_image(fixture(mutate=entry_size))
        self.assertNotIn('max_operating_temp_c', {f['key'] for f in report['fields']})
        self.assertIn('max_operating_temperature', {d.get('resolver') for d in report['diagnostics']})
        self.assertIn('power', unsupported_notes(report))

    def test_only_the_reviewed_binding_writes_the_thermal_table(self):
        image = fixture()
        parser = backend(image)
        at = thermal_entry(parser)
        binding = {b.descriptor['key']: b for b in registry.bindings(image, parser)[0]}['max_operating_temp_c']
        # The reviewed key over one word only is refused.
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'max_operating_temp_c': 85}, field_registry=custom_registry(
                'max_operating_temp_c', binding.offsets[:1], encoding='<h', scale=32,
                bounds={'minimum': 0, 'maximum': 200}))
        self.assertEqual(exc.exception.code, 'INVALID_FIELD_EVIDENCE')
        # An extension binding over the class byte or another entry is refused too.
        for offset, encoding in ((at, '<B'), (thermal_entry(parser, 1) + 2, '<h')):
            with self.subTest(offset=offset):
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {'probe': 0}, field_registry=custom_registry('probe', [offset], encoding=encoding,
                                                                            scale=1))
                self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')


class FactoryGpcOffsetTests(unittest.TestCase):
    def test_descriptor_edit_and_revert(self):
        image = fixture()
        fields = descriptors(image)
        offset, boost = fields['factory_gpc_offset_mhz'], fields['factory_rated_boost_mhz']
        self.assertEqual((offset['current'], offset['editable'], offset['units'], offset['stored_units'],
                          offset['experimental'], offset['rated_boost_mhz']), (120, True, 'MHz', 'kHz', True, 2655))
        self.assertEqual((offset['bounds']['minimum'], offset['bounds']['maximum']), (-500, 500))
        self.assertTrue(offset['unit_metadata']['storage_signed'])
        self.assertNotIn('opt_in', offset)
        self.assertEqual((boost['current'], boost['editable'], boost['reason']), (2655, False, FACTORY_BOOST_REASON))
        self.assertEqual({field_section(offset), field_section(boost)}, {'clocks'})
        parser = backend(image)
        at = parser.factory_clocks()['offsets'][0]['value_offset']
        for value in (-250, 0, 500, -500, 151):
            with self.subTest(value=value):
                result = edit(image, {'factory_gpc_offset_mhz': value})
                self.assertTrue(result.manifest['integrity']['valid'])
                self.assertEqual(struct.unpack_from('<i', result.blob, at)[0], int(Decimal(value) * 1000))
                # The binding covers the flag and the value: with the flag already 1 a value other than 0 changes
                # only the value, and 0 also clears the flag (flag 0 with 0 kHz, as ROMs without the offset store it).
                changed_bytes_within(self, image, result, [at - 1 if value == 0 else at], width=5 if value == 0 else 4)
                self.assertEqual(result.manifest['changed_object_ids'], [0x26])
                after = descriptors(result.image)
                self.assertEqual(Decimal(str(after['factory_gpc_offset_mhz']['current'])), Decimal(value))
                self.assertEqual(after['factory_rated_boost_mhz']['current'], 2655)
                self.assertEqual(result.blob[at - 1], 1 if value else 0)
                self.assertEqual(edit(result.image, {'factory_gpc_offset_mhz': 120}).blob, image.blob)
        # Whole MHz only: the driver truncates the kHz value to whole MHz.
        for value, code in ((Decimal('500.001'), 'OUT_OF_BOUNDS'), (-501, 'OUT_OF_BOUNDS'),
                            (Decimal('0.0001'), 'UNREPRESENTABLE_VALUE'), (Decimal('150.5'), 'UNREPRESENTABLE_VALUE'),
                            (Decimal('-0.5'), 'UNREPRESENTABLE_VALUE')):
            with self.subTest(value=value):
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {'factory_gpc_offset_mhz': value})
                self.assertEqual(exc.exception.code, code)
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'factory_rated_boost_mhz': 2700})
        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')

    def test_a_rom_without_the_offset_can_turn_it_on(self):
        def disabled(blob, parser):
            factory_entry(blob, parser, 'A', 0, 0, 0)
            factory_entry(blob, parser, 'B', 1, 0, 0)
        image = fixture(mutate=disabled)
        parser = backend(image)
        at = parser.factory_clocks()['offsets'][0]['offset']
        fields = descriptors(image)
        offset = fields['factory_gpc_offset_mhz']
        self.assertEqual((offset['current'], offset['editable'], offset['stored_flag'], offset['rated_boost_mhz']),
                         (0, True, 0, None))
        self.assertIn('turns one on', offset['reason'])
        self.assertNotIn('factory_rated_boost_mhz', fields)
        # A value other than 0 sets the flag; 0 keeps the stored bytes.
        result = edit(image, {'factory_gpc_offset_mhz': 50})
        self.assertEqual(result.blob[at:at + 5], struct.pack('<Bi', 1, 50000))
        changed_bytes_within(self, image, result, [at], width=5)
        self.assertEqual(result.manifest['changed_object_ids'], [0x26])
        self.assertEqual(edit(image, {'factory_gpc_offset_mhz': 0}).blob, image.blob)
        # Back to 0 on a saved copy: flag 0 with 0 kHz, the bytes of the ROM it came from.
        back = edit(result.image, {'factory_gpc_offset_mhz': 0})
        self.assertEqual(back.blob[at:at + 5], struct.pack('<Bi', 0, 0))
        self.assertEqual(back.blob, image.blob)
        self.assertEqual(descriptors(back.image)['factory_gpc_offset_mhz']['current'], 0)

    def test_an_ignored_stored_value_reads_as_zero_and_stays(self):
        # Flag 0 with a stored value (the TITAN RTX keeps 60 MHz): the driver skips it.
        image = fixture(mutate=lambda blob, parser: factory_entry(blob, parser, 'A', 0, 0, 60000))
        parser = backend(image)
        at = parser.factory_clocks()['offsets'][0]['offset']
        field = descriptors(image)['factory_gpc_offset_mhz']
        self.assertEqual((field['current'], field['editable'], field['stored_flag']), (0, True, 0))
        self.assertEqual(edit(image, {'factory_gpc_offset_mhz': 0}).blob, image.blob)
        self.assertEqual(edit(image, {'factory_gpc_offset_mhz': 30}).blob[at:at + 5], struct.pack('<Bi', 1, 30000))

    def test_a_stored_value_outside_the_range_stays_inside_the_bounds(self):
        image = fixture(mutate=lambda blob, parser: factory_entry(blob, parser, 'A', 0, 1, -600000))
        field = descriptors(image)['factory_gpc_offset_mhz']
        self.assertEqual((field['current'], field['bounds']['minimum'], field['bounds']['maximum']), (-600, -600, 500))
        at = backend(image).factory_clocks()['offsets'][0]['value_offset']
        self.assertEqual(struct.unpack_from('<i', edit(image, {'factory_gpc_offset_mhz': -550}).blob, at)[0], -550000)

    def test_a_stored_value_in_fractions_of_a_mhz_is_read_only(self):
        image = fixture(mutate=lambda blob, parser: factory_entry(blob, parser, 'A', 0, 1, 12500))
        field = descriptors(image)['factory_gpc_offset_mhz']
        self.assertEqual((field['current'], field['editable'], field['reason']),
                         (12.5, False, FACTORY_OFFSET_FRACTION_REASON))
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'factory_gpc_offset_mhz': 12})
        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')
        # The memory offset (A1, flag 0) stays editable.
        self.assertTrue(descriptors(image)['factory_memory_offset_mhz']['editable'])

    def test_unknown_flag_or_header_is_read_only_with_its_reason(self):
        def flag(blob, parser):
            factory_entry(blob, parser, 'A', 1, 2, 0)
        def header(blob, parser):
            blob[parser.pointer('P', 0x98) + 6] = 1
        for mutate in (flag, header):
            with self.subTest(mutate=mutate.__name__):
                image = fixture(mutate=mutate)
                report = inspect_image(image)
                fields = {f['key']: f for f in report['fields']}
                for key in OFFSETS:
                    self.assertEqual((fields[key]['current'], fields[key]['editable'], fields[key]['reason']),
                                     (None, False, FACTORY_UNREVIEWED_REASON))
                    with self.assertRaises(VbiosError) as exc:
                        edit(image, {key: 0})
                    self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')
                self.assertNotIn('factory_rated_boost_mhz', fields)
                self.assertNotIn('factory_clocks', {d.get('resolver') for d in report['diagnostics']})

    def test_only_the_reviewed_binding_writes_the_record(self):
        image = fixture()
        parser = backend(image)
        record = parser.factory_clocks()
        for offset, encoding in ((record['offsets'][0]['offset'], '<B'), (record['offsets'][1]['offset'], '<B'),
                                 (record['clocks'][1]['value_offset'], '<I'), (record['offset'] + 6, '<B')):
            with self.subTest(offset=offset):
                probe(self, image, [offset], encoding)
        # The reviewed key over the value bytes alone (without the flag) is refused.
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'factory_gpc_offset_mhz': 60}, field_registry=custom_registry(
                'factory_gpc_offset_mhz', [record['offsets'][0]['value_offset']], encoding='<i', scale=1000))
        self.assertEqual(exc.exception.code, 'INVALID_FIELD_EVIDENCE')

    def test_all_fields_in_one_edit(self):
        image = fixture()
        result = edit(image, {'factory_gpc_offset_mhz': 60, 'factory_memory_offset_mhz': -250,
                              'max_operating_temp_c': 80})
        self.assertEqual(sorted(result.manifest['changed_object_ids']), [0x1B, 0x26])
        self.assertTrue(result.manifest['integrity']['valid'])


class FactoryMemoryOffsetTests(unittest.TestCase):
    def test_descriptor_edit_and_revert(self):
        for image in (fixture(), legacy_fixture('ada'), legacy_fixture('ampere'), legacy_fixture('turing')):
            parser = backend(image)
            with self.subTest(family=getattr(parser, 'family', 'blackwell')):
                field = descriptors(image)['factory_memory_offset_mhz']
                self.assertEqual((field['current'], field['editable'], field['units'], field['stored_units'],
                                  field['experimental'], field['stored_flag']), (0, True, 'MHz', 'kHz', True, 0))
                self.assertEqual((field['bounds']['minimum'], field['bounds']['maximum']), (-5000, 5000))
                self.assertEqual(field_section(field), 'clocks')
                self.assertIn('nvidia-smi', field['reason'])
                self.assertIn('twice this number', field['reason'])
                binding = {b.descriptor['key']: b for b in registry.bindings(image, parser)[0]}[
                    'factory_memory_offset_mhz']
                at = parser.factory_clocks()['offsets'][1]['offset']
                for value in (-5000, 70, 5000):
                    result = edit(image, {'factory_memory_offset_mhz': value})
                    self.assertTrue(result.manifest['integrity']['valid'])
                    self.assertEqual(result.blob[at:at + 5], struct.pack('<Bi', 1, value * 1000))
                    self.assertLessEqual(changed(image, result), legacy_offsets(binding) | checksum_bytes(result) |
                                         {i for r in result.manifest['integrity_repairs'] if 'sha384' in r['kind']
                                          for i in range(r['offset'], r['offset'] + 48)})
                    self.assertEqual(descriptors(result.image)['factory_memory_offset_mhz']['current'], value)
                    # The GPC offset and the rated boost stay.
                    self.assertEqual(descriptors(result.image)['factory_gpc_offset_mhz']['current'],
                                     descriptors(image)['factory_gpc_offset_mhz']['current'])
                self.assertEqual(edit(image, {'factory_memory_offset_mhz': 0}).blob, image.blob)
                for value in (-5001, 5001, Decimal('70.5')):
                    with self.assertRaises(VbiosError) as exc:
                        edit(image, {'factory_memory_offset_mhz': value})
                    self.assertIn(exc.exception.code, ('OUT_OF_BOUNDS', 'UNREPRESENTABLE_VALUE'))

    def test_a_stored_memory_offset(self):
        # As on the two Turing ROMs that ship one (70 and 400 MHz); a stored value beyond 5000 MHz widens the range.
        for khz, bounds in ((70000, (-5000, 5000)), (6000000, (-5000, 6000))):
            image = legacy_fixture('turing', a1=(1, khz))
            field = descriptors(image)['factory_memory_offset_mhz']
            self.assertEqual((field['current'], field['stored_flag'], field['bounds']['minimum'],
                              field['bounds']['maximum']), (khz // 1000, 1, *bounds))
            # 0 turns it off (flag 0, 0 kHz); a value inside the range goes back to the stored bytes (a value outside
            # it, once changed, is outside the new bounds).
            parser = backend(image)
            at = parser.factory_clocks()['offsets'][1]['offset']
            self.assertEqual(edit(image, {'factory_memory_offset_mhz': 0}).blob[at:at + 5], struct.pack('<Bi', 0, 0))
            if khz <= 5000000:
                self.assertEqual(edit(edit(image, {'factory_memory_offset_mhz': 10}).image,
                                      {'factory_memory_offset_mhz': khz // 1000}).blob, image.blob)


class LegacyFieldTests(unittest.TestCase):
    """Turing, Ampere and Ada: the thermal policy table (v0x10) and the factory clock record."""

    def test_edited_tables_include_both_tables(self):
        for tables in (ADA_EDITED_TABLES, TURING_EDITED_TABLES):
            self.assertTrue({('P', 0x50), ('P', 0x98)} <= set(tables))

    def test_descriptors_per_family(self):
        for family, (device, stock, *_) in LEGACY_TABLES.items():
            with self.subTest(family=family):
                image = legacy_fixture(family)
                self.assertEqual(backend(image).family, family)
                fields = descriptors(image)
                temperature = fields['max_operating_temp_c']
                self.assertEqual((temperature['current'], temperature['editable'], temperature['stock_c'],
                                  temperature['thermal_policy'], temperature['experimental']),
                                 (stock, True, stock, 0, True))
                self.assertEqual((temperature['bounds']['minimum'], temperature['bounds']['maximum']),
                                 (40, stock + 3))
                self.assertIn('header byte 9', temperature['reason'])
                gpc, memory, boost = (fields[k] for k in OFFSETS + ('factory_rated_boost_mhz',))
                self.assertEqual((gpc['current'], gpc['editable'], gpc['rated_boost_mhz']), (60, True, 1800))
                self.assertEqual((gpc['bounds']['minimum'], gpc['bounds']['maximum']), (-500, 500))
                self.assertEqual((memory['current'], memory['editable']), (0, True))
                self.assertEqual((boost['current'], boost['editable'], boost['reason']),
                                 (1800, False, FACTORY_BOOST_REASON))

    def test_edits_write_every_chain_and_revert(self):
        for family in LEGACY_TABLES:
            image = legacy_fixture(family)
            parser = backend(image)
            self.assertEqual(len(parser.chains), 2)
            bindings = {b.descriptor['key']: b for b in registry.bindings(image, parser)[0]}
            stock = LEGACY_TABLES[family][1]
            for key, value, back in (('max_operating_temp_c', 40, stock), ('max_operating_temp_c', stock + 3, stock),
                                     ('factory_gpc_offset_mhz', -500, 60), ('factory_gpc_offset_mhz', 500, 60),
                                     ('factory_memory_offset_mhz', -5000, None)):
                with self.subTest(family=family, key=key, value=value):
                    binding = bindings[key]
                    self.assertEqual(len(binding.offsets), 2 * (3 if key == 'max_operating_temp_c' else 1))
                    result = edit(image, {key: value})
                    self.assertTrue(result.manifest['integrity']['valid'])
                    self.assertTrue(inspect_image(result.image)['integrity']['valid'])
                    self.assertLessEqual(changed(image, result), legacy_offsets(binding) | checksum_bytes(result))
                    # Every chain changed alike.
                    rest = changed(image, result) - checksum_bytes(result)
                    per_chain = [{at - chain[0]['start'] for at in rest if chain[0]['start'] <= at < chain[-1]['end']}
                                 for chain in parser.chains]
                    self.assertTrue(per_chain[0])
                    self.assertEqual(per_chain[1:], per_chain[:1] * (len(per_chain) - 1))
                    self.assertEqual(descriptors(result.image)[key]['current'], value)
                    if back is not None:
                        self.assertEqual(edit(result.image, {key: back}).blob, image.blob)
            for value in (Decimal(40) - Decimal(1) / 32, Decimal(stock + 3) + Decimal(1) / 32):
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {'max_operating_temp_c': value})
                self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_header_variants(self):
        # Ada header byte 6 (a clock flag GSP-RM keeps) may be 0 or 1 and stays as stored; Ampere keeps 0 and
        # Turing its six-byte header.
        def byte6(value):
            def mutate(blob, parser):
                for at in starts(parser, parser.pointer('P', 0x98) + 6):
                    blob[at] = value
            return mutate
        image = legacy_fixture('ada', mutate=byte6(1))
        record = backend(image).factory_clocks()
        self.assertEqual((record['reviewed'], record['header'][6]), (True, 1))
        result = edit(image, {'factory_memory_offset_mhz': 100})
        self.assertEqual(result.blob[record['offset'] + 6], 1)
        self.assertEqual(backend(legacy_fixture('turing')).factory_clocks()['size'], 26)
        for family, mutate in (('ada', byte6(2)), ('ampere', byte6(1))):
            with self.subTest(family=family):
                fields = descriptors(legacy_fixture(family, mutate=mutate))
                self.assertEqual({fields[key]['reason'] for key in OFFSETS}, {FACTORY_UNREVIEWED_REASON})
                self.assertNotIn('factory_rated_boost_mhz', fields)

    def test_flag_other_than_zero_or_one_is_read_only(self):
        image = legacy_fixture('ampere', a1=(3, 0))
        fields = descriptors(image)
        for key in OFFSETS:
            self.assertEqual((fields[key]['current'], fields[key]['editable'], fields[key]['reason']),
                             (None, False, FACTORY_UNREVIEWED_REASON))

    def test_an_unread_clocks_table_keeps_the_record_read_only(self):
        def clocks(blob, parser):
            for at in starts(parser, parser.pointer('C', 8)):
                blob[at + 8] ^= 0xFF  # an unreviewed clocks table header
        fields = descriptors(legacy_fixture('ada', mutate=clocks))
        self.assertEqual((fields['factory_gpc_offset_mhz']['current'], fields['factory_gpc_offset_mhz']['reason']),
                         (60, FACTORY_UNREVIEWED_REASON))
        self.assertFalse(fields['factory_memory_offset_mhz']['editable'])

    def test_laptop_layout(self):
        # Ampere and Ada laptops: the named entry (105 C on channel 1) and an 89 C entry no header byte names.
        image = legacy_fixture('ampere', laptop=True, device=0x249D)
        field = descriptors(image)['max_operating_temp_c']
        self.assertEqual((field['current'], field['editable'], field['reason'], field['lower_limits'],
                          field['stock_c']), (105, False, MAX_TEMP_LOWER_LIMIT_REASON, ['entry 1 (89 C)'], 105))
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'max_operating_temp_c': 100})
        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')
        # Without that entry (as on the Turing laptops) it is editable, up to 3 C above the product's 102 C.
        def disable(blob, parser):
            for at in starts(parser, thermal_entry(parser, 1)):
                blob[at] = 0
        field = descriptors(legacy_fixture('turing', laptop=True, device=0x1E90, mutate=disable))[
            'max_operating_temp_c']
        self.assertEqual((field['current'], field['editable'], field['bounds']['maximum']), (105, True, 105))
        # The nvidia-smi relation was checked on a channel 0 entry only: the note says so for a channel 1 entry.
        self.assertIn('another thermal channel, byte 1 = 1, where that was not checked', field['reason'])
        # An entry of the same kind above the named one (the desktop channel 1 entry) leaves it editable.
        desktop = descriptors(legacy_fixture('ada'))['max_operating_temp_c']
        self.assertTrue(desktop['editable'])
        self.assertIn('(nvidia-smi current temperature + T.Limit equals it)', desktop['reason'])

    def test_read_only_cases(self):
        def header9(value):
            def mutate(blob, parser):
                for at in starts(parser, parser.pointer('P', 0x50) + 9):
                    blob[at] = value
            return mutate
        def entry0(byte0):
            def mutate(blob, parser):
                for at in starts(parser, thermal_entry(parser)):
                    blob[at] = byte0
            return mutate
        cases = ((header9(0xFF), MAX_TEMP_NO_POLICY_REASON, None), (header9(7), MAX_TEMP_UNRECOGNIZED_REASON, None),
                 (entry0(0), MAX_TEMP_DISABLED_REASON, 93), (entry0(2), MAX_TEMP_UNRECOGNIZED_REASON, 93),
                 (set_temperatures(93 * 32, 80 * 32, 93 * 32), MAX_TEMP_UNEQUAL_REASON, 93))
        for mutate, reason, current in cases:
            with self.subTest(reason=reason):
                image = legacy_fixture('ampere', mutate=mutate)
                field = descriptors(image)['max_operating_temp_c']
                self.assertEqual((field['editable'], field['reason'], field['current']), (False, reason, current))
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {'max_operating_temp_c': 80})
                self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')
        # A product without a reviewed stock value can only lower it.
        field = descriptors(legacy_fixture('ada', device=0x28B8))['max_operating_temp_c']
        self.assertEqual((field['stock_c'], field['bounds']['maximum']), (None, 96))

    def test_unsupported_thermal_table_is_a_power_section_diagnostic(self):
        def entry_size(blob, parser):
            for at in starts(parser, parser.pointer('P', 0x50) + 2):
                blob[at] = 0x27
        report = inspect_image(legacy_fixture('turing', mutate=entry_size))
        self.assertNotIn('max_operating_temp_c', {f['key'] for f in report['fields']})
        self.assertIn('max_operating_temperature', {d.get('resolver') for d in report['diagnostics']})
        self.assertIn('power', unsupported_notes(report))

    def test_only_the_reviewed_bindings_write_the_tables(self):
        for family in LEGACY_TABLES:
            image = legacy_fixture(family)
            parser = backend(image)
            table, record = parser.thermal_policies(), parser.factory_clocks()
            probes = ((table['offset'] + 9, '<B'), (thermal_entry(parser), '<B'), (thermal_entry(parser, 1) + 2, '<h'),
                      (record['offsets'][0]['offset'], '<B'), (record['offsets'][1]['offset'], '<B'),
                      (record['clocks'][1]['value_offset'], '<I'))
            for offset, encoding in probes:
                with self.subTest(family=family, offset=offset):
                    probe(self, image, parser.copy_offsets(offset, 1), encoding)


class ImportTests(unittest.TestCase):
    def test_the_max_operating_temperature_is_never_imported(self):
        # Each product has its own limit: never copied, never listed as unchanged.
        for image in (fixture(), legacy_fixture('ada')):
            donor = edit(image, {'max_operating_temp_c': 80, 'factory_gpc_offset_mhz': 70}).image
            for target, other in ((image, donor), (donor, image)):
                report, imported = import_fields(target, other, ['power'], include_opt_in=True)
                self.assertIsNone(imported)
                self.assertEqual(report['changes'], {})
                self.assertEqual([(e['field'], e['reason']) for e in report['skipped']],
                                 [('max_operating_temp_c', 'product_specific')])
            report, _ = import_fields(image, image, ['power', 'clocks'])
            self.assertNotIn('max_operating_temp_c', report['unchanged'])
            self.assertTrue(set(OFFSETS) <= set(report['unchanged']))

    def test_the_factory_offsets_come_with_the_clock_offsets(self):
        image = fixture()
        at = backend(image).factory_clocks()['offsets'][0]['value_offset']
        donor = edit(image, {'factory_gpc_offset_mhz': -45, 'max_operating_temp_c': 80}).image
        # Not opt-in: the clocks section alone takes it, and only its value bytes and the hashes change.
        report, result = import_fields(image, donor, ['clocks'], dry_run=True)
        self.assertEqual((report['changes'], report['skipped'], report['warnings']),
                         ({'factory_gpc_offset_mhz': -45}, [], []))
        self.assertEqual(result.manifest['operation'], 'plan')
        report, result = import_fields(image, donor, ['clocks'])
        self.assertEqual([(e['field'], e['target'], e['donor']) for e in report['applied']],
                         [('factory_gpc_offset_mhz', 120, -45)])
        self.assertTrue(result.manifest['integrity']['valid'])
        self.assertEqual(struct.unpack_from('<i', result.blob, at)[0], -45000)
        self.assertEqual(result.blob[at - 1], 1)
        changed_bytes_within(self, image, result, [at], width=4)
        self.assertEqual(result.manifest['changed_object_ids'], [0x26])
        after = descriptors(result.image)
        self.assertEqual((after['factory_gpc_offset_mhz']['current'], after['max_operating_temp_c']['current'],
                          after['factory_rated_boost_mhz']['current']), (-45, 90, 2655))
        self.assertEqual(edit(result.image, {'factory_gpc_offset_mhz': 120}).blob, image.blob)
        # The other way back gives the original bytes; another section leaves it alone.
        report, result = import_fields(edit(image, {'factory_gpc_offset_mhz': -45}).image, image, ['clocks'])
        self.assertEqual((report['changes'], result.blob), ({'factory_gpc_offset_mhz': 120}, image.blob))
        report, result = import_fields(image, donor, ['power', 'voltage'])
        self.assertNotIn('factory_gpc_offset_mhz', [*report['changes'], *(e['field'] for e in report['skipped'])])
        # An equal value is unchanged.
        report, result = import_fields(image, fixture(), ['clocks'])
        self.assertEqual((report['changes'], report['skipped'], result), ({}, [], None))
        self.assertIn('factory_gpc_offset_mhz', report['unchanged'])

    def test_a_rom_without_a_factory_offset_gives_and_takes_one(self):
        def disabled(blob, parser):
            factory_entry(blob, parser, 'A', 0, 0, 0)
            factory_entry(blob, parser, 'B', 1, 0, 0)
        stored, none = fixture(), fixture(mutate=disabled)
        at = backend(stored).factory_clocks()['offsets'][0]['offset']
        # A donor that stores none (a Founders Edition, say) gives 0 MHz: flag 0 with 0 kHz, as the donor stores it.
        report, result = import_fields(stored, none, ['clocks'])
        self.assertEqual((report['changes'], report['skipped']), ({'factory_gpc_offset_mhz': 0}, []))
        self.assertEqual(result.blob[at:at + 5], struct.pack('<Bi', 0, 0))
        # A target that stores none takes the donor's, with the flag set.
        report, result = import_fields(none, stored, ['clocks'])
        self.assertEqual(report['changes'], {'factory_gpc_offset_mhz': 120})
        self.assertEqual(result.blob[at:at + 5], struct.pack('<Bi', 1, 120000))
        # Neither stores one: nothing to do.
        report, result = import_fields(none, none, ['clocks'])
        self.assertEqual((report['changes'], report['skipped'], result), ({}, [], None))
        self.assertTrue(set(OFFSETS) <= set(report['unchanged']))
        # A fraction of a MHz in the donor leaves the target's own.
        fraction = fixture(mutate=lambda blob, parser: factory_entry(blob, parser, 'A', 0, 1, 12500))
        report, result = import_fields(stored, fraction, ['clocks'])
        self.assertIsNone(result)
        self.assertEqual([(e['field'], e['reason']) for e in report['skipped']],
                         [('factory_gpc_offset_mhz', 'read_only_in_donor')])

    def test_the_factory_offsets_of_another_product_or_outside_the_range(self):
        # An RTX 5080 ROM's 30 MHz comes with the usual warning that its values were set for that product.
        other = fixture(device=0x2C02, mutate=lambda blob, parser: factory_entry(blob, parser, 'A', 0, 1, 30000))
        report, result = import_fields(fixture(), other, ['clocks'])
        self.assertEqual(report['changes'], {'factory_gpc_offset_mhz': 30})
        self.assertEqual([w['code'] for w in report['warnings']], ['DIFFERENT_DEVICE'])
        self.assertEqual(descriptors(result.image)['factory_gpc_offset_mhz']['current'], 30)
        # A stored -600 MHz is beyond this ROM's -500 MHz floor.
        low = fixture(mutate=lambda blob, parser: factory_entry(blob, parser, 'A', 0, 1, -600000))
        report, result = import_fields(fixture(), low, ['clocks'])
        self.assertIsNone(result)
        self.assertEqual([(e['field'], e['reason'], e['bounds']) for e in report['skipped']],
                         [('factory_gpc_offset_mhz', 'out_of_bounds', {'minimum': -500, 'maximum': 500})])

    def test_legacy_factory_memory_offset(self):
        # Ada: a donor's memory offset goes into another ROM of the family, in both chains.
        image = legacy_fixture('ada')
        donor = edit(image, {'factory_memory_offset_mhz': 250}).image
        report, result = import_fields(image, donor, ['clocks'])
        self.assertEqual((report['changes'], report['skipped']), ({'factory_memory_offset_mhz': 250}, []))
        self.assertEqual(result.blob, donor.blob)


class PresentationTests(unittest.TestCase):
    def test_labels_and_read_only_reasons_in_both_languages(self):
        image = fixture()
        fields = descriptors(image)
        labels = {('en', key): field_label(fields[key], 'en') for key in KEYS}
        labels.update({('es', key): field_label(fields[key], 'es') for key in KEYS})
        self.assertEqual(labels[('en', 'max_operating_temp_c')], 'Max operating temperature (experimental)')
        self.assertEqual(labels[('es', 'max_operating_temp_c')], 'Temperatura máxima de funcionamiento (experimental)')
        self.assertIn('vendor overclock', labels[('en', 'factory_gpc_offset_mhz')])
        self.assertIn('fábrica', labels[('es', 'factory_gpc_offset_mhz')])
        self.assertEqual(labels[('en', 'factory_memory_offset_mhz')],
                         'Factory memory offset (vendor overclock, experimental)')
        self.assertIn('memoria de fábrica', labels[('es', 'factory_memory_offset_mhz')])
        self.assertNotEqual(labels[('en', 'factory_gpc_offset_mhz')], field_label(dict(key='gpc_curve_offset_mhz')))
        for reason in (MAX_TEMP_DISABLED_REASON, MAX_TEMP_UNEQUAL_REASON, MAX_TEMP_UNRECOGNIZED_REASON,
                       MAX_TEMP_NO_POLICY_REASON, MAX_TEMP_LOWER_LIMIT_REASON, FACTORY_OFFSET_FRACTION_REASON,
                       FACTORY_UNREVIEWED_REASON, FACTORY_BOOST_REASON):
            with self.subTest(reason=reason):
                english, spanish = (read_only_reason(dict(reason=reason), lang) for lang in ('en', 'es'))
                generic = read_only_reason(dict(reason='unmapped'), 'es')
                self.assertTrue(english and spanish and spanish != generic and english != spanish)


if __name__ == '__main__':
    unittest.main()
