"""Import from another ROM: the values of chosen sections go through edit(), a dependent set at a time."""
import os
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nvidia_vbios.editor import IMPORT_SECTIONS, VbiosError, edit, import_fields, load
from nvidia_vbios.editor.sections import field_section, technical_field_keys
from nvidia_vbios.rom import from_bytes
from nvidia_vbios.rom.image import backend
from test_rom_formats import synthetic_blackwell, synthetic_rom

# Fan 1's maximum lowered with every curve point above it: alone it would be below the stored curves.
QUIETER = {'fan_1_max_rpm': 3000, 'fan_1_curve_3_rpm': 3000, 'fan_extra_1_curve_3_rpm': 3000,
           'fan_extra_2_curve_3_rpm': 3000}


def donor_of(blob, *stages):
    """Another board's image: blob after each change set in turn, as separate edits."""
    image = from_bytes(blob, 'other board.rom')
    for changes in stages:
        image = edit(image, changes).image
    return image


def values(image):
    return {f['key']: f['current'] for f in image.report['fields']}


class FakeDonor:
    """A donor whose descriptors differ from image's as given: {key: updates, or None to drop the field}."""

    def __init__(self, image, changes):
        self.name, self.sha256 = 'other board.rom', image.sha256
        report = image.report
        known = {f['key'] for f in report['fields']}
        fields = [dict(f, **changes.get(f['key'], {})) for f in report['fields']
                  if changes.get(f['key'], {}) is not None]
        self.report = dict(report, fields=fields + [dict(c, key=k) for k, c in changes.items() if k not in known])


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.blob = synthetic_blackwell(fans=True)
        self.target = from_bytes(self.blob, 'board.rom')

    def test_only_the_chosen_sections_are_imported_and_fan_partners_go_together(self):
        donor = donor_of(self.blob, dict(QUIETER, power_max_w=120, gpc_offset_max_mhz=2500))
        report, result = import_fields(self.target, donor, ['fans'])
        self.assertEqual((report['changes'], report['skipped'], report['warnings']), (QUIETER, [], []))
        self.assertEqual([e['field'] for e in report['applied']], list(QUIETER))
        after = values(result.image)
        self.assertEqual({key: after[key] for key in QUIETER}, QUIETER)
        self.assertEqual((after['power_max_w'], after['gpc_offset_max_mhz']), (100.0, 3000))
        self.assertEqual(result.manifest['operation'], 'edit')
        report, result = import_fields(self.target, donor, ('power', 'clocks', 'power'), dry_run=True)
        self.assertEqual(report['changes'], {'power_max_w': 120, 'gpc_offset_max_mhz': 2500})
        self.assertEqual((report['sections'], result.manifest['operation']), (['power', 'clocks'], 'plan'))
        self.assertEqual(self.target.blob, self.blob)

    def test_opt_in_fields_are_imported_only_when_included(self):
        # Fan curve levels are the exception: they come with their curve (test_a_set_waits_for_its_differing...).
        donor = donor_of(self.blob, {'fan_zero_rpm': 1, 'board_fixed_rated_w': 80})
        report, result = import_fields(self.target, donor, ['fans', 'power'])
        self.assertIsNone(result)
        self.assertEqual([(e['field'], e['reason']) for e in report['skipped']],
                         [('board_fixed_rated_w', 'opt_in'), ('fan_zero_rpm', 'opt_in')])
        report, result = import_fields(self.target, donor, ['fans', 'power'], include_opt_in=True)
        self.assertEqual((report['changes'], report['skipped']), ({'board_fixed_rated_w': 80, 'fan_zero_rpm': 1}, []))
        self.assertEqual(values(result.image)['fan_zero_rpm'], 1)

    def test_a_set_waits_for_its_differing_opt_in_partner(self):
        # Without the fixed board policies the lower ceiling would leave them above it, a mix of both ROMs.
        # A fan curve point comes whole with its level, an advanced field that comes with its curve all the same.
        lower, point = {'power_max_w': 65, 'power_default_w': 60}, {'fan_1_curve_2_rpm': 2000, 'fan_1_curve_2_pct': 40}
        donor = donor_of(self.blob, dict(lower, board_fixed_rated_w=60, **point))
        report, result = import_fields(self.target, donor, ['power', 'fans'])
        self.assertEqual(report['changes'], point)
        self.assertEqual({e['field']: (e['reason'], e.get('partners')) for e in report['skipped']},
                         {'power_max_w': ('held_back', ['board_fixed_rated_w']),
                          'power_default_w': ('held_back', ['board_fixed_rated_w']),
                          'board_fixed_rated_w': ('opt_in', None)})
        self.assertEqual(values(result.image)['fan_1_curve_2_pct'], 40)
        report, result = import_fields(self.target, donor, ['power', 'fans'], include_opt_in=True)
        self.assertEqual((report['changes'], report['skipped']), (dict(lower, board_fixed_rated_w=60, **point), []))

    def test_a_notebook_base_tgp_comes_with_the_notebook_board_power(self):
        # The base TGP is an opt-in member of the board power set: a donor's edited base left out holds back the
        # ceiling it was raised with, as the fixed board policies' rated power does on a desktop.
        from test_extended_fields import notebook_fixture
        target = from_bytes(notebook_fixture(base=150000), 'laptop.rom')
        donor = donor_of(notebook_fixture(base=150000), {'power_max_w': 225, 'notebook_base_tgp_w': 200})
        report, result = import_fields(target, donor, ['power'])
        self.assertIsNone(result)
        self.assertEqual({e['field']: (e['reason'], e.get('partners')) for e in report['skipped']},
                         {'power_max_w': ('held_back', ['notebook_base_tgp_w']),
                          'notebook_base_tgp_w': ('opt_in', None)})
        report, result = import_fields(target, donor, ['power'], include_opt_in=True)
        self.assertEqual((report['changes'], report['skipped']), ({'power_max_w': 225, 'notebook_base_tgp_w': 200}, []))
        self.assertEqual((values(result.image)['power_max_w'], values(result.image)['notebook_base_tgp_w']), (225, 200))

    def test_a_notebook_rom_edited_past_the_base_tgp_by_an_earlier_release_imports_as_before(self):
        # Earlier releases left row 2 +73 at 150000 under a 140 W ceiling or a 160 W boot default, as an edit without
        # the base TGP still does. Such a donor has no base TGP field and its values come over as before; a stock
        # donor brings such a ROM back, base TGP field included.
        from test_extended_fields import notebook_fixture
        target = from_bytes(notebook_fixture(base=150000), 'laptop.rom')
        at = backend(target).power_rows()[2]['offset'] + 73
        for changes in ({'power_max_w': 140}, {'power_default_w': 160}, {'power_max_w': 120, 'power_default_w': 100}):
            with self.subTest(changes=changes):
                donor = donor_of(notebook_fixture(base=150000), changes)
                self.assertEqual(donor.blob[at:at + 4], target.blob[at:at + 4])
                self.assertNotIn('notebook_base_tgp_w', values(donor))
                for opt_in in (False, True):
                    report, result = import_fields(target, donor, ['power'], include_opt_in=opt_in)
                    self.assertEqual(report['changes'], changes)
                    self.assertEqual({e['field']: e['reason'] for e in report['skipped']},
                                     {'notebook_base_tgp_w': 'absent_in_donor'} if opt_in else {})
                    self.assertEqual({key: values(result.image)[key] for key in changes}, changes)
                    self.assertEqual(result.blob[at:at + 4], target.blob[at:at + 4])
                    self.assertNotIn('notebook_base_tgp_w', values(result.image))
                report, result = import_fields(donor, target, ['power'], include_opt_in=True)
                self.assertEqual({e['field']: e['reason'] for e in report['skipped']},
                                 {'notebook_base_tgp_w': 'absent_in_target'})
                self.assertEqual(result.blob, target.blob)
                self.assertEqual(values(result.image)['notebook_base_tgp_w'], 150)

    def test_a_set_comes_whole_from_one_rom(self):
        # A curve temperature read-only in both ROMs holds back the speed of its curve; a read-only field
        # outside any set is not listed.
        target = FakeDonor(self.target, {'fan_1_curve_2_temp_c': dict(editable=False)})
        donor = FakeDonor(self.target, {'fan_1_curve_2_temp_c': dict(current=57.0, editable=False),
                                        'fan_1_curve_2_rpm': dict(current=2000),
                                        'nvvdd_vmin_equation_max_mv': dict(current=950.0)})
        report, result = import_fields(target, donor, ['fans', 'voltage'])
        self.assertIsNone(result)
        self.assertEqual([(e['field'], e['reason'], e.get('partners')) for e in report['skipped']],
                         [('fan_1_curve_2_temp_c', 'read_only', None),
                          ('fan_1_curve_2_rpm', 'held_back', ['fan_1_curve_2_temp_c'])])
        # So does a speed outside this ROM's encoding.
        donor = FakeDonor(self.target, {'fan_1_curve_2_rpm': dict(current=2000),
                                        'fan_1_curve_3_rpm': dict(current=40000)})
        report, result = import_fields(self.target, donor, ['fans'])
        self.assertIsNone(result)
        self.assertEqual([(e['field'], e['reason'], e.get('partners')) for e in report['skipped']],
                         [('fan_1_curve_2_rpm', 'held_back', ['fan_1_curve_3_rpm']),
                          ('fan_1_curve_3_rpm', 'out_of_bounds', None)])

    def test_the_fan_channel_count_is_never_copied(self):
        donor = donor_of(self.blob, {'fan_channels': 1}, {'fan_1_curve_2_rpm': 2000})
        for include in (False, True):
            with self.subTest(include_opt_in=include):
                report, result = import_fields(self.target, donor, ['fans'], include_opt_in=include)
                skipped = {e['field']: e['reason'] for e in report['skipped']}
                self.assertEqual((skipped['fan_channels'], skipped['fan_2_max_rpm']),
                                 ('board_specific', 'absent_in_donor'))
                self.assertEqual(report['changes'], {'fan_1_curve_2_rpm': 2000})
                self.assertEqual(values(result.image)['fan_channels'], 2)

    def test_a_refused_unit_is_reported_whole_and_none_of_it_applied(self):
        # With one channel the donor's extra curves top out at 4000 RPM; here fan 2 still has a 3500 RPM maximum.
        # The temperature that comes with them is part of the same curve.
        high = {'fan_1_max_rpm': 4000, 'fan_1_curve_3_rpm': 4000, 'fan_extra_1_curve_3_rpm': 4000,
                'fan_extra_2_curve_3_rpm': 4000}
        donor = donor_of(self.blob, {'fan_channels': 1},
                         dict(high, fan_1_curve_1_temp_c=45.0, fan_pwm_frequency_hz=25000))
        report, result = import_fields(self.target, donor, ['fans'])
        refused = {e['field']: e['code'] for e in report['skipped'] if e['reason'] == 'refused'}
        self.assertEqual(refused, {key: 'OUT_OF_BOUNDS' for key in [*high, 'fan_1_curve_1_temp_c']})
        self.assertEqual(next(e['reason'] for e in report['skipped'] if e['field'] == 'fan_channels'),
                         'board_specific')
        self.assertEqual(report['changes'], {'fan_pwm_frequency_hz': 25000})
        after = values(result.image)
        self.assertEqual((after['fan_pwm_frequency_hz'], after['fan_1_max_rpm'], after['fan_1_curve_1_temp_c']),
                         (25000, 3500, 50.0))
        # Extra curves may start below a channel minimum: a 900 RPM start comes whole, fan 2 keeps its 1050 RPM.
        low = {'fan_1_min_rpm': 900, 'fan_1_curve_1_rpm': 900, 'fan_extra_1_curve_1_rpm': 900,
               'fan_extra_2_curve_1_rpm': 900}
        report, result = import_fields(self.target, donor_of(self.blob, {'fan_channels': 1}, low), ['fans'])
        self.assertEqual(report['changes'], low)
        self.assertEqual(values(result.image)['fan_2_min_rpm'], 1050)

    def test_each_skipped_field_has_its_reason(self):
        donor = FakeDonor(self.target, {
            'fan_pwm_frequency_hz': dict(current=30000),                 # outside the 21-28 kHz band
            'fan_channels': dict(current=1),
            'gpc_offset_max_mhz': dict(current=2500, editable=False),
            'gpc_offset_min_mhz': dict(current=-500, units='table MHz'),
            'power_max_w': dict(current=150.0, notebook_tgp=True),     # a notebook TGP
            'nvvdd_alt_equation_max_mv': dict(current=1200.0, equation_offset=1),   # its own equation there
            'msvdd_rel_equation_max_mv': dict(current=1100.0, equation_type=7),
            'nvvdd_vmin_equation_max_mv': dict(current=950.0, editable=True),
            'xbar_max_table_mhz': None,
            'fan_3_max_rpm': dict(label='Fan 3 maximum speed', units='RPM', current=3000, editable=True,
                                  bounds={'minimum': 0, 'maximum': 32767})})
        report, result = import_fields(self.target, donor, ['power', 'clocks', 'fans', 'voltage'])
        self.assertIsNone(result)
        self.assertEqual({e['field']: e['reason'] for e in report['skipped']},
                         {'fan_pwm_frequency_hz': 'out_of_bounds', 'fan_channels': 'board_specific',
                          'gpc_offset_max_mhz': 'read_only_in_donor', 'gpc_offset_min_mhz': 'different_meaning',
                          'power_max_w': 'different_meaning', 'nvvdd_alt_equation_max_mv': 'different_meaning',
                          'msvdd_rel_equation_max_mv': 'different_meaning', 'xbar_max_table_mhz': 'absent_in_donor',
                          'nvvdd_vmin_equation_max_mv': 'read_only_in_target', 'fan_3_max_rpm': 'absent_in_target'})
        pwm = next(e for e in report['skipped'] if e['field'] == 'fan_pwm_frequency_hz')
        self.assertEqual((pwm['bounds'], pwm['target'], pwm['donor']),
                         ({'minimum': 21000, 'maximum': 28000}, 27000, 30000))

    def test_a_refusal_naming_no_field_keeps_the_units_the_editor_accepts(self):
        from nvidia_vbios.editor import transfer
        donor = donor_of(self.blob, {'gpc_offset_max_mhz': 2500, 'memory_offset_max_mhz': 8000})

        def refusing(image, changes, **options):
            if 'gpc_offset_max_mhz' in changes:
                raise VbiosError('PRESERVED_FIELD_CHANGED', 'a check that names no field')
            return edit(image, changes, **options)
        with patch.object(transfer, 'edit', refusing):
            report, result = import_fields(self.target, donor, ['clocks'])
        self.assertEqual(report['changes'], {'memory_offset_max_mhz': 8000})
        self.assertEqual([(e['field'], e['reason'], e['code']) for e in report['skipped']],
                         [('gpc_offset_max_mhz', 'refused', 'PRESERVED_FIELD_CHANGED')])
        self.assertEqual(values(result.image)['gpc_offset_max_mhz'], 3000)

    def test_a_curve_below_the_zero_rpm_upper_comes_only_with_its_pair(self):
        # With zero RPM on, an upper stays at most point 1 of its curve: a donor curve that starts lower than this
        # ROM's upper is refused alone and comes with the donor's pair, an advanced field, or with zero RPM off.
        # The refusal names those advanced fields, and the summary says to import again with them.
        from nvidia_vbios.gui.presentation import Messages, import_summary
        from test_extended_fields import repair_fixture
        blob = bytearray(self.blob)
        table = backend(from_bytes(bytes(blob))).fan_coolers()
        for entry in table['rows'][:3] + table['extra_curves']:
            blob[entry['policy_offset'] + 0x32] = 0x17 if entry['index'] < 4 else 0x07
        target = from_bytes(repair_fixture(blob), 'board.rom')
        fields, hint = {f['key']: f for f in target.report['fields']}, Messages('en')('import.opt_in_hint')
        for stages, partner in (([{'fan_1_curve_1_temp_c': 45, 'fan_1_zero_rpm_high_temp_c': 45}],
                                 {'fan_1_zero_rpm_high_temp_c': 45.0}),
                                ([{'fan_zero_rpm': 0}, {'fan_1_curve_1_temp_c': 45}], {'fan_zero_rpm': 0})):
            with self.subTest(partner=partner):
                donor = donor_of(target.blob, *stages)
                report, result = import_fields(target, donor, ['fans'])
                self.assertIsNone(result)
                refused = next(e for e in report['skipped'] if e['field'] == 'fan_1_curve_1_temp_c')
                self.assertEqual((refused['reason'], refused['code'], refused['partners']),
                                 ('refused', 'ZERO_RPM_ABOVE_CURVE', list(partner)))
                self.assertIn('fan_1_zero_rpm_high_temp_c', refused['message'])
                self.assertIn((hint, 'detail'), import_summary(report, fields))
                report, result = import_fields(target, donor, ['fans'], include_opt_in=True)
                self.assertEqual(report['changes'], dict(partner, fan_1_curve_1_temp_c=45.0))
                self.assertEqual(values(result.image)['fan_1_curve_1_temp_c'], 45.0)
        # A donor curve below its own upper (a board shipped that way): the advanced fields would not help.
        donor = FakeDonor(target, {'fan_1_curve_1_temp_c': dict(current=45.0)})
        report, result = import_fields(target, donor, ['fans'])
        refused = next(e for e in report['skipped'] if e['field'] == 'fan_1_curve_1_temp_c')
        self.assertEqual((refused['code'], 'partners' in refused), ('ZERO_RPM_ABOVE_CURVE', False))
        self.assertNotIn((hint, 'detail'), import_summary(report, fields))

    def test_other_families_are_refused_and_other_products_warned(self):
        for other in (synthetic_rom(), synthetic_rom(family='ampere')):
            with self.assertRaises(VbiosError) as exc:
                import_fields(self.target, from_bytes(other), ['power'])
            self.assertEqual(exc.exception.code, 'FAMILY_MISMATCH')
        with self.assertRaises(VbiosError) as exc:              # Ada and Ampere share the format, not the family
            import_fields(from_bytes(synthetic_rom()), from_bytes(synthetic_rom(family='ampere')), ['power'])
        self.assertEqual(exc.exception.code, 'FAMILY_MISMATCH')
        not_a_rom = from_bytes(b'not a rom' * 512, 'notes.txt')
        with self.assertRaises(VbiosError) as exc:
            import_fields(not_a_rom, not_a_rom, ['power'])
        self.assertEqual(exc.exception.code, 'FAMILY_MISMATCH')
        self.assertIn('this ROM is not a recognized ROM', str(exc.exception))
        target = from_bytes(synthetic_rom(family='ampere'))
        donor = edit(from_bytes(synthetic_rom(family='ampere', device=0x2206)), {'power_max_w': 80}).image
        report, _ = import_fields(target, donor, ['power'])
        self.assertEqual([w['code'] for w in report['warnings']], ['DIFFERENT_DEVICE'])
        self.assertEqual(report['changes'], {'power_max_w': 80})
        for sections in (['fans', 'memory'], [], 'other'):
            with self.subTest(sections=sections), self.assertRaises(VbiosError) as exc:
                import_fields(target, donor, sections)
            self.assertEqual(exc.exception.code, 'INVALID_SECTIONS')


if __name__ == '__main__':
    unittest.main()
