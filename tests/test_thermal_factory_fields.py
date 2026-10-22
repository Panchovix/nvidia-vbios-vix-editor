"""GB20x max operating temperature and factory GPC offset: synthetic images and opt-in reference ROMs."""
from decimal import Decimal
import os
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nvidia_vbios.editor import edit, import_fields
from nvidia_vbios.editor.registry import (FACTORY_BOOST_REASON, FACTORY_OFFSET_DISABLED_REASON,
                                          FACTORY_OFFSET_FRACTION_REASON, MAX_TEMP_DISABLED_REASON,
                                          MAX_TEMP_UNEQUAL_REASON, MAX_TEMP_UNRECOGNIZED_REASON, registry)
from nvidia_vbios.gui.presentation import field_label, field_section, read_only_reason, unsupported_notes
from nvidia_vbios.rom import from_bytes, inspect_image, load, VbiosError
from nvidia_vbios.rom.image import backend
from test_extended_fields import changed_bytes_within, custom_registry, descriptors, repair_fixture, set_device
from test_rom_formats import synthetic_blackwell

KEYS = ('max_operating_temp_c', 'factory_gpc_offset_mhz', 'factory_rated_boost_mhz')


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


def set_temperatures(*celsius_32):
    def mutate(blob, parser):
        struct.pack_into('<3h', blob, thermal_entry(parser) + 2, *celsius_32)
    return mutate


def factory_entry(blob, parser, array, index, flag, khz):
    record = parser.factory_clocks()
    entry = record['offsets' if array == 'A' else 'clocks'][index]['offset']
    struct.pack_into('<BI' if array == 'B' or khz >= 0 else '<Bi', blob, entry, flag, khz)


def changed(before, after):
    return {i for i, (a, b) in enumerate(zip(before.blob, after.blob)) if a != b}


class MaxOperatingTemperatureTests(unittest.TestCase):
    def test_absent_tables_add_no_field_and_no_diagnostic(self):
        report = inspect_image(from_bytes(synthetic_blackwell()))
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
                changed_bytes_within(self, image, result, [at], width=4)
                self.assertEqual(result.manifest['changed_object_ids'], [0x26])
                after = descriptors(result.image)
                self.assertEqual(Decimal(str(after['factory_gpc_offset_mhz']['current'])), Decimal(value))
                self.assertEqual(after['factory_rated_boost_mhz']['current'], 2655)
                # The flag byte stays 1.
                self.assertEqual(result.blob[at - 1], 1)
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

    def test_disabled_entry_is_read_only_and_never_enabled(self):
        def disabled(blob, parser):
            factory_entry(blob, parser, 'A', 0, 0, 0)
            factory_entry(blob, parser, 'B', 1, 0, 0)
        image = fixture(mutate=disabled)
        fields = descriptors(image)
        offset = fields['factory_gpc_offset_mhz']
        self.assertEqual((offset['current'], offset['editable'], offset['reason']),
                         (0, False, FACTORY_OFFSET_DISABLED_REASON))
        self.assertNotIn('factory_rated_boost_mhz', fields)
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'factory_gpc_offset_mhz': 50})
        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')

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

    def test_unknown_flag_or_header_is_a_clocks_diagnostic(self):
        def flag(blob, parser):
            factory_entry(blob, parser, 'A', 0, 2, 120000)
        def header(blob, parser):
            blob[parser.pointer('P', 0x98) + 6] = 1
        for mutate in (flag, header):
            with self.subTest(mutate=mutate.__name__):
                report = inspect_image(fixture(mutate=mutate))
                self.assertFalse({'factory_gpc_offset_mhz', 'factory_rated_boost_mhz'} &
                                 {f['key'] for f in report['fields']})
                self.assertIn('factory_clocks', {d.get('resolver') for d in report['diagnostics']})
                self.assertIn('clocks', unsupported_notes(report))

    def test_only_the_reviewed_binding_writes_the_record(self):
        image = fixture()
        parser = backend(image)
        record = parser.factory_clocks()
        for offset, encoding in ((record['offsets'][0]['offset'], '<B'), (record['clocks'][1]['value_offset'], '<I')):
            with self.subTest(offset=offset):
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {'probe': 0}, field_registry=custom_registry('probe', [offset], encoding=encoding,
                                                                            scale=1))
                self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')

    def test_both_fields_in_one_edit(self):
        image = fixture()
        result = edit(image, {'factory_gpc_offset_mhz': 60, 'max_operating_temp_c': 80})
        self.assertEqual(sorted(result.manifest['changed_object_ids']), [0x1B, 0x26])
        self.assertTrue(result.manifest['integrity']['valid'])


class ImportTests(unittest.TestCase):
    def test_the_max_operating_temperature_is_never_imported(self):
        # Each product has its own limit: never copied, never listed as unchanged.
        image = fixture()
        donor = edit(image, {'max_operating_temp_c': 80, 'factory_gpc_offset_mhz': 60}).image
        for target, other in ((image, donor), (donor, image)):
            report, imported = import_fields(target, other, ['power'], include_opt_in=True)
            self.assertIsNone(imported)
            self.assertEqual(report['changes'], {})
            self.assertEqual([(e['field'], e['reason']) for e in report['skipped']],
                             [('max_operating_temp_c', 'product_specific')])
        report, _ = import_fields(image, image, ['power', 'clocks'])
        self.assertNotIn('max_operating_temp_c', report['unchanged'])
        self.assertIn('factory_gpc_offset_mhz', report['unchanged'])

    def test_the_factory_offset_comes_with_the_clock_offsets(self):
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

    def test_the_factory_offset_needs_both_roms_to_store_one(self):
        def disabled(blob, parser):
            factory_entry(blob, parser, 'A', 0, 0, 0)
            factory_entry(blob, parser, 'B', 1, 0, 0)
        stored, none = fixture(), fixture(mutate=disabled)
        fraction = fixture(mutate=lambda blob, parser: factory_entry(blob, parser, 'A', 0, 1, 12500))
        # A donor without one (a Founders Edition, say) or with a fraction of a MHz leaves this ROM's own; a
        # target without one never gains one, since the editor never enables A0.
        for case, target, donor, reason in (('none', stored, none, 'read_only_in_donor'),
                                            ('fraction', stored, fraction, 'read_only_in_donor'),
                                            ('target', none, stored, 'read_only_in_target')):
            with self.subTest(case=case):
                report, result = import_fields(target, donor, ['clocks'])
                self.assertIsNone(result)
                self.assertEqual([(e['field'], e['reason']) for e in report['skipped']],
                                 [('factory_gpc_offset_mhz', reason)])
                self.assertNotIn('factory_gpc_offset_mhz', report['unchanged'])
        # Neither stores one: nothing to say.
        report, result = import_fields(none, none, ['clocks'])
        self.assertEqual((report['changes'], report['skipped'], result), ({}, [], None))
        self.assertNotIn('factory_gpc_offset_mhz', report['unchanged'])

    def test_the_factory_offset_of_another_product_or_outside_the_range(self):
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
        self.assertNotEqual(labels[('en', 'factory_gpc_offset_mhz')], field_label(dict(key='gpc_curve_offset_mhz')))
        for reason in (MAX_TEMP_DISABLED_REASON, MAX_TEMP_UNEQUAL_REASON, MAX_TEMP_UNRECOGNIZED_REASON,
                       FACTORY_OFFSET_DISABLED_REASON, FACTORY_OFFSET_FRACTION_REASON, FACTORY_BOOST_REASON):
            with self.subTest(reason=reason):
                english, spanish = (read_only_reason(dict(reason=reason), lang) for lang in ('en', 'es'))
                generic = read_only_reason(dict(reason='unmapped'), 'es')
                self.assertTrue(english and spanish and spanish != generic and english != spanish)


if __name__ == '__main__':
    unittest.main()
