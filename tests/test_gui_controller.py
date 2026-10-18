"""GUI behavior against real immutable editor bytes, without GTK."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from nvidia_vbios.editor import VbiosError
from nvidia_vbios.gui.controller import Controller, controls, stage_document
from test_rom_formats import synthetic_rom, synthetic_blackwell


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.rom'
        self.source.write_bytes(synthetic_rom(copies=2))
        self.controller = Controller()
        self.controller.open(self.source)

    def test_open_stage_preview_reset_save_source_immutable(self):
        original = self.source.read_bytes()
        doc = self.controller.stage({'power_max_w': '100', 'nvvdd_rel_equation_max_mv': '1100'})
        from nvidia_vbios.gui.presentation import primary_preview
        self.assertEqual({a['key'] for a, b in primary_preview(doc)}, {'power_max_w', 'nvvdd_rel_equation_max_mv'})
        self.assertEqual(doc.original.blob, original)
        output = self.root / 'new.rom'
        saved = self.controller.save(output)
        self.assertEqual(output.read_bytes(), doc.proposal.blob)
        manifest = json.loads(Path(saved['manifest']).read_text())
        self.assertFalse(manifest['runtime_validation']['new_edit_hardware_tested'])
        self.assertEqual(self.source.read_bytes(), original)
        reset = self.controller.reset()
        self.assertFalse(reset.changes)
        self.assertIsNone(reset.proposal)
        self.assertEqual(reset.original.blob, original)

    def test_failed_save_keeps_verified_stage(self):
        staged = self.controller.stage({'power_max_w': 100})
        destination = self.root / 'existing.rom'
        destination.write_bytes(b'other')
        with self.assertRaises(VbiosError) as exc:
            self.controller.save(destination)
        self.assertEqual(exc.exception.code, 'OUTPUT_EXISTS')
        self.assertIs(self.controller.document, staged)
        self.assertEqual(destination.read_bytes(), b'other')
        with self.assertRaises(VbiosError) as exc:
            self.controller.save(self.source)
        self.assertEqual(exc.exception.code, 'SOURCE_OVERWRITE')
        self.source.write_bytes(b'changed externally')
        with self.assertRaises(VbiosError) as exc:
            self.controller.save(self.root / 'refused.rom')
        self.assertEqual(exc.exception.code, 'SOURCE_CHANGED')
        self.assertIs(self.controller.document, staged)
        self.assertFalse((self.root / 'refused.rom').exists())

    def test_an_existing_loader_file_refuses_the_whole_save(self):
        self.controller.stage({'power_max_w': 100})
        for name in ('new-loader.bin', 'new-loader.bin.json'):
            with self.subTest(existing=name):
                existing = self.root / name
                existing.write_bytes(b'older copy')
                with self.assertRaises(VbiosError) as exc:
                    self.controller.save(self.root / 'new.rom')
                self.assertEqual(exc.exception.code, 'LOADER_OUTPUT_EXISTS')
                self.assertFalse((self.root / 'new.rom').exists())
                self.assertEqual(existing.read_bytes(), b'older copy')
                existing.unlink()
        # The synthetic Ada image does not relocate: the copy is saved and the reason reported.
        saved = self.controller.save(self.root / 'new.rom')
        self.assertIn('error', saved['loader'])
        self.assertFalse((self.root / 'new-loader.bin').exists())
        blackwell = self.root / 'gb.rom'
        blackwell.write_bytes(synthetic_blackwell())
        self.controller.open(blackwell)
        self.controller.stage({'power_max_w': 500})
        (self.root / 'gb-copy-loader.bin').write_bytes(b'unrelated')
        self.assertIsNone(self.controller.save(self.root / 'gb-copy.rom')['loader'])

    def test_failed_open_and_invalid_stage_keep_previous_document(self):
        staged = self.controller.stage({'power_max_w': 100})
        with self.assertRaises(VbiosError):
            self.controller.open(self.root / 'missing')
        self.assertIs(self.controller.document, staged)
        for changes, code in (({'current_limit_a': 5}, 'FIELD_READ_ONLY'),
                              ({'ocp_limit_a': 5}, 'FIELD_READ_ONLY'),
                              ({'invented': 1}, 'UNKNOWN_FIELD'),
                              ({'power_max_w': 'nan'}, 'INVALID_VALUE'),
                              ({'power_max_w': True}, 'INVALID_VALUE'),
                              ({'power_max_w': '100.0001'}, 'UNREPRESENTABLE_VALUE')):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                self.controller.stage(changes)
            self.assertEqual(exc.exception.code, code)
            self.assertIs(self.controller.document, staged)

    def test_stage_rebuilds_from_original_and_can_revert_value(self):
        original = self.controller.document.original
        self.controller.stage({'power_max_w': 100})
        doc = self.controller.stage({'power_max_w': 70})
        self.assertEqual(doc.changes, {})
        self.assertEqual(doc.proposal.blob, original.blob)
        self.assertEqual(doc.preview, [])
        self.controller.save(self.root / 'unchanged.rom')
        self.assertTrue((self.root / 'unchanged.rom.json').exists())

    def test_blackwell_prefers_nvml_units_and_rejects_overlapping_alias(self):
        self.source.write_bytes(synthetic_blackwell())
        doc = self.controller.open(self.source)
        fields = {f['key']: f for f in controls(doc.report)}
        self.assertTrue(fields['memory_offset_max_mhz']['editable'])
        self.assertFalse(fields['dram_max_table_mhz']['editable'])
        for changes, code in (({'dram_max_table_mhz': 5000}, 'FIELD_READ_ONLY'),
                              ({'dram_max_table_mhz': 5000, 'memory_offset_max_mhz': 10000}, 'CONFLICTING_FIELDS')):
            with self.assertRaises(VbiosError) as exc:
                stage_document(doc, changes)
            self.assertEqual(exc.exception.code, code)
        result = self.controller.stage({'memory_offset_max_mhz': 10000})
        after = {f['key']: f for f in result.proposal.manifest['after']['fields']}
        self.assertEqual(after['dram_max_table_mhz']['current'], 5000)
        self.assertEqual(after['memory_offset_max_mhz']['current'], 10000)

    def test_unknown_and_corrupt_inspection_do_not_invent_fields(self):
        self.source.write_bytes(b'unknown ROM')
        doc = self.controller.open(self.source)
        self.assertEqual(controls(doc.report), [])
        self.assertIsNone(doc.report['integrity']['valid'])
        self.source.write_bytes(synthetic_blackwell())
        corrupt = bytearray(self.source.read_bytes())
        corrupt[3072 + 0x209] ^= 1
        self.source.write_bytes(corrupt)
        doc = self.controller.open(self.source)
        self.assertFalse(any(f['editable'] for f in controls(doc.report)))
        with self.assertRaises(VbiosError):
            self.controller.stage({'power_max_w': 100})

    def test_ampere_power_and_clock_ranges_are_editable(self):
        self.source.write_bytes(synthetic_rom(family='ampere'))
        doc = self.controller.open(self.source)
        editable = [f['key'] for f in controls(doc.report) if f['editable']]
        self.assertEqual(editable[:3], ['power_max_w', 'power_default_w', 'power_min_w'])
        self.assertIn('gpc_offset_max_mhz', editable)
        self.assertFalse(any(key.endswith('_mv') for key in editable))

    def test_fan_channel_count_and_channel_limits_are_separate_copies(self):
        source = self.root / 'fans.rom'
        source.write_bytes(synthetic_blackwell(fans=True))
        self.controller.open(source)
        with self.assertRaises(VbiosError) as exc:
            self.controller.stage({'fan_channels': '3', 'fan_1_min_rpm': '900'})
        self.assertEqual(exc.exception.code, 'SEPARATE_EDIT_REQUIRED')
        # An unchanged count is not requested.
        self.assertEqual(self.controller.stage({'fan_channels': '2', 'fan_1_min_rpm': '900'}).changes,
                         {'fan_1_min_rpm': '900'})

    def test_a_fan_maximum_and_its_curve_points_lower_in_one_copy(self):
        from nvidia_vbios.rom import from_bytes
        from nvidia_vbios.rom.image import backend
        source = self.root / 'fans.rom'
        source.write_bytes(synthetic_blackwell(fans=True))
        self.controller.open(source)
        top = {'fan_1_max_rpm': '3000', 'fan_1_curve_3_rpm': '3000', 'fan_extra_1_curve_3_rpm': '3000',
               'fan_extra_2_curve_3_rpm': '3000'}
        # Without the extra curves the joint result is refused and the earlier document stays.
        opened = self.controller.document
        with self.assertRaises(VbiosError) as exc:
            self.controller.stage({key: top[key] for key in ('fan_1_max_rpm', 'fan_1_curve_3_rpm')})
        self.assertEqual((exc.exception.code, exc.exception.details['field']), ('OUT_OF_BOUNDS', 'fan_1_max_rpm'))
        self.assertIs(self.controller.document, opened)
        # An unchanged temperature (60 = 60.0 C) is not requested.
        document = self.controller.stage(dict(top, fan_1_curve_2_temp_c='56.5', fan_1_curve_3_temp_c='60'))
        self.assertEqual(document.changes, dict(top, fan_1_curve_2_temp_c='56.5'))
        self.controller.save(self.root / 'quieter.rom')
        table = backend(from_bytes((self.root / 'quieter.rom').read_bytes())).fan_coolers()
        self.assertEqual((table['rows'][0]['rpm_maximum'], table['rows'][0]['curve_points'][1:]),
                         (3000, ((56.5 * 32, 2200), (60 * 32, 3000))))
        self.assertEqual([c['curve_points'][2][1] for c in table['extra_curves']], [3000, 3000])
        # The same fields undo it in one copy, the points flush with the new maximum included.
        self.controller.open(self.root / 'quieter.rom')
        self.controller.stage(dict({key: '3500' for key in top}, fan_1_curve_2_temp_c='55'))
        self.controller.save(self.root / 'restored.rom')
        self.assertEqual((self.root / 'restored.rom').read_bytes(), source.read_bytes())

    def test_main_preview_has_one_memory_representation_and_keeps_backend_manifest(self):
        from nvidia_vbios.gui.presentation import primary_preview, technical_field_keys
        self.source.write_bytes(synthetic_blackwell())
        doc = self.controller.open(self.source)
        self.assertIn('dram_max_table_mhz', technical_field_keys(doc.report))
        self.assertIn('nvvdd_rel_max_mv', technical_field_keys(doc.report))
        self.assertFalse(next(f for f in controls(doc.report) if f['key'] == 'nvvdd_rel_max_mv')['editable'])
        staged = self.controller.stage({'memory_offset_max_mhz': 10000})
        self.assertEqual([a['key'] for a, b in primary_preview(staged)], ['memory_offset_max_mhz'])
        self.assertIn('dram_max_table_mhz', [a['key'] for a, b in staged.preview])
        self.source.write_bytes(synthetic_rom())
        ada = self.controller.open(self.source)
        # The Ada memory ceiling is editable in MHz too, so its table twin is a detail.
        self.assertIn('dram_max_table_mhz', technical_field_keys(ada.report))
        self.assertIn('nvvdd_rel_max_mv', technical_field_keys(ada.report))

    def test_spanish_known_labels_and_backend_specific_read_only_reasons(self):
        from nvidia_vbios.gui.presentation import field_label, read_only_reason
        fields = {f['key']: f for f in controls(self.controller.document.report)}
        self.assertEqual(field_label(fields['power_max_w'], 'es'), 'Techo de potencia de la placa')
        self.assertIn('no está validada', read_only_reason(fields['ocp_limit_a'], 'es'))
        self.assertIn('únicamente NVVDD', read_only_reason(fields['msvdd_rel_max_mv'], 'es'))
        other = dict(fields['msvdd_rel_max_mv'], reason='integrity failed')
        self.assertEqual(read_only_reason(other), 'integrity failed')

    def test_missing_gtk_has_concise_launch_error(self):
        code = """
import importlib.abc
import sys
class BlockGi(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == 'gi':
            raise ImportError('test missing gi')
sys.meta_path.insert(0, BlockGi())
from nvidia_vbios.gui import main
assert main([]) == 2
"""
        result = subprocess.run([sys.executable, '-c', code], check=True, capture_output=True, text=True)
        self.assertIn('GUI requires GTK4', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_import_gui_and_controller_never_imports_gi(self):
        code = "import sys; import nvidia_vbios.gui; import nvidia_vbios.gui.controller; assert 'gi' not in sys.modules"
        subprocess.run([sys.executable, '-c', code], check=True)


class PresentationNumberTests(unittest.TestCase):
    """Typed text of any size is classified and formatted without raising."""

    def test_extreme_and_invalid_input_is_refused_before_arithmetic(self):
        from decimal import Decimal
        from nvidia_vbios.gui.presentation import classify_number, number, parse_number, windows_value
        cases = {'1e29': 'out_of_range', '-1e29': 'out_of_range', '1e999999999': 'out_of_range',
                 '1e-999999999': 'out_of_range', '0.0000001': 'out_of_range', '9' * 5000: 'out_of_range',
                 'abc': 'not_a_number', '': 'not_a_number', 'nan': 'not_a_number', 'inf': 'not_a_number',
                 '1,5': 'not_a_number'}
        for text, problem in cases.items():
            with self.subTest(text=text[:20]):
                self.assertEqual(classify_number(text), (None, problem))
                self.assertIsNone(parse_number(text))
                self.assertIsNone(windows_value({'key': 'memory_offset_max_mhz'}, text))
        for text, value in (('0', Decimal(0)), ('-2000', Decimal(-2000)), ('10000', Decimal(10000)),
                            ('2147483.647', Decimal('2147483.647')), ('0.001', Decimal('0.001'))):
            self.assertEqual(classify_number(text), (value, None))
        self.assertEqual(windows_value({'key': 'memory_offset_max_mhz'}, '10000'), '5000')
        self.assertIsNone(windows_value({'key': 'gpc_offset_max_mhz'}, '10000'))

    def test_milliamp_fields_show_amps_and_store_exact_milliamps(self):
        from decimal import Decimal
        from nvidia_vbios.gui.presentation import display_units, number, to_display, to_stored
        amps = {'key': 'nvvdd_output_ocp_rated_ma', 'units': 'mA'}
        self.assertEqual(display_units(amps), 'A')
        for stored, shown in ((170000, '170'), (5001000, '5001'), (6600, '6.6'), (1, '0.001'),
                              (0x7FFFFFFF, '2147483.647')):
            self.assertEqual(number(to_display(amps, stored)), shown)
            self.assertEqual(to_stored(amps, shown), str(stored))
        self.assertEqual(to_stored(amps, '6.6005'), '6600.5')  # the backend refuses fractional mA
        self.assertEqual(to_stored(amps, 'abc'), 'abc')
        self.assertIsNone(to_display(amps, None))
        from nvidia_vbios.gui.i18n import Messages
        from nvidia_vbios.gui.presentation import field_section, read_only_reason
        single = {'key': 'fan_channels', 'units': 'channels',
                  'reason': "no other fan channel layout is stored in this table, or a stored channel's limits do not "
                            'hold the extra fan curves'}
        for language in ('en', 'es'):
            self.assertEqual(read_only_reason(single, language), Messages(language)('reason.fan_layout'))
        self.assertEqual(display_units(single), '')
        self.assertEqual({field_section(single), field_section({'key': 'fan_pwm_frequency_hz'})}, {'fans'})
        hertz = {'key': 'fan_pwm_frequency_hz', 'units': 'Hz'}
        self.assertEqual((display_units(hertz), number(to_display(hertz, 25000)), to_stored(hertz, '27')),
                         ('kHz', '25', '27000'))
        table = {'key': 'xbar_max_table_mhz', 'units': 'table MHz'}
        watts = {'key': 'power_max_w', 'units': 'W'}
        self.assertEqual((display_units(table), to_stored(table, '1500')), ('MHz', '1500'))
        self.assertEqual((display_units(watts), to_display(watts, 600.0), to_stored(watts, '700')),
                         ('W', Decimal('600.0'), '700'))

    def test_shunt_multiplier_scales_only_12v_input_limits(self):
        from decimal import Decimal
        from nvidia_vbios.gui.presentation import (CONNECTOR_KEY, FIELD_KEYS, SHUNT_KEYS, field_section, shunt_real,
                                                   shunt_scaled, to_display)
        watts = {'key': 'power_max_w', 'units': 'W'}
        self.assertEqual(shunt_real(watts, '600', Decimal(2)), '1200')
        self.assertEqual(shunt_real(watts, to_display(watts, 450.0), Decimal('1.33')), '598.5')
        # mA fields are shown in A, so the real value is in A too (also the Ada threshold variant).
        amps = {'key': 'input_current_rated_ma', 'units': 'mA', 'policy_class': 'hardware-threshold'}
        self.assertEqual(shunt_real(amps, to_display(amps, 80000), Decimal('2.67')), '213.6')
        self.assertEqual(shunt_real({'key': 'slot_current_threshold_rated_ma', 'units': 'mA'}, '8.25',
                                    Decimal('1.33')), '11')
        for value, multiplier in (('600', Decimal(1)), ('abc', Decimal(2)), ('', Decimal(2)), (None, Decimal(2)),
                                  ('1e29', Decimal(2))):
            with self.subTest(value=value, multiplier=multiplier):
                self.assertIsNone(shunt_real(watts, value, multiplier))
        # VRM output sensors, voltages, clocks, fans and placeholders are not read through the input shunts.
        for key in ('nvvdd_output_ocp_rated_ma', 'msvdd_output_ocp_max_ma', 'nvvdd_power_threshold_max_w',
                    'nvvdd_power_threshold_rated_w', 'nvvdd_rel_max_mv', 'gpc_offset_max_mhz',
                    'fan_pwm_frequency_hz', 'current_limit_a', 'ocp_limit_a', 'input_policy_9_max_raw'):
            with self.subTest(key=key):
                self.assertFalse(shunt_scaled({'key': key}))
                self.assertIsNone(shunt_real({'key': key, 'units': 'mA'}, '100', Decimal(2)))
        # Every shunt key has its own label; Ampere connector keys share a numbered one.
        self.assertTrue(all(key in FIELD_KEYS or CONNECTOR_KEY.fullmatch(key) for key in SHUNT_KEYS))
        self.assertEqual({field_section({'key': key}) for key in SHUNT_KEYS}, {'power', 'current'})

    def test_ampere_connector_labels_sections_and_shunt_scaling(self):
        from nvidia_vbios.gui.presentation import field_label, field_section, shunt_scaled
        from test_extended_fields import descriptors
        from nvidia_vbios.rom import from_bytes
        fields = descriptors(from_bytes(synthetic_rom(family='ampere', policies=True)))
        self.assertEqual(field_label(fields['connector_2_power_rated_w']), 'Connector power channel 2 limit, rated (experimental)')
        self.assertEqual(field_label(fields['connector_1_power_max_w'], 'es'),
                         'Techo del canal de potencia de conector 1 (experimental)')
        for key in ('connector_1_power_max_w', 'connector_1_power_rated_w', 'connector_2_power_max_w'):
            self.assertTrue(shunt_scaled(fields[key]))
            self.assertEqual(field_section(fields[key]), 'power')
        self.assertFalse(shunt_scaled(fields['nvvdd_output_ocp_max_ma']))

    def test_fan_limit_labels_sections_and_opt_in(self):
        from nvidia_vbios.gui.presentation import (display_units, field_label, field_section, opt_in_field_keys,
                                                   section_order, shunt_scaled)
        from test_extended_fields import descriptors
        from nvidia_vbios.rom import from_bytes
        fields = descriptors(from_bytes(synthetic_blackwell(fans=True)))
        self.assertEqual([field_label(fields[k]) for k in ('fan_2_min_rpm', 'fan_1_max_pct')],
                         ['Fan 2 minimum speed (experimental)', 'Fan 1 maximum level (advanced, experimental)'])
        self.assertEqual([field_label(fields[k], 'es') for k in ('fan_2_max_rpm', 'fan_1_min_pct')],
                         ['Velocidad máxima del ventilador 2 (experimental)',
                          'Nivel mínimo del ventilador 1 (avanzado, experimental)'])
        keys = [f'fan_{n}_{side}_{unit}' for n in (1, 2) for unit in ('rpm', 'pct') for side in ('max', 'min')]
        self.assertEqual([f['key'] for f in section_order(fields.values()) if f['key'] in keys], keys)
        for key in keys:
            with self.subTest(key=key):
                self.assertEqual(field_section(fields[key]), 'fans')
                self.assertEqual(display_units(fields[key]), 'RPM' if key.endswith('rpm') else '%')
                self.assertFalse(shunt_scaled(fields[key]))
        # The level limits stay behind the advanced toggle.
        self.assertEqual(opt_in_field_keys({'fields': list(fields.values())}) & set(keys),
                         {k for k in keys if k.endswith('_pct')})

    def test_fan_curve_labels_sections_units_and_opt_in(self):
        from decimal import Decimal
        from nvidia_vbios.gui.presentation import (display_units, field_label, field_section, number,
                                                   opt_in_field_keys, section_order, to_display)
        from test_extended_fields import descriptors
        from nvidia_vbios.rom import from_bytes
        fields = descriptors(from_bytes(synthetic_blackwell(fans=True)))
        keys = ('fan_2_curve_1_temp_c', 'fan_1_curve_3_rpm', 'fan_1_curve_2_pct', 'fan_extra_2_curve_3_temp_c',
                'fan_extra_2_curve_1_rpm', 'fan_extra_1_curve_2_pct')
        self.assertEqual([field_label(fields[k]) for k in keys],
                         ['Fan 2 curve point 1 temperature (experimental)', 'Fan 1 curve point 3 speed (experimental)',
                          'Fan 1 curve point 2 level (advanced, experimental)',
                          'Extra fan curve 2 point 3 temperature (experimental)',
                          'Extra fan curve 2 point 1 speed (experimental)',
                          'Extra fan curve 1 point 2 level (advanced, experimental)'])
        self.assertEqual([field_label(fields[k], 'es') for k in keys],
                         ['Curva del ventilador 2, punto 1: temperatura (experimental)',
                          'Curva del ventilador 1, punto 3: velocidad (experimental)',
                          'Curva del ventilador 1, punto 2: nivel (avanzado, experimental)',
                          'Curva adicional 2, punto 3: temperatura (experimental)',
                          'Curva adicional 2, punto 1: velocidad (experimental)',
                          'Curva adicional 1, punto 2: nivel (avanzado, experimental)'])
        # Channels and PWM, then each channel's limits and curve points, then the extra curves, then zero RPM.
        limits = lambda n: [f'fan_{n}_{side}_{unit}' for unit in ('rpm', 'pct') for side in ('max', 'min')]
        points = lambda prefix: [f'{prefix}_curve_{k}_{unit}' for k in (1, 2, 3) for unit in ('temp_c', 'rpm', 'pct')]
        expected = (['fan_channels', 'fan_pwm_frequency_hz'] + limits(1) + points('fan_1') + limits(2) + points('fan_2') +
                    points('fan_extra_1') + points('fan_extra_2') + ['fan_zero_rpm'])
        self.assertEqual([f['key'] for f in section_order(fields.values()) if f['key'].startswith('fan_')], expected)
        self.assertTrue(all(field_section(fields[k]) == 'fans' for k in expected))
        self.assertEqual(opt_in_field_keys({'fields': list(fields.values())}) & set(expected),
                         {k for k in expected if k.endswith('_pct')})
        # Temperatures show in °C, with decimals only when the stored 1/32 C needs them.
        self.assertEqual(display_units(fields['fan_1_curve_1_temp_c']), '°C')
        self.assertEqual([number(to_display(fields['fan_1_curve_1_temp_c'], v)) for v in (60.0, 51.90625, '60.5')],
                         ['60', '51.90625', '60.5'])
        self.assertEqual(to_display(fields['fan_1_curve_1_temp_c'], fields['fan_1_curve_1_temp_c']['current']),
                         Decimal(50))

    def test_number_formats_every_magnitude_briefly(self):
        from decimal import Decimal
        from nvidia_vbios.gui.presentation import number
        for value, text in ((600.0, '600'), (1112.5, '1112.5'), (-2000, '-2000'), (None, None),
                            (2147483.647, '2147483.647'), (Decimal('1e29'), '1e+29'),
                            (Decimal('-1e-999999999'), '-1e-999999999'), (float('inf'), 'Infinity'),
                            ('n/a', 'n/a')):
            with self.subTest(value=value):
                self.assertEqual(number(value), text)
        self.assertLess(len(number(Decimal('9' * 5000))), 20)


if __name__ == '__main__':
    unittest.main()
