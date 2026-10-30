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
        # The constant REL and ALT take only their opt-in fixed values.
        self.assertFalse(any(key.endswith('_mv') and not key.endswith('_fixed_mv') for key in editable))

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

    def test_a_fan_channel_count_previews_the_channel_it_clears_or_enables(self):
        from decimal import Decimal
        from nvidia_vbios.editor import edit
        from nvidia_vbios.gui.presentation import change_rows, fan_channel_reason, primary_preview
        from nvidia_vbios.rom import from_bytes
        two, three = self.root / 'two.rom', self.root / 'three.rom'
        two.write_bytes(synthetic_blackwell(fans=True))
        three.write_bytes(edit(from_bytes(two.read_bytes()), {'fan_channels': 3}).blob)
        doc = self.controller.open(three)
        fields = {f['key']: f for f in doc.report['fields']}
        fan_3 = [f['key'] for f in doc.report['fields'] if f.get('fan_channel') == 2]
        self.assertEqual(len(fan_3), 15)
        # A lower count clears the last channel: its fields, advanced ones included, are not used in the copy.
        lowered = self.controller.stage({'fan_channels': '2'})
        self.assertEqual([(a['key'], b and b['current']) for a, b in primary_preview(lowered)],
                         [('fan_channels', 2)] + [(key, None) for key in fan_3])
        rows = change_rows(primary_preview(lowered))
        self.assertEqual(rows[:3], [('Fan channels', 3, 2, ''), ('Fan 3 minimum speed', '1050 RPM', 'not used', ''),
                                    ('Fan 3 maximum speed', '3500 RPM', 'not used', '')])
        self.assertIn(('Fan 3 curve point 1 temperature', '50 °C', 'not used', ''), rows)
        self.assertEqual(change_rows(primary_preview(lowered), 'es')[1],
                         ('Velocidad mínima del ventilador 3', '1050 RPM', 'no se usa', ''))
        # Its rows are greyed out while the typed count leaves the channel off.
        channels = fields['fan_channels']
        self.assertEqual(fan_channel_reason(fields['fan_3_min_rpm'], channels, Decimal(2)),
                         'Not used while the fan channel count is 2: the copy keeps fan 3 stored but off, and a '
                         'count of 3 or more turns it on again.')
        self.assertEqual(fan_channel_reason(fields['fan_2_min_rpm'], channels, Decimal(1), 'es'),
                         'No se usa mientras la cantidad de canales de ventilador sea 1: la copia guarda el '
                         'ventilador 2, pero apagado, y con 2 canales o más vuelve a encenderse.')
        for count in (Decimal(3), Decimal('2.5'), Decimal(0), Decimal(4), None):
            self.assertIsNone(fan_channel_reason(fields['fan_3_min_rpm'], channels, count), count)
        self.assertIsNone(fan_channel_reason(fields['fan_2_min_rpm'], channels, Decimal(2)))
        self.assertIsNone(fan_channel_reason(fields['power_max_w'], channels, Decimal(1)))
        # The stored count again: no change.
        self.assertEqual(self.controller.stage({'fan_channels': '3'}).preview, [])
        # A higher count enables the stored channel: its fields only the copy has come last.
        self.controller.open(two)
        raised = self.controller.stage({'fan_channels': '3'})
        self.assertEqual([(a and a['key'], b['key']) for a, b in primary_preview(raised)],
                         [('fan_channels', 'fan_channels')] + [(None, key) for key in fan_3])
        self.assertEqual(change_rows(primary_preview(raised))[1], ('Fan 3 minimum speed', 'not used', 1050, 'RPM'))
        self.assertEqual(change_rows(primary_preview(raised), 'es')[-1][1:],
                         ('no se usa', 50, '°C'))

    def test_an_idle_power_switch_of_an_unlisted_product_previews_off(self):
        # A product whose GR rail gating entries are not reviewed: the switch covers the entries the ROM enables, so
        # the copy saved with Off has no switch, nor its idle time. The change list shows the requested Off and the
        # idle time as not used; the row notes what the Off copy loses.
        from nvidia_vbios.gui.presentation import change_rows, lpwr_notes, primary_preview
        from test_advanced_fields import fixture, set_gr_rail_gating
        path = self.root / 'unlisted.rom'
        path.write_bytes(fixture(device=0x2C02, mutate=set_gr_rail_gating(0xFF)).blob)
        doc = self.controller.open(path)
        fields = {f['key']: f for f in doc.report['fields']}
        self.assertEqual(lpwr_notes(fields['lpwr_gr_rail_gating']),
                         ['This product is not among the reviewed ones, so this switch covers the entries this ROM '
                          'enables. A copy saved with Off no longer shows the switch, since an entry shipped disabled '
                          'looks the same as one turned off: keep the original ROM to go back to Stock.'])
        self.assertEqual(lpwr_notes(fields['lpwr_mscg']), [])
        staged = self.controller.stage({'lpwr_gr_rail_gating': '0'})
        self.assertTrue(staged.proposal.manifest['integrity']['valid'])
        self.assertEqual([(a['key'], b and b['current']) for a, b in primary_preview(staged)],
                         [('lpwr_gr_rail_gating', 0), ('lpwr_gr_rail_gating_idle_us', None)])
        self.assertEqual(change_rows(primary_preview(staged)),
                         [('GR rail gating', 'Stock', 'Off', ''),
                          ('GR rail gating idle time (10 µs steps)', '500 µs', 'not used', '')])
        self.assertEqual(change_rows(primary_preview(staged), 'es')[0][1:3], ('De fábrica', 'Desactivado'))
        output = self.root / 'off.rom'
        self.controller.save(output)
        reopened = self.controller.open(output)
        self.assertFalse({'lpwr_gr_rail_gating', 'lpwr_gr_rail_gating_idle_us'} &
                         {f['key'] for f in reopened.report['fields']})

    def test_shared_vmin_notes_the_memory_floor_and_the_added_equation(self):
        from nvidia_vbios.gui.presentation import vmin_clone_notes
        from nvidia_vbios.rom import from_bytes, inspect_image
        from test_rail_vmin import ada_vmin, ada_vmin_clone
        source = self.root / 'vmin.rom'
        source.write_bytes(ada_vmin_clone())
        doc = self.controller.open(source)
        fields = {f['key']: f for f in doc.report['fields']}
        self.assertEqual(vmin_clone_notes(fields['nvvdd_vmin_mv']), [
            'On this ROM the memory clock voltage floor keeps its stock value. A lower VMIN shows only while the memory '
            'runs at its lowest clock (405 MHz, single-monitor idle). A higher VMIN shows at every memory clock only '
            'above 575 mV (stock VMIN + 15 mV). Up to that it also shows only at that lowest clock.',
            'Not tested on hardware. A VMIN other than the stock value adds a VFE equation to the ROM, and no Ada '
            'card has run an equation added by the editor yet. The override might not load or the driver might fail '
            'to start. Removing the override brings the card back.'])
        self.assertEqual(vmin_clone_notes(fields['nvvdd_vmin_mv'], 'es'), [
            'En esta ROM el piso de voltaje del reloj de memoria mantiene su valor de fábrica. Un VMIN más bajo solo '
            'se nota mientras la memoria va a su reloj más bajo (405 MHz, reposo con un monitor). Un VMIN más alto se '
            'nota con cualquier reloj de memoria solo por encima de 575 mV (VMIN de fábrica + 15 mV). Hasta ahí '
            'también se nota solo en ese reloj más bajo.',
            'Sin probar en hardware. Un VMIN distinto del de fábrica agrega una ecuación VFE a la ROM, y ninguna '
            'tarjeta Ada ha usado todavía una ecuación agregada por el editor. El override podría no cargar o el '
            'driver podría no iniciar. Quitar el override devuelve la tarjeta a como estaba.'])
        plain = {f['key']: f for f in inspect_image(from_bytes(ada_vmin()))['fields']}
        self.assertEqual(vmin_clone_notes(plain['nvvdd_vmin_mv']), [])
        # VMIN and the GPC curve offset take the same unused slot: separate copies.
        with self.assertRaises(VbiosError) as exc:
            self.controller.stage({'nvvdd_vmin_mv': '600', 'gpc_curve_offset_mhz': '30'})
        self.assertEqual(exc.exception.code, 'SEPARATE_EDIT_REQUIRED')
        self.assertEqual(self.controller.stage({'nvvdd_vmin_mv': '600', 'gpc_curve_offset_mhz': '0'}).changes,
                         {'nvvdd_vmin_mv': '600'})

    def test_a_per_chip_vmin_stages_a_value_and_its_switch_goes_back(self):
        from nvidia_vbios.gui.presentation import per_chip, read_only_reason, vmin_tree_notes
        from test_rail_vmin import blackwell_tree
        source = self.root / 'tree.rom'
        source.write_bytes(blackwell_tree())
        doc = self.controller.open(source)
        fields = {f['key']: f for f in controls(doc.report)}
        field, switch = fields['msvdd_vmin_mv'], fields['msvdd_vmin_fixed']
        self.assertTrue(per_chip(field))
        self.assertFalse(per_chip(fields['nvvdd_vmin_mv']))
        notes = vmin_tree_notes(field, 'blackwell-gb20x'), vmin_tree_notes(field, 'blackwell-gb20x', 'es')
        self.assertIn('set per chip from fused values', notes[0][0])
        self.assertIn('round VMIN up to a 5 mV step', notes[0][0])
        self.assertIn('a pasos de 5 mV', notes[1][0])
        # The 5 mV step is the Blackwell driver's: an Ampere compare root's note leaves it out.
        self.assertNotIn('5 mV', vmin_tree_notes(field, 'ampere')[0])
        self.assertIn('idle and light-load states unstable', notes[0][1])
        self.assertIn('se fija por chip', notes[1][0])
        self.assertIn('volver inestables el reposo y las cargas ligeras', notes[1][1])
        self.assertEqual(vmin_tree_notes(switch, 'blackwell-gb20x'), [])
        self.assertEqual(read_only_reason(switch), 'Off: VMIN is the stock value of each chip. Type a value in the '
                                                   'minimum voltage row to fix it.')
        self.assertIn('Desactivado', read_only_reason(switch, 'es'))
        doc = self.controller.stage({'msvdd_vmin_mv': '665'})
        self.assertEqual(doc.changes, {'msvdd_vmin_mv': '665'})
        output = self.root / 'pinned.rom'
        self.controller.save(output)
        doc = self.controller.open(output)
        fields = {f['key']: f for f in controls(doc.report)}
        self.assertFalse(per_chip(fields['msvdd_vmin_mv']))
        self.assertEqual(vmin_tree_notes(fields['msvdd_vmin_fixed'], 'blackwell-gb20x')[0][:41],
                         'On while the value above fixes VMIN. Off ')
        with self.assertRaises(VbiosError) as exc:
            self.controller.stage({'msvdd_vmin_mv': '700', 'msvdd_vmin_fixed': '0'})
        self.assertEqual(exc.exception.code, 'SEPARATE_EDIT_REQUIRED')
        doc = self.controller.stage({'msvdd_vmin_fixed': '0'})
        self.assertEqual(doc.proposal.blob, source.read_bytes())
        from nvidia_vbios.gui.presentation import primary_preview
        self.assertEqual({(a['key'], a['current'], b['current']) for a, b in primary_preview(doc)},
                         {('msvdd_vmin_mv', 665, None), ('msvdd_vmin_fixed', 1, 0)})

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

    def test_unknown_placeholders_stay_in_the_json_and_out_of_the_window(self):
        from nvidia_vbios.gui.presentation import technical_field_keys
        from test_extended_fields import single_rail_fixture
        from nvidia_vbios.rom import from_bytes, inspect_image
        for name, blob in (('Ada', synthetic_rom()), ('Ampere', synthetic_rom(family='ampere')),
                           ('Blackwell', synthetic_blackwell()), ('single rail', single_rail_fixture())):
            with self.subTest(image=name):
                report = inspect_image(from_bytes(blob))
                fields = {f['key']: f for f in report['fields']}
                placeholders = {k for k in ('current_limit_a', 'ocp_limit_a', 'msvdd_rel_max_mv')
                                if k in fields and fields[k]['current'] is None}
                self.assertLessEqual({'current_limit_a', 'ocp_limit_a'}, placeholders)
                self.assertFalse(any(fields[k]['editable'] for k in placeholders))
                self.assertLessEqual(placeholders, technical_field_keys(report))
        single = {f['key']: f for f in inspect_image(from_bytes(single_rail_fixture()))['fields']}
        self.assertEqual(single['msvdd_rel_max_mv']['reason'], 'this recognized single-rail layout exposes only logic/NVVDD')
        self.assertIn('msvdd_rel_max_mv', technical_field_keys({'fields': list(single.values())}))
        # The same keys with a value stay shown.
        for key in ('current_limit_a', 'ocp_limit_a', 'msvdd_rel_max_mv'):
            with self.subTest(key=key):
                self.assertEqual(technical_field_keys({'fields': [dict(single[key], current=5)]}), set())

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


class MemoryViewTests(unittest.TestCase):
    """The read-only memory view and its comparison never touch the open document."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'memory.rom'
        self.source.write_bytes(synthetic_rom(memory=True))

    def test_memory_view_and_comparison_leave_the_document_alone(self):
        from nvidia_vbios.gui.controller import compare_memory, memory_view
        controller = Controller()
        controller.open(self.source)
        staged = controller.stage({'power_max_w': 100})
        report = memory_view(staged.original)
        self.assertEqual(report['timings']['status'], 'recognized')
        changed = bytearray(self.source.read_bytes())
        changed[int(report['timings']['items'][1]['offset'], 16)] += 1
        other = self.root / 'other.rom'
        other.write_bytes(bytes(changed))
        result = compare_memory(report, other)
        self.assertEqual(result['sections']['timings']['keys'], [1])
        self.assertEqual(result['b']['file'], str(other))
        with self.assertRaises(VbiosError) as exc:
            compare_memory(report, self.root / 'missing.rom')
        self.assertEqual(exc.exception.code, 'IO_ERROR')
        self.assertIs(controller.document, staged)
        self.assertEqual((staged.changes, staged.last_saved), ({'power_max_w': '100'}, None))
        self.assertIs(staged.proposal, controller.document.proposal)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['memory.rom', 'other.rom'])

    def test_memory_text_in_both_languages(self):
        from nvidia_vbios.gui.controller import compare_memory, memory_view
        from nvidia_vbios.gui.i18n import Messages
        from nvidia_vbios.gui.presentation import (memory_columns, memory_comparison, memory_configuration,
                                                   memory_raw_text)
        from nvidia_vbios.rom import from_bytes
        report = memory_view(from_bytes(self.source.read_bytes(), 'memory.rom'))
        items = report['configurations']['items']
        self.assertEqual([memory_configuration(item) for item in items[:3]],
                         ['Strap 0 → column 0 · Samsung · type GDDR6',
                          'Strap 1 → column 1 · SK hynix · type 0xa (probably GDDR6X)',
                          'Strap 2 → column 1 · Micron · type 0xd (probably GDDR7)'])
        self.assertEqual(memory_configuration(items[3], 'es'), 'Strap 5 → columna 3 · fabricante 0x2 · tipo 0x3')
        self.assertIn('probablemente GDDR7', memory_configuration(items[2], 'es'))
        # Without stock clocks every band is shown; a column without a timing entry has no rows.
        columns = memory_columns(report)
        self.assertEqual([heading for heading, _, _ in columns],
                         ['Strap 0 → column 0 · Samsung', 'Strap 1, 2 → column 1 · SK hynix, Micron',
                          'Strap 5 → column 3 · vendor 0x2'])
        self.assertEqual(columns[0][1][2][:3], ('5001–16383', '', 'T01'))
        self.assertEqual(columns[0][1][2][3]['tRC'], 79)
        self.assertEqual((columns[0][2], columns[2][1:]), (None, ([], 'No timing entry in these bands.')))
        self.assertEqual(memory_columns(report, 'es')[1][0], 'Strap 1, 2 → columna 1 · SK hynix, Micron')
        # A column the clock table does not reach comes last, with its own note.
        outside = dict(report, bands=dict(report['bands'], columns=[0, 1], outside_table=[3]))
        self.assertEqual(memory_columns(outside, 'es')[-1], ('Strap 5 → columna 3 · fabricante 0x2', [],
                                                             'Fuera de la tabla de clocks de memoria (columnas 0–3).'))
        result = compare_memory(report, self.source)
        spanish = Messages('es')
        self.assertEqual(memory_comparison(result, 'es')[2],
                         (spanish('memory.identical', section=spanish('memory.section.timings')), False))
        self.assertEqual(len(memory_comparison(result)), 4)        # no board profile outside GB20x
        differs = dict(result, sections=dict(
            result['sections'], timings=dict(status='differs', count=1, keys=[1]),
            tables=dict(status='differs', count=2, keys=['memory clock bands (0x0f)', 'timings (0x10)']),
            board_profile=dict(status='differs', fields=0, meaning='unknown')))
        self.assertEqual([line for line, _ in memory_comparison(differs)[2:]],
                         ['Timing entries: differs (entries: 1)',
                          'Memory tables (SHA-256): differs (memory clock bands (0x0f), timings (0x10))',
                          'Board memory-training profile: differs, meaning unknown'])
        self.assertEqual(memory_comparison(differs, 'es')[3][0],
                         'Tablas de memoria (SHA-256): con diferencias (bandas de clock de memoria (0x0f), '
                         'timings (0x10))')
        raw = memory_raw_text(report)
        self.assertIn('T01 @' + report['timings']['items'][1]['offset'] + ': 4f fd 6a 1a', raw)
        self.assertIn('E0 0–540: 0:T00 1:T02 3:--\n    00 00 1c 02 00 00 00 00\n    0: 00 00', raw)
        self.assertIn(report['tables'][2]['sha256'], raw)
        self.assertIn(spanish('memory.section.bands'), memory_raw_text(report, 'es'))


class ImportTests(unittest.TestCase):
    """Values imported from another ROM are typed in as pending changes; nothing is staged or written."""

    def test_import_proposes_values_and_leaves_the_document_alone(self):
        from nvidia_vbios.editor import edit
        from nvidia_vbios.gui.controller import import_from
        from nvidia_vbios.gui.presentation import number
        from nvidia_vbios.rom import from_bytes
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, other = root / 'board.rom', root / 'other.rom'
            blob = synthetic_blackwell(fans=True)
            source.write_bytes(blob)
            other.write_bytes(edit(from_bytes(blob), {'fan_pwm_frequency_hz': 25000, 'power_max_w': 120}).blob)
            controller = Controller()
            controller.open(source)
            document = controller.stage({'power_max_w': 110})
            report = import_from(document, other, ['fans', 'power'])
            self.assertEqual(report['changes'], {'power_max_w': 120, 'fan_pwm_frequency_hz': 25000})
            self.assertIs(controller.document, document)
            self.assertEqual(document.changes, {'power_max_w': '110'})
            # The window types them in over the pending values and verifies the whole set.
            typed = {key: number(value) for key, value in report['changes'].items()}
            staged = stage_document(document, dict(document.changes, **typed))
            self.assertEqual(staged.changes, {'power_max_w': '120', 'fan_pwm_frequency_hz': '25000'})
            with self.assertRaises(VbiosError) as exc:
                import_from(document, root / 'missing.rom', ['fans'])
            self.assertEqual(exc.exception.code, 'IO_ERROR')
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['board.rom', 'other.rom'])
            self.assertEqual(source.read_bytes(), blob)

    def test_import_summary_in_both_languages(self):
        from nvidia_vbios.gui.presentation import import_summary
        report = dict(donor=dict(file='/roms/other.rom', pci_device='10de:2c02'),
                      target=dict(pci_device='10de:2b85'), applied=[dict(field='power_max_w')],
                      unchanged=['fan_1_min_rpm', 'fan_2_min_rpm', 'fan_pwm_frequency_hz'],
                      warnings=[dict(code='DIFFERENT_DEVICE', message='another product')], skipped=[
                          dict(field='input_current_rated_ma', label='12 V input current limit (rated)', units='mA',
                               reason='out_of_bounds', bounds=dict(minimum=1000, maximum=30000)),
                          dict(field='fan_1_max_rpm', label='Fan 1 maximum speed', units='RPM', reason='held_back',
                               partners=['fan_1_max_pct', 'fan_1_min_pct', 'fan_2_max_pct']),
                          dict(field='fan_1_min_rpm', label='Fan 1 minimum speed', units='RPM', reason='held_back',
                               partners=['fan_1_max_pct', 'fan_1_min_pct', 'fan_2_max_pct']),
                          dict(field='fan_2_min_rpm', label='Fan 2 minimum speed', units='RPM', reason='held_back',
                               partners=['fan_2_max_pct']),
                          *(dict(field=f'fan_{n}_{side}_pct', label='', units='%', reason='opt_in')
                            for n, side in ((1, 'max'), (1, 'min'), (2, 'max'))),
                          dict(field='fan_2_max_rpm', label='Fan 2 maximum speed', units='RPM', reason='refused',
                               code='OUT_OF_BOUNDS', message='fan_2_max_rpm violates the ordering'),
                          dict(field='fan_channels', label='Fan channels', units='count', reason='board_specific'),
                          dict(field='fan_3_max_rpm', label='Fan 3 maximum speed', units='RPM',
                               reason='absent_in_target'),
                          dict(field='mystery', label='Mystery field', units='W', reason='refused', code='ODD',
                               message='the backend says no')])
        self.assertEqual(import_summary(report, {}), [
            ('Imported from other.rom as pending changes: 1.', 'heading'),
            ('The other ROM is for another product of this family (PCI 10de:2c02; this ROM: PCI 10de:2b85). Its '
             'values were set for that product.', 'warning'),
            ('Already equal in both ROMs: 3.', 'detail'),
            ('Not imported: 11.', 'heading'),
            ('Some fields go with advanced fields that differ; import again with the advanced fields to take them.',
             'detail'),
            ("12 V input current limit, rated: outside this ROM's range (1 to 30 A)", 'detail'),
            ('Fan 1 maximum speed; Fan 1 minimum speed: go with related fields that are not imported: Fan 1 maximum '
             'level (advanced); Fan 1 minimum level (advanced) and 1 more', 'detail'),
            ('Fan 2 minimum speed: goes with related fields that are not imported: Fan 2 maximum level (advanced)',
             'detail'),
            ('Fan 1 maximum level (advanced): advanced field, not included', 'detail'),
            ('Fan 1 minimum level (advanced): advanced field, not included', 'detail'),
            ('Fan 2 maximum level (advanced): advanced field, not included', 'detail'),
            ('Fan 2 maximum speed: refused by the editor: The value is outside the allowed range or breaks the '
             'minimum/default/maximum order [OUT_OF_BOUNDS]', 'detail'),
            ("Fan channels: this board's fan count; never copied", 'detail'),
            ('Fan 3 maximum speed: not in this ROM', 'detail'),
            ('Mystery field: refused by the editor: the backend says no [ODD]', 'detail')])
        spanish = [line for line, _ in import_summary(dict(report, applied=[], warnings=[]), {}, 'es')]
        self.assertEqual(spanish[:4], ['No se importó nada de other.rom.', 'Ya iguales en ambas ROM: 3.',
                                       'No importados: 11.', 'Algunos campos van junto con campos avanzados que '
                                       'difieren; importa de nuevo con los campos avanzados para traerlos.'])
        self.assertEqual(spanish[5], 'Velocidad máxima del ventilador 1; Velocidad mínima del ventilador 1: van junto '
                                     'con campos relacionados que no se importan: Nivel máximo del ventilador 1 '
                                     '(avanzado); Nivel mínimo del ventilador 1 (avanzado) y 1 más')
        self.assertEqual(spanish[10:13], [
            'Velocidad máxima del ventilador 2: rechazado por el editor: El valor está fuera del rango permitido o '
            'rompe el orden mínimo/por defecto/máximo [OUT_OF_BOUNDS]',
            'Canales de ventilador: cantidad de ventiladores de esta placa; nunca se copia',
            'Velocidad máxima del ventilador 3: no está en esta ROM'])


class PresentationNumberTests(unittest.TestCase):
    """Typed text of any size is classified and formatted without raising."""

    def test_extreme_and_invalid_input_is_refused_before_arithmetic(self):
        from decimal import Decimal
        from nvidia_vbios.gui.presentation import classify_number, linux_value, number, parse_number, windows_value
        cases = {'1e29': 'out_of_range', '-1e29': 'out_of_range', '1e999999999': 'out_of_range',
                 '1e-999999999': 'out_of_range', '0.0000001': 'out_of_range', '9' * 5000: 'out_of_range',
                 'abc': 'not_a_number', '': 'not_a_number', 'nan': 'not_a_number', 'inf': 'not_a_number',
                 '1,5': 'not_a_number'}
        for text, problem in cases.items():
            with self.subTest(text=text[:20]):
                self.assertEqual(classify_number(text), (None, problem))
                self.assertIsNone(parse_number(text))
                self.assertIsNone(windows_value({'key': 'memory_offset_max_mhz'}, text))
                self.assertIsNone(linux_value({'key': 'factory_memory_offset_mhz'}, text))
        for text, value in (('0', Decimal(0)), ('-2000', Decimal(-2000)), ('10000', Decimal(10000)),
                            ('2147483.647', Decimal('2147483.647')), ('0.001', Decimal('0.001'))):
            self.assertEqual(classify_number(text), (value, None))
        self.assertEqual(windows_value({'key': 'memory_offset_max_mhz'}, '10000'), '5000')
        self.assertIsNone(windows_value({'key': 'gpc_offset_max_mhz'}, '10000'))
        # The factory memory offset is on the Afterburner scale: nvidia-settings shows twice the number.
        self.assertEqual(linux_value({'key': 'factory_memory_offset_mhz'}, '-5000'), '-10000')
        self.assertIsNone(windows_value({'key': 'factory_memory_offset_mhz'}, '500'))
        self.assertIsNone(linux_value({'key': 'factory_gpc_offset_mhz'}, '500'))
        self.assertIsNone(linux_value({'key': 'memory_offset_max_mhz'}, '10000'))

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
                  'reason': "no other fan channel layout is stored in this table, or a stored channel's maximums sit "
                            'below the extra fan curves'}
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
        from nvidia_vbios.gui.presentation import (CONNECTOR_CURRENT_KEY, CONNECTOR_KEY, FIELD_KEYS, SHUNT_KEYS,
                                                   field_section, shunt_real, shunt_scaled, to_display)
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
        # Every shunt key has its own label; connector keys share numbered ones.
        self.assertTrue(all(key in FIELD_KEYS or CONNECTOR_KEY.fullmatch(key) or CONNECTOR_CURRENT_KEY.fullmatch(key)
                            for key in SHUNT_KEYS))
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
        # The opt-in NVVDD output current limit (row 13) is labelled as the Turing one.
        self.assertEqual([field_label(fields[k]) for k in ('nvvdd_output_ocp_max_ma', 'nvvdd_output_ocp_rated_ma')],
                         ['NVVDD output current limit ceiling (advanced, experimental)',
                          'NVVDD output current limit, rated (advanced, experimental)'])
        self.assertEqual(field_section(fields['nvvdd_output_ocp_rated_ma']), 'current')
        # Both rows note the risk in each language; not on another family or a read-only row.
        from nvidia_vbios.gui.i18n import Messages
        from nvidia_vbios.gui.presentation import output_current_notes
        for language in ('en', 'es'):
            for key in ('nvvdd_output_ocp_max_ma', 'nvvdd_output_ocp_rated_ma'):
                self.assertEqual(output_current_notes(fields[key], 'ampere', language),
                                 [Messages(language)('output_ocp.ampere')])
        self.assertIn('likely protects the core VRM', output_current_notes(fields['nvvdd_output_ocp_max_ma'],
                                                                            'ampere')[0])
        self.assertIn('Probablemente protege el VRM del núcleo',
                      output_current_notes(fields['nvvdd_output_ocp_max_ma'], 'ampere', 'es')[0])
        self.assertEqual(output_current_notes(fields['nvvdd_output_ocp_max_ma'], 'turing'), [])
        self.assertEqual(output_current_notes(dict(fields['nvvdd_output_ocp_max_ma'], editable=False), 'ampere'), [])
        self.assertEqual(output_current_notes(fields['connector_1_power_max_w'], 'ampere'), [])

    def test_a_row_capping_the_connector_sum_is_noted_on_each_connector_row(self):
        from nvidia_vbios.gui.presentation import field_label, section_order, shunt_scaled, summed_cap_notes
        from test_ampere_fields import CONNECTOR_SUM, connector_sum
        from test_extended_fields import descriptors
        from nvidia_vbios.rom import from_bytes
        blob = synthetic_rom(family='ampere', policies=True)
        fields = descriptors(from_bytes(connector_sum(blob)))
        notes = {key: summed_cap_notes(fields[key], list(fields.values())) for key in fields}
        self.assertEqual(notes['connector_2_power_rated_w'],
                         ['Row 11 also caps the sum of connector power channels 1, 2 at 280 W rated / 280 W maximum '
                          'and may bind first: raising this limit alone may have no effect. Raise the connector power '
                          'sum limits too.'])
        self.assertEqual({key for key, note in notes.items() if note},
                         {f'connector_{n}_power_{side}_w' for n in (1, 2) for side in ('max', 'rated')})
        spanish = summed_cap_notes(fields['connector_1_power_max_w'], list(fields.values()), 'es')
        self.assertEqual(len(spanish), 1)
        self.assertTrue(spanish[0].startswith('La fila 11 también limita la suma de los canales de potencia de '
                                              'conector 1, 2 a 280 W nominal / 280 W máximo'))
        self.assertTrue(spanish[0].endswith('Sube también los límites de la suma de potencia de conectores.'))
        # A sum row without its own field (weight -1.0) keeps the warning; a channel without a
        # connector field is named by its power channel index.
        negative = descriptors(from_bytes(connector_sum(blob, weight=0xFFFFF000)))
        self.assertTrue(summed_cap_notes(negative['connector_1_power_max_w'], list(negative.values()))[0]
                        .endswith('may have no effect.'))
        partial = [f for f in fields.values() if not f['key'].startswith('connector_2_')]
        self.assertIn('sum of power channels 5, 6 at 280 W',
                      summed_cap_notes(fields['connector_1_power_max_w'], partial)[0])
        self.assertEqual([field_label(fields[k]) for k in CONNECTOR_SUM],
                         ['Connector power sum ceiling (experimental)', 'Connector power sum limit, rated (experimental)'])
        self.assertEqual(field_label(fields['connector_sum_power_rated_w'], 'es'),
                         'Límite de la suma de potencia de conectores, nominal (experimental)')
        power = [f['key'] for f in section_order(fields.values()) if f['key'].startswith('connector_')]
        self.assertEqual(power[-2:], CONNECTOR_SUM)
        self.assertTrue(all(shunt_scaled(fields[k]) for k in CONNECTOR_SUM))

    def test_cable_sense_profiles_note_the_top_level_and_the_input_current(self):
        from nvidia_vbios.gui.presentation import sense_profile_notes, unsupported_notes
        from nvidia_vbios.rom import from_bytes, inspect_image
        from test_ada_fields import sense_profiles
        report = inspect_image(from_bytes(sense_profiles(synthetic_rom(copies=2, policies=True))))
        fields = {f['key']: f for f in report['fields']}
        self.assertEqual(unsupported_notes(report), {})
        self.assertEqual(sense_profile_notes(fields['power_max_w'], report['fields']), [
            'This ROM sets its power limits from the 16-pin cable sense pins. This value applies at the top level, '
            'most likely a 600 W cable (inferred, not tested). Lower levels keep their own limits.',
            'Going past 600 W is more than that cable is rated for. That is your call.',
            'The 12 V input current threshold (rated 30 A, about 360 W at 12 V) may limit first. Raise it too, under '
            'Show advanced XOC-style fields.'])
        self.assertEqual(sense_profile_notes(fields['power_default_w'], report['fields'], 'es'), [
            'Esta ROM fija sus límites de potencia según los pines de detección del cable de 16 pines. Este valor se '
            'aplica en el nivel más alto, probablemente un cable de 600 W (deducido, sin probar). Los niveles más '
            'bajos mantienen sus propios límites.'])
        # Without the 12 V input threshold field the ceiling keeps the first two notes; other fields and ROMs
        # without sense profiles have none.
        partial = [f for f in report['fields'] if f['key'] != 'input_current_rated_ma']
        self.assertEqual(len(sense_profile_notes(fields['power_max_w'], partial, 'es')), 2)
        self.assertEqual(sense_profile_notes(fields['power_min_w'], report['fields']), [])
        plain = {f['key']: f for f in inspect_image(from_bytes(synthetic_rom(copies=2, policies=True)))['fields']}
        self.assertEqual(sense_profile_notes(plain['power_max_w'], list(plain.values())), [])

    def test_notebook_notes_name_the_running_limit_and_the_base_tgp(self):
        from nvidia_vbios.gui.presentation import field_label, notebook_notes, shunt_scaled
        from nvidia_vbios.rom import from_bytes, inspect_image
        from test_extended_fields import notebook_fixture
        report = inspect_image(from_bytes(notebook_fixture(base=150000)))
        fields = {f['key']: f for f in report['fields']}
        family = report['architecture']['family']
        ceiling = notebook_notes(fields['power_max_w'], family)
        self.assertEqual(len(ceiling), 1)
        self.assertIn('raising it alone usually does not raise the running limit', ceiling[0])
        # The base TGP bounds neither the ceiling nor the boot default, but on the one laptop tested the running
        # limit moved only with the three raised together, so each note names the other two.
        default = notebook_notes(fields['power_default_w'], family)
        self.assertEqual(len(default), 1)
        for note in (ceiling[0], default[0]):
            self.assertIn('Notebook base TGP (under Show advanced XOC-style fields, where the ROM has it)', note)
            self.assertIn('from 175 to about 185 W', note)
        self.assertIn('To raise the running limit, raise the three together.', ceiling[0])
        self.assertIn("the laptop's VRM, cooling and power adapter were sized for the stock limit", ceiling[0])
        # The step is a difference in watts, not the base TGP's value.
        self.assertIn('by as many watts as you raise the base TGP', default[0])
        self.assertEqual(notebook_notes(fields['power_min_w'], family), [])
        base = notebook_notes(fields['notebook_base_tgp_w'], family)
        self.assertEqual(len(base), 1)
        self.assertTrue(base[0].startswith('Tested on one RTX 5090 Laptop GPU'), base[0])
        self.assertIn('To raise the running limit, raise the three together, the boot default by as many watts as '
                      'you raise this value', base[0])
        self.assertIn('When you change it, it has to stay between the boot default and the ceiling', base[0])
        self.assertIn('To go above the ceiling, raise the ceiling with it in the same edit', base[0])
        self.assertIn('does not show this field but keeps its stored value', base[0])
        self.assertIn('Other laptops are not tested', base[0])
        spanish = notebook_notes(fields['notebook_base_tgp_w'], family, 'es')[0]
        self.assertIn('Dynamic Boost', spanish)
        self.assertTrue(spanish.startswith('Probado en una RTX 5090 Laptop GPU'), spanish)
        self.assertIn('Para pasar del techo, sube el techo junto con él en la misma edición', spanish)
        self.assertIn('no muestra este campo pero conserva su valor guardado', spanish)
        for key in ('power_max_w', 'power_default_w'):
            note = notebook_notes(fields[key], family, 'es')[0]
            self.assertIn('el TGP base del portátil', note)
            self.assertIn('está en Mostrar campos avanzados (estilo XOC) cuando la ROM lo tiene.', note)
        self.assertIn('tantos vatios como subas el TGP base',
                      notebook_notes(fields['power_default_w'], family, 'es')[0])
        self.assertIn('tantos vatios como subas este valor', spanish)
        self.assertIn('se dimensionaron para el límite de fábrica',
                      notebook_notes(fields['power_max_w'], family, 'es')[0])
        self.assertEqual(field_label(fields['notebook_base_tgp_w']), 'Notebook base TGP (experimental)')
        self.assertEqual(field_label(fields['notebook_base_tgp_w'], 'es'), 'TGP base del portátil (experimental)')
        self.assertTrue(shunt_scaled(fields['notebook_base_tgp_w']))
        # Without the base TGP field the ceiling and the boot default keep their notes; other families and layouts
        # have none.
        plain = inspect_image(from_bytes(notebook_fixture()))
        plain_fields = {f['key']: f for f in plain['fields']}
        self.assertEqual(notebook_notes(plain_fields['power_max_w'], family), ceiling)
        self.assertEqual(notebook_notes(plain_fields['power_default_w'], family), default)
        self.assertEqual(notebook_notes(fields['power_default_w'], 'ada'), [])
        self.assertEqual(notebook_notes(fields['power_max_w'], 'ada'), [])
        desktop = {f['key']: f for f in inspect_image(from_bytes(synthetic_blackwell()))['fields']}
        self.assertEqual(notebook_notes(desktop['power_max_w'], family), [])

    def test_an_untouched_notebook_base_tgp_holds_back_no_power_edit(self):
        # The window sends every shown row, the advanced base TGP included; an unchanged row is not requested, so a
        # ceiling below or a boot default above the stored base stages as it does without that field. The change
        # list then holds only the requested fields: the base TGP keeps its stored value, and that it is no field on
        # the copy (or is one again on a copy edited back) is no change.
        from nvidia_vbios.gui.presentation import change_rows, primary_preview
        from test_extended_fields import notebook_fixture
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'laptop.rom'
            path.write_bytes(notebook_fixture(base=150000))
            controller = Controller()
            controller.open(path)
            doc = controller.document
            for changes in ({'power_max_w': '120'}, {'power_default_w': '160'},
                            {'power_max_w': '250', 'power_default_w': '175'}):
                with self.subTest(changes=changes):
                    staged = stage_document(doc, dict(changes, notebook_base_tgp_w='150', power_min_w='5'))
                    self.assertEqual(staged.changes, changes)
                    self.assertTrue(staged.proposal.manifest['integrity']['valid'])
                    self.assertEqual({a['key'] for a, b in primary_preview(staged)}, set(changes))
                    for language in ('en', 'es'):
                        rows = change_rows(primary_preview(staged), language)
                        self.assertEqual(len(rows), len(changes))
                        self.assertNotIn('not used' if language == 'en' else 'no se usa', [r[2] for r in rows])
                    # The full preview still has the pair; the window leaves it out.
                    hidden = 'notebook_base_tgp_w' not in {f['key'] for f in staged.proposal.manifest['after']['fields']}
                    self.assertEqual(any(a['key'] == 'notebook_base_tgp_w' for a, b in staged.preview), hidden)
            lowered = Path(tmp) / 'lowered.rom'
            lowered.write_bytes(controller.stage({'power_max_w': '120'}).proposal.blob)
            copy = Controller()
            copy.open(lowered)
            self.assertNotIn('notebook_base_tgp_w', {f['key'] for f in copy.document.report['fields']})
            back = stage_document(copy.document, {'power_max_w': '175'})
            self.assertEqual([(a and a['key'], b['key']) for a, b in back.preview],
                             [('power_max_w', 'power_max_w'), (None, 'notebook_base_tgp_w')])
            self.assertEqual([(a['key'], b['current']) for a, b in primary_preview(back)], [('power_max_w', 175)])
            with self.assertRaises(VbiosError) as exc:
                stage_document(doc, {'power_max_w': '120', 'notebook_base_tgp_w': '140'})
            self.assertEqual((exc.exception.code, exc.exception.details['field'],
                              exc.exception.details['bounds']['maximum']), ('OUT_OF_BOUNDS', 'notebook_base_tgp_w', 120))

    def test_a_failed_resolver_leaves_one_note_in_its_section(self):
        from nvidia_vbios.gui.i18n import Messages
        from nvidia_vbios.gui.presentation import unsupported_notes
        # The Galax HOF XOC shape before its selector layout was accepted: four voltage resolvers failed.
        message = 'unvalidated Turing rail selectors'
        report = {'diagnostics': [{'code': 'UNSUPPORTED_FORMAT', 'message': message, 'resolver': resolver}
                                  for resolver in ('voltage', 'equation_roles', 'evaluated_vmin', 'fixed_voltage')]}
        self.assertEqual(unsupported_notes(report),
                         {'voltage': 'Some fields in this section are not shown: this VBIOS uses a layout the editor '
                                     'does not support yet.'})
        self.assertEqual(unsupported_notes(report, 'es'), {'voltage': Messages('es')('section.unsupported')})
        self.assertNotEqual(unsupported_notes(report, 'es'), unsupported_notes(report))
        # No diagnostics, or none from a mapped resolver (an unpadded image, an unrecognized one, an Ada REL
        # compare expression that drops only the hidden REL ceiling alias): no note.
        for diagnostics in ([], [{'message': 'legacy image lacks a contiguous EFI image'}],
                             [{'message': 'fields are read-only', 'resolver': 'checksum_layout'}],
                             [{'message': 'REL equation is a compare expression on fused inputs; read-only',
                               'resolver': 'voltage'}]):
            with self.subTest(diagnostics=diagnostics):
                self.assertEqual(unsupported_notes({'diagnostics': diagnostics}), {})
        self.assertEqual(unsupported_notes({}), {})
        fans = {'diagnostics': [{'message': 'fan channel enables disagree across the fan tables', 'resolver': 'fans'}]}
        self.assertEqual(list(unsupported_notes(fans)), ['fans'])

    def test_connector_current_labels_sections_shunt_scaling_and_opt_in(self):
        from nvidia_vbios.gui.presentation import (field_label, field_section, opt_in_field_keys, section_order,
                                                   shunt_scaled)
        from test_ampere_fields import with_connector_current
        from test_extended_fields import descriptors
        from nvidia_vbios.rom import from_bytes
        fields = descriptors(from_bytes(with_connector_current(synthetic_rom(family='ampere', copies=2,
                                                                             policies=True))))
        keys = ['connector_1_current_threshold_rated_ma', 'connector_1_current_threshold_max_ma']
        self.assertEqual([field_label(fields[k]) for k in keys],
                         ['Connector channel 1 current threshold, rated (advanced, experimental)',
                          'Connector channel 1 current threshold ceiling (advanced, experimental)'])
        self.assertEqual([field_label(fields[k], 'es') for k in keys],
                         ['Umbral de corriente del canal de conector 1, nominal (avanzado, experimental)',
                          'Techo del umbral de corriente del canal de conector 1 (avanzado, experimental)'])
        for key in keys:
            with self.subTest(key=key):
                self.assertEqual(field_section(fields[key]), 'current')
                self.assertTrue(shunt_scaled(fields[key]))
        self.assertLessEqual(set(keys), opt_in_field_keys({'fields': list(fields.values())}))
        order = [f['key'] for f in section_order(fields.values())]
        self.assertEqual(order.index(keys[0]) + 1, order.index(keys[1]))
        self.assertLess(order.index('slot_current_threshold_max_ma'), order.index(keys[0]))

    def test_turing_fixed_voltage_labels_sections_and_opt_in(self):
        from nvidia_vbios.gui.presentation import field_label, field_section, opt_in_field_keys, shunt_scaled
        from test_extended_fields import descriptors
        from test_turing import synthetic_turing
        from nvidia_vbios.rom import from_bytes
        fields = descriptors(from_bytes(synthetic_turing(rails=True)))
        keys = ['nvvdd_rel_fixed_mv', 'nvvdd_alt_fixed_mv']
        self.assertEqual([field_label(fields[k]) for k in keys],
                         ['NVVDD REL fixed voltage (advanced, experimental)',
                          'NVVDD ALT fixed voltage (advanced, experimental)'])
        self.assertEqual(field_label(fields['nvvdd_alt_fixed_mv'], 'es'),
                         'Voltaje fijo ALT de NVVDD (avanzado, experimental)')
        # The Ada fields are not opt-in: the same label without "advanced".
        self.assertEqual(field_label({'key': 'nvvdd_rel_fixed_mv'}), 'NVVDD REL fixed voltage (experimental)')
        self.assertEqual({field_section(fields[k]) for k in keys}, {'voltage'})
        self.assertLessEqual(set(keys), opt_in_field_keys({'fields': list(fields.values())}))
        self.assertFalse(any(shunt_scaled(fields[k]) for k in keys))

    def test_turing_nvvdd_current_limit_labels_are_advanced(self):
        from nvidia_vbios.gui.presentation import field_label, opt_in_field_keys
        from test_extended_fields import descriptors
        from test_turing import synthetic_turing
        from nvidia_vbios.rom import from_bytes
        fields = descriptors(from_bytes(synthetic_turing(inputs=True)))
        keys = ['nvvdd_output_ocp_max_ma', 'nvvdd_output_ocp_rated_ma']
        self.assertEqual([field_label(fields[k]) for k in keys],
                         ['NVVDD output current limit ceiling (advanced, experimental)',
                          'NVVDD output current limit, rated (advanced, experimental)'])
        self.assertEqual(field_label(fields['nvvdd_output_ocp_rated_ma'], 'es'),
                         'Límite de corriente de salida de NVVDD, nominal (avanzado, experimental)')
        self.assertLessEqual(set(keys), opt_in_field_keys({'fields': list(fields.values())}))
        # Without opt-in (the Ada row) the label stays the OCP one.
        self.assertEqual(field_label({'key': 'nvvdd_output_ocp_rated_ma'}),
                         'NVVDD output OCP current limit, rated (experimental)')

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
        # Channels and PWM, then each channel's limits and curve points, then the extra curves, then zero RPM
        # and its temperature pairs.
        limits = lambda n: [f'fan_{n}_{side}_{unit}' for unit in ('rpm', 'pct') for side in ('max', 'min')]
        points = lambda prefix: [f'{prefix}_curve_{k}_{unit}' for k in (1, 2, 3) for unit in ('temp_c', 'rpm', 'pct')]
        pair = lambda prefix: [f'{prefix}_zero_rpm_{side}_temp_c' for side in ('low', 'high')]
        temperatures = pair('fan_1') + pair('fan_2') + pair('fan_extra_1') + pair('fan_extra_2')
        expected = (['fan_channels', 'fan_pwm_frequency_hz'] + limits(1) + points('fan_1') + limits(2) + points('fan_2') +
                    points('fan_extra_1') + points('fan_extra_2') + ['fan_zero_rpm'] + temperatures)
        self.assertEqual([f['key'] for f in section_order(fields.values()) if f['key'].startswith('fan_')], expected)
        self.assertTrue(all(field_section(fields[k]) == 'fans' for k in expected))
        self.assertEqual(opt_in_field_keys({'fields': list(fields.values())}) & set(expected),
                         {k for k in expected if k.endswith('_pct')} | {'fan_zero_rpm'} | set(temperatures))
        thresholds = ('fan_2_zero_rpm_low_temp_c', 'fan_extra_1_zero_rpm_high_temp_c')
        self.assertEqual([field_label(fields[k]) for k in thresholds],
                         ['Fan 2 zero RPM lower threshold (advanced, experimental)',
                          'Extra fan curve 1 zero RPM upper threshold (advanced, experimental)'])
        self.assertEqual([field_label(fields[k], 'es') for k in thresholds],
                         ['Ventilador 2, parada en reposo: umbral inferior (avanzado, experimental)',
                          'Curva adicional 1, parada en reposo: umbral superior (avanzado, experimental)'])
        self.assertEqual(display_units(fields['fan_1_zero_rpm_high_temp_c']), '°C')
        # Temperatures show in °C, with decimals only when the stored 1/32 C needs them.
        self.assertEqual(display_units(fields['fan_1_curve_1_temp_c']), '°C')
        self.assertEqual([number(to_display(fields['fan_1_curve_1_temp_c'], v)) for v in (60.0, 51.90625, '60.5')],
                         ['60', '51.90625', '60.5'])
        self.assertEqual(to_display(fields['fan_1_curve_1_temp_c'], fields['fan_1_curve_1_temp_c']['current']),
                         Decimal(50))

    def test_fan_curve_hints_name_only_actual_channel_blockers_in_both_languages(self):
        from nvidia_vbios.gui.presentation import fan_curve_hint, row_title
        from test_extended_fields import descriptors
        from nvidia_vbios.rom import from_bytes
        fields = descriptors(from_bytes(synthetic_rom(copies=2, fans=2)))
        pending = {'fan_1_min_rpm': '1200', 'fan_2_min_rpm': '1200'}
        for language in ('en', 'es'):
            for channel in (1, 2):
                with self.subTest(language=language, channel=channel):
                    limit = fields[f'fan_{channel}_min_rpm']
                    hint = fan_curve_hint(limit, list(fields.values()), pending, language)
                    self.assertIn('1000 RPM', hint)
                    self.assertIn(row_title(fields[f'fan_{channel}_curve_1_rpm'], language)[0], hint)
                    # A minimum is held by the channel's own curve only: the extra curves (also from 1000 RPM)
                    # may stay below it.
                    for key in (f'fan_{3-channel}_curve_1_rpm', f'fan_{channel}_curve_2_rpm', 'fan_extra_1_curve_1_rpm',
                                'fan_extra_2_curve_1_rpm'):
                        self.assertNotIn(row_title(fields[key], language)[0], hint)
                    fixed = dict(pending, **{f'fan_{channel}_curve_1_rpm': '1200'})
                    self.assertEqual(fan_curve_hint(limit, list(fields.values()), fixed, language), '')
        self.assertNotEqual(fan_curve_hint(fields['fan_1_min_rpm'], list(fields.values()), pending, 'en'),
                            fan_curve_hint(fields['fan_1_min_rpm'], list(fields.values()), pending, 'es'))

    def test_fan_curve_hints_use_pending_maximum_midpoints_and_hidden_percentages(self):
        from nvidia_vbios.gui.presentation import fan_curve_hint, row_title
        from test_extended_fields import descriptors
        from nvidia_vbios.rom import from_bytes
        fields = descriptors(from_bytes(synthetic_rom(copies=2, fans=2)))
        for language in ('en', 'es'):
            with self.subTest(language=language):
                maximum = fields['fan_1_max_rpm']
                pending = {'fan_1_max_rpm': '3000'}
                hint = fan_curve_hint(maximum, list(fields.values()), pending, language)
                self.assertIn('3300 RPM', hint)
                for prefix in ('fan_1', 'fan_extra_1', 'fan_extra_2'):
                    key = prefix + '_curve_3_rpm'
                    self.assertIn(row_title(fields[key], language)[0], hint)
                    pending[key] = '3000'
                self.assertEqual(fan_curve_hint(maximum, list(fields.values()), pending, language), '')
                # Pending values may belong to advanced rows that are currently hidden. The extra curves (20/50 %)
                # stay below the raised minimum.
                minimum = fields['fan_1_min_pct']
                pending = {'fan_1_min_pct': '60', 'fan_1_curve_1_pct': '60', 'fan_1_curve_2_pct': '55'}
                hint = fan_curve_hint(minimum, list(fields.values()), pending, language)
                self.assertIn('55 %', hint)  # the pending midpoint
                self.assertIn(row_title(fields['fan_1_curve_2_pct'], language)[0], hint)
                for key in ('fan_extra_1_curve_1_pct', 'fan_extra_1_curve_2_pct', 'fan_extra_2_curve_2_pct'):
                    self.assertNotIn(row_title(fields[key], language)[0], hint)
                pending['fan_1_curve_2_pct'] = '60'
                self.assertEqual(fan_curve_hint(minimum, list(fields.values()), pending, language), '')
                upper_pct = fields['fan_1_max_pct']
                self.assertIn('100 %', fan_curve_hint(upper_pct, list(fields.values()),
                                                     {'fan_1_max_pct': '90'}, language))

    def test_fan_curve_hints_require_numeric_pending_values_and_matching_metadata(self):
        from nvidia_vbios.gui.presentation import fan_curve_hint, row_title
        from test_extended_fields import descriptors
        from nvidia_vbios.rom import from_bytes
        fields = descriptors(from_bytes(synthetic_rom(fans=2)))
        limit = fields['fan_1_min_rpm']
        for value in (None, '', 'abc', 'nan', 'inf'):
            with self.subTest(value=value):
                self.assertEqual(fan_curve_hint(limit, list(fields.values()), {limit['key']: value}), '')
        self.assertEqual(fan_curve_hint(limit, list(fields.values()), {}), '')
        self.assertEqual(fan_curve_hint(fields['power_max_w'], list(fields.values()), {'power_max_w': '1200'}), '')
        self.assertEqual(fan_curve_hint(fields['fan_1_curve_1_rpm'], list(fields.values()),
                                        {'fan_1_curve_1_rpm': '1200'}), '')
        # Metadata, rather than the displayed channel number, determines membership: a minimum takes the points
        # whose fan_channel is its channel, a maximum every point whose fan_rows hold it, extra curves included.
        relevant = dict(fields['fan_2_curve_2_rpm'], fan_channel=0, fan_rows=[0], current=900)
        unrelated = dict(fields['fan_1_curve_1_rpm'], fan_channel=1, fan_rows=[1], current=100)
        extra = dict(fields['fan_extra_1_curve_1_rpm'], fan_rows=[0], current=800)
        nonnumeric = dict(fields['fan_1_curve_2_rpm'], current=None)
        rows = [limit, relevant, unrelated, extra, nonnumeric, fields['fan_1_curve_1_pct']]
        hint = fan_curve_hint(limit, rows, {limit['key']: '1200'})
        self.assertIn('900 RPM', hint)
        self.assertIn(row_title(relevant)[0], hint)
        for other in (unrelated, extra, nonnumeric, fields['fan_1_curve_1_pct']):
            self.assertNotIn(row_title(other)[0], hint)
        self.assertEqual(fan_curve_hint(limit, rows, {limit['key']: '1200', relevant['key']: 'abc'}), '')
        hint = fan_curve_hint(fields['fan_1_max_rpm'], rows, {'fan_1_max_rpm': '700'})
        self.assertIn('900 RPM', hint)
        for blocker in (relevant, extra):
            self.assertIn(row_title(blocker)[0], hint)
        self.assertNotIn(row_title(unrelated)[0], hint)
        # A refusal due to encoding or the speed table must not blame curves that already fit.
        self.assertEqual(fan_curve_hint(limit, [], {limit['key']: '40000'}), '')
        self.assertEqual(fan_curve_hint(fields['fan_1_max_rpm'], list(fields.values()),
                                        {'fan_1_max_rpm': '3400'}), '')

    def test_fan_curve_hint_does_not_offer_to_edit_read_only_blockers(self):
        from nvidia_vbios.gui.presentation import fan_curve_hint, row_title
        from test_extended_fields import descriptors
        from nvidia_vbios.rom import from_bytes
        fields = descriptors(from_bytes(synthetic_rom(fans=2)))
        # The channel's first point below a minimum, an extra curve's top point above a maximum.
        readonly = {'fan_1_min_rpm': (dict(fields['fan_1_curve_1_rpm'], editable=False), '1200'),
                    'fan_1_max_rpm': (dict(fields['fan_extra_1_curve_3_rpm'], editable=False), '3000')}
        rows = [next((r for r, _ in readonly.values() if r['key'] == f['key']), f) for f in fields.values()]
        for language, explanation, edit_instructions in (
                ('en', 'read-only', ('Raise those points', 'Lower those points')),
                ('es', 'solo lectura', ('Sube esos puntos', 'Baja esos puntos'))):
            for key, (blocker, value) in readonly.items():
                with self.subTest(language=language, limit=key):
                    hint = fan_curve_hint(fields[key], rows, {key: value}, language)
                    self.assertIn(explanation, hint)
                    self.assertIn(row_title(blocker, language)[0], hint)
                    for instruction in edit_instructions:
                        self.assertNotIn(instruction, hint)

    def test_zero_rpm_mixed_state_reasons_and_notes(self):
        from nvidia_vbios.gui.presentation import fan_stop_notes, read_only_reason, value_text, zero_rpm_channels_hint
        from test_ada_fields import template_board, with_low_extra, with_policy_copy, with_zero_rpm
        from test_extended_fields import descriptors
        from nvidia_vbios.rom import from_bytes
        blob = synthetic_rom(copies=2, fans=2)
        # Bit 2 on some entries only: no value, but a state the rows can show, and a translated reason.
        mixed = descriptors(from_bytes(with_zero_rpm(with_zero_rpm(blob, flags=(0x13, 0x03)), flags=(0x17, 0x07),
                                                     entries=(2,))))
        flag, pair = mixed['fan_zero_rpm'], mixed['fan_1_zero_rpm_high_temp_c']
        self.assertEqual([value_text(flag, None, language) for language in ('en', 'es')],
                         ['Mixed (on for some fan entries)', 'Mixto (activado en algunas entradas de ventilador)'])
        self.assertIn('on for some fan entries', read_only_reason(flag))
        self.assertIn('activada en algunas entradas', read_only_reason(flag, 'es'))
        self.assertEqual(read_only_reason(pair), 'Zero RPM is read-only in this ROM, so its thresholds stay as stored.')
        self.assertIn('solo lectura', read_only_reason(pair, 'es'))
        # A block GSP-RM refuses (the RTX A2000's third entry): translated as well.
        refused = descriptors(from_bytes(with_zero_rpm(blob, flags=(0x11, 0x01), block=b'')))['fan_zero_rpm']
        self.assertIn('RTX A2000', read_only_reason(refused))
        self.assertIn('RTX A2000', read_only_reason(refused, 'es'))
        # Notes under the switch: the values a template board takes and the blower risks, the flag form with bit 4
        # clear, the untested note on Ada and Ampere, and the manual fan tool everywhere.
        template = descriptors(from_bytes(template_board()))['fan_zero_rpm']
        notes = fan_stop_notes(template, 'ampere')
        self.assertEqual(len(notes), 4)
        self.assertIn('the values NVIDIA stores on the RTX 3080 Ti Founders Edition ROM (zero RPM thresholds '
                      '38.875/60, 50/72, 60/70 °C)', notes[0])
        self.assertIn('No blower card ships with fan stop on. A stopped blower most likely moves no air', notes[1])
        self.assertIn('Restarting a blower from 0 RPM is untested', notes[1])
        self.assertNotIn('clamshell', ' '.join(notes))
        self.assertIn('no shipped ROM runs zero RPM with; whether the fans stop is untested', notes[2])
        self.assertEqual(notes[3], 'A fan tool that holds manual control keeps the fans running.')
        spanish = fan_stop_notes(template, 'ampere', 'es')
        self.assertIn('Lo más probable es que un blower parado', spanish[1])
        self.assertIn('no está probado si los ventiladores se detienen', spanish[2])
        ada = descriptors(from_bytes(with_zero_rpm(blob)))['fan_zero_rpm']
        self.assertEqual(fan_stop_notes(ada, 'ada'), ['Not tested on hardware on Ada or Ampere cards.',
                                                      'A fan tool that holds manual control keeps the fans running.'])
        # A ROM that ships with zero RPM off: the risks on a card with a blower fan.
        off = descriptors(from_bytes(with_zero_rpm(blob, flags=(0x11, 0x01))))['fan_zero_rpm']
        notes = fan_stop_notes(off, 'ada')
        self.assertEqual(len(notes), 3)
        self.assertTrue(notes[0].startswith('This ROM ships with zero RPM off. If the card has a blower fan, a stopped '
                                            'fan most likely moves no air through the card, memory and power stages '
                                            'included'))
        self.assertTrue(fan_stop_notes(off, 'ada', 'es')[0].startswith('Esta ROM viene de fábrica con la parada en '
                                                                       'reposo desactivada'))
        # An entry with the same lower and upper (the RTX 3060 8GB stores 40/40 C): no hysteresis.
        flat = descriptors(from_bytes(with_zero_rpm(blob, flags=(0x13, 0x03),
                                                    pairs=((40, 40), (40, 50), (53, 63), (60, 70)))))['fan_zero_rpm']
        self.assertEqual(flat['zero_rpm_flat_pairs'], [{'field': 'fan_1_zero_rpm_low_temp_c', 'temp_c': 40.0}])
        self.assertIn('"Fan 1 zero RPM lower threshold (advanced)" equals the upper threshold (40 °C): with zero RPM '
                      'on there is no hysteresis', fan_stop_notes(flat, 'ampere')[1])
        self.assertIn('Bájalo unos grados.', fan_stop_notes(flat, 'ampere', 'es')[1])
        # GB20x: the synthetic image stores flag bytes 0 (zero RPM off, bit 4 clear on its channel entries).
        blackwell = descriptors(from_bytes(synthetic_blackwell(fans=True)))['fan_zero_rpm']
        self.assertEqual([note[:30] for note in fan_stop_notes(blackwell, 'blackwell')],
                         ['This ROM ships with zero RPM o', 'With zero RPM on, the fan chan',
                          'A fan tool that holds manual c'])
        self.assertEqual(fan_stop_notes(flag, 'ampere'), [])          # read-only: the reason says it
        # A ROM that keeps a copy of the fan 1 entry (an HP OEM RTX 3060 12 GB): the switch says the editor writes
        # both, and the read-only channel count says why.
        copied = descriptors(from_bytes(with_policy_copy(with_zero_rpm(
            synthetic_rom(family='ampere', copies=2, fans=1), flags=(0x11, 0x01),
            pairs=((45, 55), (90, 95), (85, 90))))))
        self.assertIn('This ROM also keeps a copy of the fan 1 settings, most likely unused; the editor changes both '
                      'the same way.', fan_stop_notes(copied['fan_zero_rpm'], 'ampere'))
        self.assertIn('copia de los ajustes del ventilador 1, probablemente sin uso',
                      ' '.join(fan_stop_notes(copied['fan_zero_rpm'], 'ampere', 'es')))
        self.assertTrue(read_only_reason(copied['fan_channels']).endswith('so the count stays as stored.'))
        self.assertTrue(read_only_reason(copied['fan_channels'], 'es').endswith('queda como está guardada.'))
        # A ROM that stores an extra fan curve in the entry of a disabled channel (an RTX 3050 6GB or 8GB): the
        # read-only channel count says why.
        low = descriptors(from_bytes(with_low_extra(synthetic_rom(family='ampere', copies=2, fans=1))))
        self.assertTrue(read_only_reason(low['fan_channels']).startswith('This ROM stores an extra fan curve, used for '
                                                                         'every fan, in the entry of a second fan'))
        self.assertTrue(read_only_reason(low['fan_channels'], 'es').startswith('Esta ROM guarda una curva adicional'))
        # The hint for a fan channel count the start temperature rule refuses.
        self.assertEqual([zero_rpm_channels_hint(v) for v in ('separate-edits', 'none', None)],
                         ['zero_rpm_channels_hint', 'zero_rpm_channels_locked_hint', None])

    def test_flag_fields_read_on_and_off(self):
        from decimal import Decimal
        from nvidia_vbios.gui.presentation import field_label, value_text
        from test_extended_fields import descriptors
        from nvidia_vbios.rom import from_bytes
        field = descriptors(from_bytes(synthetic_blackwell(fans=True)))['fan_zero_rpm']
        self.assertEqual((field_label(field), field_label(field, 'es')),
                         ('Fan zero RPM (advanced, experimental)', 'Parada de ventiladores en reposo (avanzado, experimental)'))
        self.assertEqual([value_text(field, v) for v in (Decimal(0), Decimal(1), None)], ['Off', 'On', None])
        self.assertEqual([value_text(field, v, 'es') for v in (0, 1)], ['Desactivado', 'Activado'])
        # Other units keep the plain number, 0 and 1 included.
        self.assertEqual([value_text({'units': 'channels'}, v) for v in (Decimal(1), Decimal('2.50'))], ['1', '2.5'])

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
