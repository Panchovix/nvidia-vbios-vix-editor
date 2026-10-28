"""Opt-in actual GTK window smoke test; requires a dedicated display.

VBIOS_GUI_SMOKE=1; optional VBIOS_GUI_SCREENSHOT=/ignored/path.png.
Does not use reference ROMs or access GPUs.
"""
import os
from pathlib import Path
import struct
import tempfile
import time
import unittest


@unittest.skipUnless(os.environ.get('VBIOS_GUI_SMOKE') == '1', 'opt-in GTK display smoke test')
class GtkSmokeTests(unittest.TestCase):
    def test_real_window_live_preview_reset_and_snapshot(self):
        for language in ('en', 'es'):
            with self.subTest(language=language):
                self._exercise_window(language)

    def test_window_language_is_independent_of_other_windows_and_host_locale(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, Gtk
        from nvidia_vbios.gui.app import EditorWindow
        from unittest.mock import patch
        app = Gtk.Application(application_id='org.nvidia_vbios.LocaleSmoke', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        with patch.dict(os.environ, {'LANG': 'es_CL.UTF-8', 'LC_ALL': 'es_CL.UTF-8'}):
            english = EditorWindow(app)
            spanish = EditorWindow(app, language='es')
        try:
            self.assertEqual(english.open_button.get_label(), 'Open ROM…')
            self.assertEqual(english.language, 'en')
            self.assertNotEqual(spanish.open_button.get_label(), english.open_button.get_label())
            self.assertEqual(spanish.language, 'es')
            self.assertEqual(english.preview_text(), english.text('live_none'))
            self.assertEqual(spanish.preview_text(), spanish.text('live_none'))
            self.assertNotEqual(english.preview_text(), spanish.preview_text())
            self.assertEqual(english.get_title(), english.text('window_title'))
            self.assertNotEqual(english.get_title(), spanish.get_title())
        finally:
            english.close()
            spanish.close()

    def test_theme_menu_switches_every_window_and_system_restores_the_desktop_choice(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.gui.app import EditorWindow
        app = Gtk.Application(application_id='org.nvidia_vbios.ThemeSmoke', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        settings = Gtk.Settings.get_default()
        key = ('gtk-interface-color-scheme' if hasattr(Gtk, 'InterfaceColorScheme') else
               'gtk-application-prefer-dark-theme')
        desktop = settings.get_property(key)
        window = EditorWindow(app, theme='dark')
        try:
            dark = settings.get_property(key)
            self.assertNotEqual(dark, desktop)
            action = window.lookup_action('theme')
            self.assertEqual(action.get_state().get_string(), 'dark')
            action.activate(GLib.Variant('s', 'light'))
            self.assertNotEqual(settings.get_property(key), dark)
            action.activate(GLib.Variant('s', 'auto'))         # not Windows: the desktop's choice again
            self.assertEqual((settings.get_property(key), window.theme), (desktop, 'auto'))
        finally:
            window.close()

    def test_ampere_connector_rows_stage_in_both_languages(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.gui.app import EditorWindow, texts
        from test_ampere_fields import connector_sum
        from test_rom_formats import synthetic_rom
        app = Gtk.Application(application_id='org.nvidia_vbios.AmpereSmoke', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ampere.rom'
            # Row 11 caps the sum of both connector channels at 280 W.
            path.write_bytes(connector_sum(synthetic_rom(family='ampere', policies=True, fans=2)))
            for language, title, note, ocp in (
                    ('en', 'Connector power channel 1 ceiling', 'Row 11 also caps the sum of connector power channels '
                                                                '1, 2 at 280 W rated / 280 W maximum',
                     'NVVDD output current limit, rated (advanced)'),
                    ('es', 'Techo del canal de potencia de conector 1', 'La fila 11 también limita la suma de los '
                                                                        'canales de potencia de conector 1, 2',
                     'Límite de corriente de salida de NVVDD, nominal (avanzado)')):
                with self.subTest(language=language):
                    window = EditorWindow(app, path, language)
                    window.present()
                    try:
                        until(lambda: not window.busy and window.controller.document is not None)
                        self.assertIn(title, '\n'.join(texts(window.field_box)))
                        for key in ('connector_1_power_max_w', 'connector_2_power_rated_w'):
                            self.assertIn(note, '\n'.join(texts(window.rows[key]['row'])))
                        self.assertNotIn(note, '\n'.join(texts(window.rows['connector_sum_power_max_w']['row'])))
                        for key in ('connector_2_power_rated_w', 'connector_sum_power_rated_w', 'gpc_offset_max_mhz',
                                    'fan_pwm_frequency_hz'):
                            self.assertIn(key, window.entries)
                        # Hardware thresholds and the NVVDD output current limit stay behind the advanced
                        # toggle; constant voltages have no entry.
                        for key in ('input_current_rated_ma', 'nvvdd_output_ocp_rated_ma', 'nvvdd_output_ocp_max_ma'):
                            self.assertNotIn(key, window.entries)
                        self.assertNotIn('nvvdd_output_ocp_max_ma', window.readonly_rows)
                        self.assertNotIn('nvvdd_rel_equation_max_mv', window.entries)
                        window.advanced_toggle.set_active(True)
                        until(lambda: 'nvvdd_output_ocp_rated_ma' in window.entries)
                        self.assertIn(ocp, '\n'.join(texts(window.field_box)))
                        self.assertEqual(window.entries['nvvdd_output_ocp_rated_ma'].get_text(), '226.8')  # in amps
                        self.assertIn('nvvdd_output_ocp_max_ma', window.entries)
                        for key in ('nvvdd_output_ocp_max_ma', 'nvvdd_output_ocp_rated_ma'):
                            self.assertIn(window.text('output_ocp.ampere'), '\n'.join(texts(window.rows[key]['row'])))
                        self.assertNotIn(window.text('output_ocp.ampere'),
                                         '\n'.join(texts(window.rows['input_current_rated_ma']['row'])))
                        window.entries['connector_1_power_max_w'].set_text('200')
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual(window.controller.document.changes['connector_1_power_max_w'], '200')
                    finally:
                        window.close()

    def test_auxiliary_connector_rows_stay_behind_the_advanced_toggle_with_their_notes(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.gui.app import EditorWindow, texts
        from test_connector_input import ada_connector
        app = Gtk.Application(application_id='org.nvidia_vbios.ConnectorSmoke', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'connector.rom'
            path.write_bytes(ada_connector())
            for language, title, rating in (
                    ('en', 'Connector power channel 1 ceiling (advanced)',
                     'a PCIe 8-pin connector is rated for 150 W, a 12V-2x6 (16-pin) cable for the level its sense pins '
                     'report.'),
                    ('es', 'Techo del canal de potencia de conector 1 (avanzado)',
                     'un conector PCIe de 8 pines admite 150 W, y un cable 12V-2x6 (16 pines), el nivel que indican '
                     'sus pines de detección.')):
                with self.subTest(language=language):
                    window = EditorWindow(app, path, language)
                    window.present()
                    try:
                        until(lambda: not window.busy and window.controller.document is not None)
                        self.assertNotIn('connector_1_power_max_w', window.entries)
                        window.advanced_toggle.set_active(True)
                        until(lambda: 'connector_1_power_max_w' in window.entries)
                        ceiling = '\n'.join(texts(window.rows['connector_1_power_max_w']['row']))
                        self.assertIn(title, ceiling)
                        self.assertIn(rating, ceiling)
                        self.assertNotIn(rating, '\n'.join(texts(window.rows['connector_1_power_rated_w']['row'])))
                        window.entries['connector_1_power_max_w'].set_text('200')
                        window.entries['connector_1_power_rated_w'].set_text('200')
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual(window.controller.document.changes,
                                         {'connector_1_power_max_w': '200', 'connector_1_power_rated_w': '200'})
                    finally:
                        window.close()

    def test_ada_cable_sense_profile_notes_in_both_languages(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.gui.app import EditorWindow, texts
        from test_ada_fields import sense_profiles
        from test_rom_formats import synthetic_rom
        app = Gtk.Application(application_id='org.nvidia_vbios.SenseSmoke', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sense.rom'
            path.write_bytes(sense_profiles(synthetic_rom(copies=2, policies=True)))
            for language, top, past in (('en', 'most likely a 600 W cable', 'Going past 600 W'),
                                        ('es', 'probablemente un cable de 600 W', 'Pasar de 600 W')):
                with self.subTest(language=language):
                    window = EditorWindow(app, path, language)
                    window.present()
                    try:
                        until(lambda: not window.busy and window.controller.document is not None)
                        ceiling = '\n'.join(texts(window.rows['power_max_w']['row']))
                        default = '\n'.join(texts(window.rows['power_default_w']['row']))
                        self.assertIn(top, ceiling)
                        self.assertIn(past, ceiling)
                        self.assertIn('360 W', ceiling)
                        self.assertIn(top, default)
                        self.assertNotIn(past, default)
                        self.assertNotIn(top, '\n'.join(texts(window.rows['power_min_w']['row'])))
                        window.entries['power_max_w'].set_text('90')
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual(window.controller.document.changes['power_max_w'], '90')
                    finally:
                        window.close()

    def test_notebook_ceiling_and_base_tgp_notes_in_both_languages(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.gui.app import EditorWindow, texts
        from test_extended_fields import notebook_fixture
        app = Gtk.Application(application_id='org.nvidia_vbios.NotebookSmoke', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'notebook.rom'
            path.write_bytes(notebook_fixture(base=150000))
            for language in ('en', 'es'):
                with self.subTest(language=language):
                    window = EditorWindow(app, path, language)
                    window.present()
                    try:
                        until(lambda: not window.busy and window.controller.document is not None)
                        ceiling = '\n'.join(texts(window.rows['power_max_w']['row']))
                        default = '\n'.join(texts(window.rows['power_default_w']['row']))
                        self.assertIn(window.text('notebook.ceiling'), ceiling)
                        self.assertIn(window.text('notebook.default'), default)
                        self.assertNotIn(window.text('notebook.ceiling'), default)
                        # The base TGP bounds neither, but both rows name it: the three are raised together.
                        label = window.text('field.notebook_base_tgp_w').split(' (')[0]
                        self.assertIn(label, ceiling)
                        self.assertIn(label, default)

                        def staged(typed, changes):
                            for key, text in typed.items():
                                window.entries[key].set_text(text)
                            until(lambda: not window.verifying)
                            self.assertFalse(window.dirty, typed)
                            self.assertEqual(window.controller.document.changes, changes)
                            self.assertEqual([key for key, info in window.rows.items()
                                              if 'invalid' in info['row'].get_css_classes()], [])
                            # The change list and its count hold only the requested fields: the untouched base
                            # TGP keeps its stored value even where the copy no longer shows it as a field.
                            document = window.controller.document
                            if changes:
                                self.assertEqual(window.status.get_text(), window.text(
                                    'live_ok', count=len(changes), bytes=document.proposal.manifest['changed_bytes']))
                            self.assertNotIn(label, window.preview_text())
                            self.assertNotIn(window.text('change.not_used'), window.preview_text())

                        # A ceiling below and a boot default above the stored base TGP (150 W) stage as without it,
                        # with the advanced box off or on (the base TGP row shown and untouched).
                        for advanced in (False, True):
                            window.advanced_toggle.set_active(advanced)
                            # The base TGP is an advanced field: hidden until the box is ticked.
                            self.assertEqual('notebook_base_tgp_w' in window.entries, advanced)
                            staged({'power_max_w': '120'}, {'power_max_w': '120'})
                            staged({'power_max_w': '175', 'power_default_w': '160'}, {'power_default_w': '160'})
                            staged({'power_default_w': '80'}, {})
                        base = '\n'.join(texts(window.rows['notebook_base_tgp_w']['row']))
                        self.assertIn(window.text('notebook.base_tgp'), base)
                        self.assertIn(window.text('field.notebook_base_tgp_w').split(' (')[0], base)
                        window.entries['power_max_w'].set_text('225')
                        window.entries['notebook_base_tgp_w'].set_text('200')
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual((window.controller.document.changes['power_max_w'],
                                          window.controller.document.changes['notebook_base_tgp_w']), ('225', '200'))
                        # Past the ceiling alone, the base TGP row is marked.
                        window.entries['power_max_w'].set_text('175')
                        until(lambda: not window.verifying)
                        self.assertIn('invalid', window.rows['notebook_base_tgp_w']['row'].get_css_classes())
                    finally:
                        window.close()

    def test_shared_vmin_notes_and_separate_gpc_offset_in_both_languages(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.gui.app import EditorWindow, texts
        from test_rail_vmin import ada_vmin_clone
        app = Gtk.Application(application_id='org.nvidia_vbios.VminCloneSmoke', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'vmin.rom'
            path.write_bytes(ada_vmin_clone())
            for language, floor, risk in (('en', 'lowest clock (405 MHz, single-monitor idle)',
                                           'Removing the override brings the card back'),
                                          ('es', 'reloj más bajo (405 MHz, reposo con un monitor)',
                                           'Quitar el override devuelve la tarjeta')):
                with self.subTest(language=language):
                    window = EditorWindow(app, path, language)
                    window.present()
                    try:
                        until(lambda: not window.busy and window.controller.document is not None)
                        row = '\n'.join(texts(window.rows['nvvdd_vmin_mv']['row']))
                        self.assertIn(floor, row)
                        self.assertIn(risk, row)
                        self.assertNotIn(floor, '\n'.join(texts(window.rows['power_max_w']['row'])))
                        window.entries['nvvdd_vmin_mv'].set_text('600')
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual(window.controller.document.changes, {'nvvdd_vmin_mv': '600'})
                        # The GPC curve offset (an advanced field) takes the same unused slot: a separate copy.
                        window.advanced_toggle.set_active(True)
                        until(lambda: 'gpc_curve_offset_mhz' in window.entries)
                        window.entries['gpc_curve_offset_mhz'].set_text('30')
                        until(lambda: not window.verifying)
                        self.assertIn(window.text('error.SEPARATE_EDIT_REQUIRED'), window.status.get_text())
                        window.entries['gpc_curve_offset_mhz'].set_text('0')
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual(window.controller.document.changes, {'nvvdd_vmin_mv': '600'})
                    finally:
                        window.close()

    def test_per_chip_vmin_row_and_its_switch_in_both_languages(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.editor import edit, load
        from nvidia_vbios.gui.app import EditorWindow, texts
        from test_rail_vmin import blackwell_tree
        app = Gtk.Application(application_id='org.nvidia_vbios.VminTreeSmoke', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        with tempfile.TemporaryDirectory() as tmp:
            stock, pinned = Path(tmp) / 'tree.rom', Path(tmp) / 'pinned.rom'
            stock.write_bytes(blackwell_tree())
            pinned.write_bytes(edit(load(stock), {'msvdd_vmin_mv': 665}).blob)
            for language, original, note in (('en', 'Original: per chip (not stored in the ROM)', 'set per chip'),
                                             ('es', 'Original: por chip (no está guardado en la ROM)', 'por chip')):
                with self.subTest(language=language):
                    window = EditorWindow(app, stock, language)
                    window.present()
                    chip = window.text('per_chip_value')
                    try:
                        until(lambda: not window.busy and window.controller.document is not None)
                        row = window.rows['msvdd_vmin_mv']
                        lines = '\n'.join(texts(row['row']))
                        self.assertIn(original, lines)
                        self.assertIn(note, lines)
                        entry = window.entries['msvdd_vmin_mv']
                        self.assertEqual(entry.get_text(), '')
                        self.assertNotIn('invalid', row['row'].get_css_classes())
                        # The stock switch is a read-only row.
                        self.assertIn(window.text('reason.vmin_fixed_stock'),
                                      texts(window.readonly_rows['msvdd_vmin_fixed']))
                        entry.set_text('665')
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual(window.controller.document.changes, {'msvdd_vmin_mv': '665'})
                        self.assertIn('changed', row['row'].get_css_classes())
                        self.assertEqual(row['delta'].get_text(), f'{chip} → 665 mV')
                        self.assertIn(f'{chip} → 665 mV', window.preview_text())
                        entry.set_text('')
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual(window.controller.document.changes, {})
                        # The pinned copy: the value is a number and the switch turns it back to stock.
                        window.open_path(pinned)
                        until(lambda: not window.busy and window.controller.document.original.name == str(pinned))
                        self.assertEqual(window.entries['msvdd_vmin_mv'].get_text(), '665')
                        switch = window.entries['msvdd_vmin_fixed']
                        self.assertIsInstance(switch, Gtk.Switch)
                        self.assertTrue(switch.get_active())
                        switch.set_active(False)
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual(window.controller.document.changes, {'msvdd_vmin_fixed': '0'})
                        self.assertIn(f'665 → {chip}', window.preview_text())
                    finally:
                        window.close()
                        while context.pending():
                            context.iteration(False)

    def test_max_temperature_and_factory_offset_rows_stage_in_both_languages(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.gui.app import EditorWindow, texts
        from test_rom_formats import synthetic_blackwell
        app = Gtk.Application(application_id='org.nvidia_vbios.ThermalSmoke', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'factory-oc.rom'
            path.write_bytes(synthetic_blackwell(thermal=True, factory_clocks=True))
            for language in ('en', 'es'):
                with self.subTest(language=language):
                    window = EditorWindow(app, path, language)
                    window.present()
                    try:
                        until(lambda: not window.busy and window.controller.document is not None)
                        # Both are regular rows (no advanced toggle); the rated boost is in the read-only list.
                        self.assertFalse(window.advanced_toggle.get_active())
                        for key in ('max_operating_temp_c', 'factory_gpc_offset_mhz'):
                            self.assertIn(key, window.entries)
                            self.assertIn(window.text('field.' + key).split(' (')[0],
                                          '\n'.join(texts(window.rows[key]['row'])))
                        self.assertIn('factory_rated_boost_mhz', window.readonly_rows)
                        boost = '\n'.join(texts(window.readonly_rows['factory_rated_boost_mhz']))
                        self.assertIn('2655 MHz', boost)
                        self.assertIn(window.text('reason.factory_boost'), boost)
                        self.assertIn('90 °C', '\n'.join(texts(window.rows['max_operating_temp_c']['row'])))
                        # The factory memory offset is on the Afterburner scale; its row also shows the
                        # nvidia-settings number, and a value other than 0 says it turns the offset on (flag 0).
                        memory = window.rows['factory_memory_offset_mhz']
                        self.assertIn(window.text('linux_equivalent', value='0'), '\n'.join(texts(memory['row'])))
                        window.entries['max_operating_temp_c'].set_text('83.5')
                        window.entries['factory_gpc_offset_mhz'].set_text('-50')
                        window.entries['factory_memory_offset_mhz'].set_text('500')
                        delta = memory['delta'].get_text()
                        self.assertIn('nvidia-settings: 1000 MHz', delta)
                        self.assertIn(window.text('factory_offset_on'), delta)
                        # The GPC offset is stored with flag 1: no such note, and no second scale.
                        gpc = window.rows['factory_gpc_offset_mhz']['delta'].get_text()
                        self.assertNotIn(window.text('factory_offset_on'), gpc)
                        self.assertNotIn('nvidia-settings', gpc)
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual(window.controller.document.changes['max_operating_temp_c'], '83.5')
                        self.assertEqual(window.controller.document.changes['factory_gpc_offset_mhz'], '-50')
                        self.assertEqual(window.controller.document.changes['factory_memory_offset_mhz'], '500')
                        self.assertIn('120 → -50 MHz', window.preview_text())
                        self.assertIn('0 → 500 MHz', window.preview_text())
                        # Above the stock ceiling the row is marked with the accepted range.
                        window.entries['max_operating_temp_c'].set_text('94')
                        until(lambda: not window.verifying)
                        self.assertIn('invalid', window.rows['max_operating_temp_c']['row'].get_css_classes())
                        self.assertIn('93', window.rows['max_operating_temp_c']['delta'].get_text())
                    finally:
                        window.close()

    def test_advanced_section_greys_rows_whose_switch_is_off_in_both_languages(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.editor import edit, load
        from nvidia_vbios.gui.app import EditorWindow, texts
        from test_rom_formats import synthetic_blackwell
        app = Gtk.Application(application_id='org.nvidia_vbios.AdvancedSmoke', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        def children(box):
            child, found = box.get_first_child(), []
            while child:
                found.append(child)
                child = child.get_next_sibling()
            return found

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'advanced.rom'
            path.write_bytes(synthetic_blackwell(perf_cf=True, lpwr=True, thermal=True))
            # The same ROM with the utilization policy stored off.
            stored_off = Path(tmp) / 'policy-off.rom'
            stored_off.write_bytes(edit(load(path), {'perf_cf_util_policy': 0}).blob)
            for language in ('en', 'es'):
                with self.subTest(language=language):
                    window = EditorWindow(app, path, language)
                    window.present()
                    try:
                        until(lambda: not window.busy and window.controller.document is not None)
                        expander = window.advanced_expander
                        # A collapsed section after the other ones (Power here), without the XOC-style toggle.
                        self.assertFalse(window.advanced_toggle.get_active())
                        self.assertFalse(expander.get_expanded())
                        self.assertIn(window.text('section.advanced'), texts(expander))
                        self.assertIn(window.text('section.advanced_note'), texts(expander.get_child()))
                        boxes = children(window.field_box)
                        self.assertLess(boxes.index(window.rows['max_operating_temp_c']['row'].get_parent()),
                                        boxes.index(expander))
                        for key in ('perf_cf_util_policy', 'perf_cf_gpc_target_pct', 'perf_cf_dram_hysteresis_down',
                                    'lpwr_mscg', 'lpwr_difr', 'lpwr_difr_dfpr_idle_ms'):
                            self.assertIn(key, window.entries)
                        # Two cards under their headings: the clock controllers, then idle power saving.
                        inside = texts(expander.get_child())
                        self.assertLess(inside.index(window.text('section.advanced_perf')),
                                        inside.index(window.text('section.advanced_lpwr')))
                        perf_card = window.rows['perf_cf_util_policy']['row'].get_parent()
                        self.assertIs(window.rows['perf_cf_vid_hysteresis_up']['row'].get_parent(), perf_card)
                        lpwr_card = window.rows['lpwr_gr_power_gating']['row'].get_parent()
                        self.assertIsNot(lpwr_card, perf_card)
                        self.assertIs(window.rows['lpwr_difr_cg_idle_us']['row'].get_parent(), lpwr_card)
                        target, policy = window.entries['perf_cf_gpc_target_pct'], window.entries['perf_cf_util_policy']
                        note = window.rows['perf_cf_gpc_target_pct']['dependency']
                        self.assertTrue(target.get_sensitive())
                        self.assertFalse(note.get_visible())
                        self.assertIn(window.text('flag_stock'), '\n'.join(texts(window.rows['lpwr_mscg']['row'])))
                        # A typed target, then the policy turned off as a pending change: the row goes back to
                        # its stored value, greyed out with the reason naming the switch.
                        target.set_text('55')
                        policy.set_active(False)
                        self.assertFalse(target.get_sensitive())
                        self.assertEqual(target.get_text(), '40')
                        self.assertTrue(note.get_visible())
                        self.assertIn(window.text('field.perf_cf_util_policy').split(' (')[0], note.get_text())
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual(window.controller.document.changes, {'perf_cf_util_policy': '0'})
                        # Back on: editable again, and a target stages.
                        policy.set_active(True)
                        self.assertTrue(target.get_sensitive())
                        self.assertFalse(note.get_visible())
                        target.set_text('55')
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual(window.controller.document.changes, {'perf_cf_gpc_target_pct': '55'})
                        self.assertIn('40 → 55 %', window.preview_text())
                        # DIFR set to Off greys its idle times.
                        window.entries['lpwr_difr'].set_active(False)
                        for key in ('lpwr_difr_dfpr_idle_ms', 'lpwr_difr_sw_asr_idle_us', 'lpwr_difr_cg_idle_us'):
                            self.assertFalse(window.entries[key].get_sensitive())
                            self.assertTrue(window.rows[key]['dependency'].get_visible())
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual(window.controller.document.changes,
                                         {'perf_cf_gpc_target_pct': '55', 'lpwr_difr': '0'})
                        # The expander keeps its state across a re-render of the same ROM.
                        expander.set_expanded(True)
                        window.advanced_toggle.set_active(True)
                        self.assertTrue(window.advanced_expander.get_expanded())
                        window.advanced_toggle.set_active(False)
                    finally:
                        window.close()
                    # A ROM that stores the policy off opens with the controller rows greyed out.
                    window = EditorWindow(app, stored_off, language)
                    window.present()
                    try:
                        until(lambda: not window.busy and window.controller.document is not None)
                        self.assertFalse(window.advanced_expander.get_expanded())
                        self.assertFalse(window.entries['perf_cf_util_policy'].get_active())
                        for key in ('perf_cf_gpc_target_pct', 'perf_cf_vid_jump_pct', 'perf_cf_dram_hysteresis_up'):
                            self.assertFalse(window.entries[key].get_sensitive())
                            self.assertTrue(window.rows[key]['dependency'].get_visible())
                        self.assertTrue(window.entries['lpwr_difr_dfpr_idle_ms'].get_sensitive())
                        window.entries['perf_cf_util_policy'].set_active(True)
                        window.entries['perf_cf_vid_jump_pct'].set_text('90')
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual(window.controller.document.changes,
                                         {'perf_cf_util_policy': '1', 'perf_cf_vid_jump_pct': '90'})
                    finally:
                        window.close()

    def test_idle_power_switch_of_an_unlisted_product_notes_the_off_copy(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.gui.app import EditorWindow, texts
        from test_advanced_fields import fixture, set_gr_rail_gating
        app = Gtk.Application(application_id='org.nvidia_vbios.UnlistedLpwrSmoke',
                              flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        with tempfile.TemporaryDirectory() as tmp:
            # An RTX 5080 image with GR rail gating entry 0 enabled: a product whose entries are not reviewed.
            path = Path(tmp) / 'unlisted.rom'
            path.write_bytes(fixture(device=0x2C02, mutate=set_gr_rail_gating(0xFF)).blob)
            for language in ('en', 'es'):
                with self.subTest(language=language):
                    window = EditorWindow(app, path, language)
                    window.present()
                    try:
                        until(lambda: not window.busy and window.controller.document is not None)
                        note = window.text('lpwr.enabled_entries')
                        self.assertIn(note, '\n'.join(texts(window.rows['lpwr_gr_rail_gating']['row'])))
                        self.assertNotIn(note, '\n'.join(texts(window.rows['lpwr_mscg']['row'])))
                        switch = window.entries['lpwr_gr_rail_gating']
                        idle = window.entries['lpwr_gr_rail_gating_idle_us']
                        self.assertTrue(switch.get_active() and idle.get_sensitive())
                        switch.set_active(False)
                        self.assertFalse(idle.get_sensitive())
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual(window.controller.document.changes, {'lpwr_gr_rail_gating': '0'})
                        preview = window.preview_text()
                        self.assertIn(window.text('flag_stock') + ' → ' + window.text('flag_off'), preview)
                        self.assertIn(window.text('change.not_used'), preview)
                    finally:
                        window.close()

    def test_advanced_section_on_ampere_and_turing_roms(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.gui.app import EditorWindow, texts
        from test_advanced_fields import legacy_advanced
        app = Gtk.Application(application_id='org.nvidia_vbios.LegacyAdvancedSmoke',
                              flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        # Each family lists the idle power switches its ROM has.
        shown = {'ampere': ('lpwr_gr_power_gating', 'lpwr_mscg', 'lpwr_gr_rail_gating', 'lpwr_gr_rail_gating_idle_us'),
                 'turing': ('lpwr_gr_power_gating', 'lpwr_mscg')}
        missing = {'ampere': ('lpwr_difr', 'lpwr_nvdec_gating'),
                   'turing': ('lpwr_difr', 'lpwr_gr_rail_gating', 'lpwr_nvdec_gating')}
        with tempfile.TemporaryDirectory() as tmp:
            for family in ('ampere', 'turing'):
                path = Path(tmp) / f'{family}.rom'
                path.write_bytes(legacy_advanced(family).blob)
                for language in ('en', 'es'):
                    with self.subTest(family=family, language=language):
                        window = EditorWindow(app, path, language)
                        window.present()
                        try:
                            until(lambda: not window.busy and window.controller.document is not None)
                            expander = window.advanced_expander
                            self.assertFalse(expander.get_expanded())
                            self.assertIn(window.text('section.advanced_note'), texts(expander.get_child()))
                            for key in ('perf_cf_util_policy', 'perf_cf_vid_target_pct') + shown[family]:
                                self.assertIn(key, window.entries)
                            for key in missing[family]:
                                self.assertNotIn(key, window.entries)
                            if family == 'ampere':
                                # GR rail gating set to Off greys its idle time.
                                window.entries['lpwr_gr_rail_gating'].set_active(False)
                                self.assertFalse(window.entries['lpwr_gr_rail_gating_idle_us'].get_sensitive())
                                self.assertTrue(window.rows['lpwr_gr_rail_gating_idle_us']['dependency'].get_visible())
                                until(lambda: not window.verifying and not window.dirty)
                                self.assertEqual(window.controller.document.changes, {'lpwr_gr_rail_gating': '0'})
                            else:
                                window.entries['perf_cf_vid_target_pct'].set_text('50')
                                until(lambda: not window.verifying and not window.dirty)
                                self.assertEqual(window.controller.document.changes, {'perf_cf_vid_target_pct': '50'})
                                self.assertIn('60 → 50 %', window.preview_text())
                        finally:
                            window.close()

    def test_ada_fixed_voltage_rows_stage_rel_and_alt_together(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.gui.app import EditorWindow, texts
        from test_rail_vmin import ada_xoc
        app = Gtk.Application(application_id='org.nvidia_vbios.AdaVoltageSmoke', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ada.rom'
            path.write_bytes(ada_xoc())
            for language, title in (('en', 'NVVDD REL fixed voltage'), ('es', 'Voltaje fijo REL de NVVDD')):
                with self.subTest(language=language):
                    window = EditorWindow(app, path, language)
                    window.present()
                    try:
                        until(lambda: not window.busy and window.controller.document is not None)
                        self.assertIn(title, '\n'.join(texts(window.field_box)))
                        self.assertIn('nvvdd_alt_fixed_mv', window.entries)
                        # Follow OV stays behind the advanced toggle.
                        self.assertNotIn('nvvdd_rel_alt_follow_ov', window.entries)
                        window.advanced_toggle.set_active(True)
                        self.assertIn('nvvdd_rel_alt_follow_ov', window.entries)
                        # REL above ALT marks both rows of their group; raising ALT with REL verifies.
                        window.entries['nvvdd_rel_fixed_mv'].set_text('1100')
                        window.entries['nvvdd_alt_fixed_mv'].set_text('1050')
                        until(lambda: not window.verifying)
                        for key in ('nvvdd_rel_fixed_mv', 'nvvdd_alt_fixed_mv'):
                            self.assertIn('invalid', window.rows[key]['row'].get_css_classes())
                        self.assertEqual(window.rows['nvvdd_rel_fixed_mv']['delta'].get_text(),
                                         window.text('order_hint_voltage'))
                        window.entries['nvvdd_alt_fixed_mv'].set_text('1100')
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual(window.controller.document.changes['nvvdd_rel_fixed_mv'], '1100')
                        self.assertEqual(window.controller.document.changes['nvvdd_alt_fixed_mv'], '1100')
                    finally:
                        window.close()

    def test_turing_rows_and_advanced_current_thresholds_stage_in_both_languages(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.gui.app import EditorWindow, texts
        from nvidia_vbios.rom import from_bytes
        from nvidia_vbios.rom.image import backend
        from test_ada_fields import patched
        from test_turing import synthetic_turing
        app = Gtk.Application(application_id='org.nvidia_vbios.TuringSmoke', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'turing.rom'
            path.write_bytes(synthetic_turing(inputs=True, rails=True, clocks=True, fans=2))
            for language, title in (('en', 'Connector channel 2 current threshold, rated'),
                                    ('es', 'Umbral de corriente del canal de conector 2, nominal')):
                with self.subTest(language=language):
                    window = EditorWindow(app, path, language)
                    window.present()
                    try:
                        until(lambda: not window.busy and window.controller.document is not None)
                        for key in ('slot_power_max_w', 'connector_2_power_rated_w', 'nvvdd_vmin_mv',
                                    'gpc_offset_max_mhz', 'fan_pwm_frequency_hz', 'fan_1_curve_2_rpm'):
                            self.assertIn(key, window.entries)
                        # Thresholds and the NVVDD current limit stay behind the advanced toggle.
                        for key in ('connector_2_current_threshold_rated_ma', 'nvvdd_output_ocp_rated_ma'):
                            self.assertNotIn(key, window.entries)
                        self.assertNotIn('nvvdd_rel_equation_max_mv', window.entries)
                        window.advanced_toggle.set_active(True)
                        until(lambda: 'connector_2_current_threshold_rated_ma' in window.entries)
                        self.assertIn(title, '\n'.join(texts(window.field_box)))
                        entry = window.entries['connector_2_current_threshold_rated_ma']
                        self.assertEqual(entry.get_text(), '22.5')  # shown in amps
                        entry.set_text('25')
                        window.entries['connector_1_power_max_w'].set_text('200')
                        until(lambda: not window.verifying and not window.dirty)
                        changes = window.controller.document.changes
                        self.assertEqual((changes['connector_2_current_threshold_rated_ma'],
                                          changes['connector_1_power_max_w']), ('25000', '200'))
                        self.assertNotIn(window.text('section.unsupported'), texts(window.field_box))
                        # An unsupported rail layout (REL = OV, ALT below OV) keeps the voltage heading with a note.
                        refused = Path(tmp) / 'refused.rom'
                        row = backend(from_bytes(path.read_bytes())).pointer('P', 0x68) + 5
                        refused.write_bytes(patched(path.read_bytes(), row + 4, b'\x03\x01'))
                        window.open_path(refused)
                        until(lambda: not window.busy and 'nvvdd_vmin_mv' not in window.entries)
                        shown = texts(window.field_box)
                        self.assertEqual(shown.count(window.text('section.unsupported')), 1)
                        self.assertIn(window.text('section.voltage'), shown)
                        self.assertNotIn(window.text('section.voltage_note'), shown)
                    finally:
                        window.close()

    def test_milliamp_fields_are_edited_in_amps(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.gui.app import EditorWindow, texts
        from test_extended_fields import input_fixture
        app = Gtk.Application(application_id='org.nvidia_vbios.AmpSmoke', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.rom'
            path.write_bytes(input_fixture())
            window = EditorWindow(app, path, 'es')
            window.present()
            try:
                until(lambda: not window.busy and window.controller.document is not None)
                entry = window.entries['input_current_rated_ma']
                self.assertEqual(entry.get_text(), '80')
                self.assertEqual(window.rows['input_current_rated_ma']['field']['units'], 'mA')
                entry.set_text('85')
                window.entries['input_current_max_ma'].set_text('85')
                self.assertIn('80 → 85 A', window.rows['input_current_rated_ma']['delta'].get_text())
                until(lambda: not window.verifying and not window.dirty)
                self.assertEqual(window.controller.document.changes['input_current_rated_ma'], '85000')
                self.assertIn('80 → 85 A', window.preview_text())
                # A joint ordering error marks both partners of its group only; a
                # valid power group requested at the same time stays valid.
                window.entries['power_default_w'].set_text('90')
                window.entries['power_max_w'].set_text('150')
                entry.set_text('90')
                until(lambda: not window.verifying)
                for key in ('input_current_rated_ma', 'input_current_max_ma'):
                    self.assertIn('invalid', window.rows[key]['row'].get_css_classes())
                    self.assertEqual(window.rows[key]['delta'].get_text(), window.text('order_hint'))
                for key in ('power_default_w', 'power_max_w'):
                    self.assertNotIn('invalid', window.rows[key]['row'].get_css_classes())
                    self.assertIn('changed', window.rows[key]['row'].get_css_classes())
                self.assertFalse(window.lookup_action('save').get_enabled())
                window.entries['power_default_w'].set_text('70')
                window.entries['power_max_w'].set_text('100')
                # A plain range error is shown in amps.
                window.entries['input_current_max_ma'].set_text('80')
                until(lambda: not window.verifying)
                self.assertIn('invalid', window.rows['input_current_rated_ma']['row'].get_css_classes())
                self.assertIn('80 A', window.rows['input_current_rated_ma']['delta'].get_text())
                self.assertNotIn('80000', window.rows['input_current_rated_ma']['delta'].get_text())
                window.entries['input_current_max_ma'].set_text('85')
                # Typed amps survive hiding and showing the advanced fields.
                entry.set_text('84.5')
                window.advanced_toggle.set_active(True)
                self.assertEqual(window.entries['input_current_rated_ma'].get_text(), '84.5')
                until(lambda: not window.verifying and not window.dirty)
                self.assertEqual(window.controller.document.changes['input_current_rated_ma'], '84500')
                # Fan PWM frequency is typed in kHz and stored in Hz.
                fans = Path(tmp) / 'fans.rom'
                from test_rom_formats import synthetic_blackwell
                fans.write_bytes(synthetic_blackwell(fans=True))
                window.open_path(fans)
                until(lambda: not window.busy and 'fan_pwm_frequency_hz' in window.entries)
                pwm = window.entries['fan_pwm_frequency_hz']
                self.assertEqual(pwm.get_text(), '27')
                self.assertEqual(window.entries['fan_channels'].get_text(), '2')
                field_text = texts(window.field_box)
                self.assertIn(window.text('section.fans'), field_text)
                channel_text = texts(window.rows['fan_channels']['row'])
                self.assertIn('Original: 2', channel_text)
                self.assertNotIn('channels', ' '.join(channel_text))
                self.assertIn('Original: 27 kHz', texts(window.rows['fan_pwm_frequency_hz']['row']))
                pwm.set_text('25')
                window.entries['fan_channels'].set_text('3')
                until(lambda: not window.verifying and not window.dirty)
                self.assertEqual(window.controller.document.changes['fan_pwm_frequency_hz'], '25000')
                self.assertEqual(window.controller.document.changes['fan_channels'], '3')
                window.entries['fan_channels'].set_text('4')
                until(lambda: not window.verifying)
                self.assertIn('invalid', window.rows['fan_channels']['row'].get_css_classes())
                window.entries['fan_channels'].set_text('2')
                pwm.set_text('30')
                until(lambda: not window.verifying)
                self.assertIn('28 kHz', window.rows['fan_pwm_frequency_hz']['delta'].get_text())
                # Channel limits stage in RPM; a channel count with them asks for separate copies.
                pwm.set_text('27')
                window.entries['fan_1_min_rpm'].set_text('900')
                until(lambda: not window.verifying and not window.dirty)
                self.assertEqual(window.controller.document.changes, {'fan_1_min_rpm': '900'})
                self.assertIn('Original: 1050 RPM', texts(window.rows['fan_1_min_rpm']['row']))
                window.entries['fan_channels'].set_text('3')
                until(lambda: not window.verifying)
                self.assertIn(window.text('error.SEPARATE_EDIT_REQUIRED'), window.status.get_text())
                window.entries['fan_channels'].set_text('2')
                until(lambda: not window.verifying and not window.dirty)
                # Level limits only show with the advanced fields.
                self.assertIn('fan_1_min_pct', window.entries)
                window.advanced_toggle.set_active(False)
                self.assertNotIn('fan_1_min_pct', window.entries)
                self.assertEqual(window.entries['fan_1_min_rpm'].get_text(), '900')
                # Curve temperatures show in °C. A maximum below the curves is refused until the points
                # above it move too, then the whole set stages as one copy.
                self.assertIn('Original: 60 °C', texts(window.rows['fan_1_curve_3_temp_c']['row']))
                self.assertNotIn('fan_1_curve_3_pct', window.entries)
                window.entries['fan_1_min_rpm'].set_text('1050')
                window.entries['fan_1_max_rpm'].set_text('3000')
                until(lambda: not window.verifying)
                self.assertIn('invalid', window.rows['fan_1_max_rpm']['row'].get_css_classes())
                top = ('fan_1_curve_3_rpm', 'fan_extra_1_curve_3_rpm', 'fan_extra_2_curve_3_rpm')
                for key in top:
                    window.entries[key].set_text('3000')
                until(lambda: not window.verifying and not window.dirty)
                self.assertEqual(window.controller.document.changes, {key: '3000' for key in ('fan_1_max_rpm',) + top})
                self.assertNotIn('invalid', window.rows['fan_1_max_rpm']['row'].get_css_classes())
            finally:
                window.close()
                while context.pending():
                    context.iteration(False)

    def test_a_fan_channel_count_checks_saves_and_comes_back_in_both_languages(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from unittest.mock import patch
        from nvidia_vbios.editor import edit, load
        from nvidia_vbios.gui.app import EditorWindow, texts
        from nvidia_vbios.rom import from_bytes
        from test_rom_formats import synthetic_blackwell
        app = Gtk.Application(application_id='org.nvidia_vbios.FanChannelSmoke',
                              flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        with tempfile.TemporaryDirectory() as tmp:
            two, three = Path(tmp) / 'two.rom', Path(tmp) / 'three.rom'
            two.write_bytes(synthetic_blackwell(fans=True))
            three.write_bytes(edit(from_bytes(two.read_bytes()), {'fan_channels': 3}).blob)
            for language in ('en', 'es'):
                with self.subTest(language=language):
                    window = EditorWindow(app, three, language)
                    window.present()
                    try:
                        until(lambda: not window.busy and window.controller.document is not None)
                        channels, fan_3 = window.entries['fan_channels'], window.entries['fan_3_min_rpm']
                        note = window.rows['fan_3_min_rpm']['dependency']
                        self.assertEqual((channels.get_text(), fan_3.get_text()), ('3', '1050'))
                        fan_3.set_text('1000')
                        until(lambda: not window.verifying and not window.dirty)
                        # A lower count clears the last channel: its rows go back to the stored values and grey out,
                        # and the check ends with the cleared fields listed as not used.
                        channels.set_text('2')
                        self.assertEqual(fan_3.get_text(), '1050')
                        self.assertFalse(fan_3.is_sensitive())
                        self.assertTrue(note.get_visible())
                        self.assertIn(window.text('reason.fan_channel_off', count=2, fan=3), texts(note))
                        self.assertTrue(window.entries['fan_2_min_rpm'].is_sensitive())
                        until(lambda: not window.verifying and not window.dirty)
                        document = window.controller.document
                        self.assertEqual(document.changes, {'fan_channels': '2'})
                        self.assertEqual(window.status.get_text(), window.text(
                            'live_ok', count=16, bytes=document.proposal.manifest['changed_bytes']))
                        self.assertFalse(window.spinner.get_spinning())
                        self.assertIn('3 → 2', window.preview_text())
                        self.assertIn(f"1050 RPM → {window.text('change.not_used')}", window.preview_text())
                        self.assertTrue(window.lookup_action('save').get_enabled())
                        self.assertTrue(window.save_button.is_sensitive())
                        output = Path(tmp) / f'two-{language}.rom'
                        window._accept_save_path(output, document)
                        until(lambda: not window.busy)
                        self.assertTrue(window.status.get_text().startswith(window.text(
                            'saved', output=output, manifest=f'{output}.json')))
                        self.assertEqual({f['key']: f['current'] for f in load(output).report['fields']}
                                         ['fan_channels'], 2)
                        # The stored count again: the rows come back with the value typed before the count.
                        channels.set_text('3')
                        self.assertTrue(fan_3.is_sensitive())
                        self.assertFalse(note.get_visible())
                        self.assertEqual(fan_3.get_text(), '1000')
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual(window.controller.document.changes, {'fan_3_min_rpm': '1000'})
                        fan_3.set_text('1050')
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual(window.status.get_text(), window.text('live_same'))
                        self.assertEqual(window.preview_text(), window.text('live_none'))
                        # An unexpected exception in the window's own code ends the check with the error, Save off.
                        refresh = window._refresh
                        with patch.object(window, '_refresh', side_effect=RuntimeError('broken view')), \
                                patch('nvidia_vbios.gui.app.traceback.print_exc') as printed:
                            channels.set_text('1')
                            until(lambda: not window.verifying)
                        self.assertEqual(window._refresh, refresh)
                        printed.assert_called_once()
                        self.assertEqual(window.status.get_text(), window.text(
                            'unexpected', message='broken view', code='RuntimeError'))
                        self.assertTrue(window.status.has_css_class('error'))
                        self.assertFalse(window.spinner.get_spinning())
                        self.assertFalse(window.lookup_action('save').get_enabled())
                        channels.set_text('3')
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual(window.status.get_text(), window.text('live_same'))
                        self.assertFalse(window.status.has_css_class('error'))
                        # A higher count enables the stored channel of a two-channel image.
                        window.open_path(two)
                        until(lambda: not window.busy and window.entries['fan_channels'].get_text() == '2')
                        self.assertNotIn('fan_3_min_rpm', window.entries)
                        window.entries['fan_channels'].set_text('3')
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertTrue(window.status.get_text().startswith(window.text(
                            'live_ok', count=16, bytes=0).split(':')[0]))
                        self.assertIn(f"{window.text('change.not_used')} → 1050 RPM", window.preview_text())
                        self.assertTrue(window.lookup_action('save').get_enabled())
                    finally:
                        window.close()
                        while context.pending():
                            context.iteration(False)

    def test_values_a_fan_channel_count_greys_out_are_kept_and_imported_in_both_languages(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from unittest.mock import patch
        from nvidia_vbios.editor import edit
        from nvidia_vbios.gui.app import EditorWindow, texts
        from nvidia_vbios.gui.presentation import primary_preview
        from nvidia_vbios.rom import from_bytes
        from test_rom_formats import synthetic_blackwell
        app = Gtk.Application(application_id='org.nvidia_vbios.FanChannelKeepSmoke',
                              flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        with tempfile.TemporaryDirectory() as tmp:
            three, donor = Path(tmp) / 'three.rom', Path(tmp) / 'donor.rom'
            blob = edit(from_bytes(synthetic_blackwell(fans=True)), {'fan_channels': 3}).blob
            three.write_bytes(blob)
            # Another three-channel image with other fan 3 values: the maximum and a curve point, with its level.
            imported = {'fan_3_max_rpm': '3600', 'fan_3_curve_2_rpm': '2500', 'fan_3_curve_2_pct': '60'}
            donor.write_bytes(edit(from_bytes(blob), {key: int(value) for key, value in imported.items()}).blob)
            for language in ('en', 'es'):
                with self.subTest(language=language):
                    window = EditorWindow(app, three, language)
                    window.present()
                    try:
                        until(lambda: not window.busy and window.controller.document is not None)
                        entries, channels = window.entries, window.entries['fan_channels']
                        idle = lambda: not window.verifying and not window.dirty
                        typed = {'fan_2_curve_2_rpm': '2300', 'fan_3_curve_2_rpm': '2350'}
                        for key, text in typed.items():
                            entries[key].set_text(text)
                        until(idle)
                        self.assertEqual(window.controller.document.changes, typed)
                        # A count typo corrected at once (GTK deletes, then inserts): while it reads 1 the rows of
                        # fans 2 and 3 show their stored values, and the typed values come back with the count.
                        for text in ('', '1', '', '3'):
                            channels.set_text(text)
                            if text == '1':
                                self.assertEqual({key: entries[key].get_text() for key in typed},
                                                 {'fan_2_curve_2_rpm': '2200', 'fan_3_curve_2_rpm': '2200'})
                                self.assertFalse(entries['fan_2_curve_2_rpm'].is_sensitive())
                        self.assertEqual({key: entries[key].get_text() for key in typed}, typed)
                        until(idle)
                        self.assertEqual(window.controller.document.changes, typed)
                        # Fan 3 values, a lower count, then an import from an image with the stored count: every
                        # imported value is staged, fan 3 included, the count goes back to the shared one, and the
                        # values typed before the count give way to the other image's.
                        window.lookup_action('reset').activate(None)
                        channels = entries['fan_channels']           # a reset renders new rows
                        entries['fan_3_curve_1_rpm'].set_text('1100')
                        entries['fan_3_curve_2_rpm'].set_text('2350')
                        until(idle)
                        channels.set_text('2')
                        until(idle)
                        self.assertEqual(window.controller.document.changes, {'fan_channels': '2'})
                        done = []
                        self.assertIsNotNone(window.import_path(donor, ['fans'], on_done=done.append))
                        until(lambda: done and idle())
                        self.assertEqual(done[0][0], (window.text('import.applied', count=3, file='donor.rom'),
                                                      'heading'))
                        document = window.controller.document
                        self.assertEqual(document.changes, imported)
                        self.assertEqual(len(primary_preview(document)), 3)
                        self.assertEqual(channels.get_text(), '3')
                        self.assertEqual([entries[key].get_text() for key in
                                          ('fan_3_max_rpm', 'fan_3_curve_1_rpm', 'fan_3_curve_2_rpm')],
                                         ['3600', '1050', '2500'])
                        self.assertTrue(entries['fan_3_curve_2_rpm'].is_sensitive())
                        # A hidden advanced value of fan 3 stays out of a lower count's check, comes back as the
                        # greyed-out row's parked value, and returns with the count.
                        window.lookup_action('reset').activate(None)
                        window.advanced_toggle.set_active(True)
                        entries['fan_3_curve_2_pct'].set_text('60')
                        until(idle)
                        window.advanced_toggle.set_active(False)
                        entries['fan_channels'].set_text('2')
                        # The provisional list has the count only, without the hidden values the toggle keeps.
                        self.assertEqual(len(window.preview_text().split('\n')), 2)
                        until(idle)
                        document = window.controller.document
                        self.assertEqual(document.changes, {'fan_channels': '2'})
                        verified = window.text('live_ok', count=16, bytes=document.proposal.manifest['changed_bytes'])
                        self.assertEqual(window.status.get_text(), verified)
                        window.advanced_toggle.set_active(True)
                        level = entries['fan_3_curve_2_pct']
                        self.assertEqual(level.get_text(), '50')
                        self.assertFalse(level.is_sensitive())
                        until(idle)
                        self.assertEqual(window.status.get_text(), verified)
                        self.assertTrue(window.lookup_action('save').get_enabled())
                        # Hidden again, then the stored count: the value is checked again.
                        window.advanced_toggle.set_active(False)
                        entries['fan_channels'].set_text('3')
                        until(idle)
                        self.assertEqual(window.controller.document.changes, {'fan_3_curve_2_pct': '60'})
                        window.advanced_toggle.set_active(True)
                        self.assertEqual(entries['fan_3_curve_2_pct'].get_text(), '60')
                        self.assertTrue(entries['fan_3_curve_2_pct'].is_sensitive())
                        # An unexpected exception while importing also ends the dialog's wait.
                        dialog = window.show_import_dialog(donor)
                        dialog.checks['fans'].set_active(True)
                        with patch('nvidia_vbios.gui.app.import_summary', side_effect=RuntimeError('broken summary')), \
                                patch('nvidia_vbios.gui.app.traceback.print_exc'):
                            dialog.accept_button.emit('clicked')
                            until(lambda: window.importing is None)
                        unexpected = window.text('unexpected', message='broken summary', code='RuntimeError')
                        self.assertEqual(texts(dialog.summary), [window.text('import.failed', message=unexpected)])
                        self.assertEqual(dialog.cancel_button.get_label(), window.text('import.close'))
                        self.assertEqual(window.status.get_text(), unexpected)
                        dialog.close()
                    finally:
                        window.close()
                        while context.pending():
                            context.iteration(False)

    def test_fan_curve_blockers_follow_both_pending_channels_in_both_languages(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.gui.app import EditorWindow
        from nvidia_vbios.gui.presentation import row_title
        from test_rom_formats import synthetic_rom
        app = Gtk.Application(application_id='org.nvidia_vbios.FanHintSmoke',
                              flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'two-fan-copies.rom'
            path.write_bytes(synthetic_rom(copies=2, fans=2))
            for language in ('en', 'es'):
                with self.subTest(language=language):
                    window = EditorWindow(app, path, language)
                    window.present()
                    try:
                        until(lambda: not window.busy and window.controller.document is not None)
                        fields = {f['key']: f for f in window.controller.document.report['fields']}

                        def title(key):
                            return row_title(fields[key], language)[0]

                        def delta(key):
                            return window.rows[key]['delta'].get_text()

                        minima = ('fan_1_min_rpm', 'fan_2_min_rpm')
                        own = ('fan_1_curve_1_rpm', 'fan_2_curve_1_rpm')
                        extras = ('fan_extra_1_curve_1_rpm', 'fan_extra_2_curve_1_rpm')
                        for key in minima:
                            window.entries[key].set_text('1200')
                        until(lambda: not window.verifying)
                        self.assertFalse(window.lookup_action('save').get_enabled())
                        for n, key in enumerate(minima):
                            self.assertIn('invalid', window.rows[key]['row'].get_css_classes())
                            self.assertIn('1000 RPM', delta(key))
                            self.assertIn(title(own[n]), delta(key))
                            # A minimum is held by the channel's own curve only: the extra curves may stay below it.
                            for other in (own[1-n],) + extras:
                                self.assertNotIn(title(other), delta(key))
                            self.assertNotEqual(delta(key), window.text('order_hint'))
                        # The backend reports one owner; its range remains alongside the curve hint.
                        owner = 'fan_1_min_rpm'
                        self.assertIn(window.text('range_hint', minimum='0', maximum='1000', units='RPM'), delta(owner))
                        for key in own:
                            window.entries[key].set_text('1200')
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertTrue(window.lookup_action('save').get_enabled())
                        self.assertEqual(window.controller.document.changes, {key: '1200' for key in minima + own})
                        for key in minima:
                            self.assertNotIn('invalid', window.rows[key]['row'].get_css_classes())
                        # The last points explain a reduced maximum, with no first-point blame.
                        window._reset()
                        window.entries['fan_1_max_rpm'].set_text('3000')
                        until(lambda: not window.verifying)
                        hint = delta('fan_1_max_rpm')
                        self.assertIn('3300 RPM', hint)
                        for prefix in ('fan_1', 'fan_extra_1', 'fan_extra_2'):
                            self.assertIn(title(prefix + '_curve_3_rpm'), hint)
                        self.assertNotIn(title('fan_1_curve_1_rpm'), hint)
                        self.assertFalse(window.lookup_action('save').get_enabled())
                        # Encoding still rejects a fractional stored RPM even when all curves fit.
                        window._reset()
                        window.entries['fan_1_min_rpm'].set_text('900.5')
                        until(lambda: not window.verifying)
                        self.assertFalse(window.lookup_action('save').get_enabled())
                        self.assertNotIn(title('fan_1_curve_1_rpm'), delta('fan_1_min_rpm'))
                        self.assertNotIn(title('fan_extra_1_curve_1_rpm'), delta('fan_1_min_rpm'))
                        # All curves fit 2200 RPM, but the preserved speed-table entry is 2295.
                        window._reset()
                        window.entries['fan_1_max_rpm'].set_text('2200')
                        for prefix in ('fan_1', 'fan_extra_1', 'fan_extra_2'):
                            window.entries[prefix + '_curve_3_rpm'].set_text('2200')
                        until(lambda: not window.verifying)
                        self.assertFalse(window.lookup_action('save').get_enabled())
                        for prefix in ('fan_1', 'fan_extra_1', 'fan_extra_2'):
                            self.assertNotIn(title(prefix + '_curve_3_rpm'), delta('fan_1_max_rpm'))
                    finally:
                        window.close()
                        while context.pending():
                            context.iteration(False)

    def test_flag_fields_are_switches_that_stage_and_unstage(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.gui.app import EditorWindow, texts
        from nvidia_vbios.rom import from_bytes
        from nvidia_vbios.rom.image import backend
        from test_extended_fields import repair_fixture
        from test_rail_vmin import blackwell_vmin
        from test_rom_formats import synthetic_blackwell
        app = Gtk.Application(application_id='org.nvidia_vbios.FlagSmoke', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        blob = bytearray(synthetic_blackwell(fans=True))
        table = backend(from_bytes(bytes(blob))).fan_coolers()
        for entry in [r for r in table['rows'] if r['active']] + table['extra_curves']:
            blob[entry['policy_offset'] + 46] = 0xFF  # no fan-stop parameters: 1 is not offered
        with tempfile.TemporaryDirectory() as tmp:
            fans, maxq, xoc = Path(tmp) / 'fans.rom', Path(tmp) / 'maxq.rom', Path(tmp) / 'xoc.rom'
            fans.write_bytes(synthetic_blackwell(fans=True))
            maxq.write_bytes(repair_fixture(blob))
            xoc.write_bytes(blackwell_vmin(legacy=True))
            for language in ('en', 'es'):
                window = EditorWindow(app, fans, language)
                window.present()
                on, off = window.text('flag_on'), window.text('flag_off')
                try:
                    until(lambda: not window.busy and window.controller.document is not None)
                    # Opt-in: the switch shows with the advanced fields.
                    self.assertNotIn('fan_zero_rpm', window.entries)
                    window.advanced_toggle.set_active(True)
                    switch = window.entries['fan_zero_rpm']
                    self.assertIsInstance(switch, Gtk.Switch)
                    self.assertFalse(switch.get_active())
                    row = window.rows['fan_zero_rpm']
                    self.assertIn(window.text('original', value=off, units='').rstrip(), texts(row['row']))
                    switch.set_active(True)
                    until(lambda: not window.verifying and not window.dirty)
                    self.assertEqual(window.controller.document.changes, {'fan_zero_rpm': '1'})
                    self.assertIn('changed', row['row'].get_css_classes())
                    self.assertEqual(row['delta'].get_text(), f'{off} → {on}')
                    self.assertIn(f'{off} → {on}', window.preview_text())
                    # Switching it back off unstages it.
                    switch.set_active(False)
                    until(lambda: not window.verifying and not window.dirty)
                    self.assertEqual(window.controller.document.changes, {})
                    self.assertNotIn('changed', row['row'].get_css_classes())
                    # Read-only rows show the state as text.
                    window.open_path(maxq)
                    until(lambda: not window.busy and window.controller.document.original.name == str(maxq))
                    self.assertNotIn('fan_zero_rpm', window.entries)
                    self.assertIn(off, texts(window.readonly_rows['fan_zero_rpm']))
                    # The XOC-style REL/ALT flag (0 -> 1 only) is a switch too; off again unstages it.
                    window.open_path(xoc)
                    until(lambda: not window.busy and window.controller.document.original.name == str(xoc))
                    follow = window.entries['nvvdd_rel_alt_follow_ov']
                    self.assertIsInstance(follow, Gtk.Switch)
                    follow.set_active(True)
                    until(lambda: not window.verifying and not window.dirty)
                    self.assertEqual(window.controller.document.changes, {'nvvdd_rel_alt_follow_ov': '1'})
                    follow.set_active(False)
                    until(lambda: not window.verifying and not window.dirty)
                    self.assertEqual(window.controller.document.changes, {})
                finally:
                    window.close()
                    while context.pending():
                        context.iteration(False)

    def test_zero_rpm_rows_show_mixed_state_template_notes_and_the_start_rule(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.gui.app import EditorWindow, texts
        from nvidia_vbios.rom import from_bytes
        from nvidia_vbios.rom.image import backend
        from test_ada_fields import REFERENCE_BLOCK, patched, template_board, with_zero_rpm
        from test_rom_formats import synthetic_rom
        app = Gtk.Application(application_id='org.nvidia_vbios.ZeroRpmSmoke', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        blob = synthetic_rom(copies=2, fans=2)
        # One active channel and a stored second one with 40/60 C over its 55 C point 1, zero RPM on.
        one = synthetic_rom(family='ampere', copies=2, fans=3)
        second = backend(from_bytes(one)).fan_coolers()['rows'][1]['policy_offset']
        one = with_zero_rpm(one, pairs=((40, 50), (53, 63), (60, 70), (60, 70)))
        one = patched(patched(one, second + 30, struct.pack('<HH', 40 * 32, 60 * 32) + REFERENCE_BLOCK), second + 0x32,
                      b'\x17')
        with tempfile.TemporaryDirectory() as tmp:
            mixed, blower, stuck, later = (Path(tmp) / f'{name}.rom' for name in ('mixed', 'blower', 'stuck', 'later'))
            mixed.write_bytes(with_zero_rpm(with_zero_rpm(blob, flags=(0x13, 0x03)), flags=(0x17, 0x07), entries=(2,)))
            blower.write_bytes(template_board())
            # Zero RPM off, channel lowers at 56 C over point 1 at 55 C (as an RTX 3050 stores them).
            stuck.write_bytes(with_zero_rpm(synthetic_rom(family='ampere', copies=2, fans=2), flags=(0x11, 0x01),
                                            pairs=((56, 60), (56, 60), (53, 63), (60, 70))))
            later.write_bytes(one)
            for language in ('en', 'es'):
                window = EditorWindow(app, mixed, language)
                window.present()
                try:
                    until(lambda: not window.busy and window.controller.document is not None)
                    window.advanced_toggle.set_active(True)
                    # Bit 2 on some entries only: a read-only row that reads Mixed, never None.
                    shown = texts(window.readonly_rows['fan_zero_rpm'])
                    self.assertIn(window.text('flag_mixed'), shown)
                    self.assertIn(window.text('reason.fan_zero_rpm_mixed'), shown)
                    self.assertFalse([text for row in window.readonly_rows.values() for text in texts(row)
                                      if 'None' in text])
                    # A blower board without fan-stop values: the switch notes the values it writes, the risks and
                    # the flag form with bit 4 clear.
                    window.open_path(blower)
                    until(lambda: not window.busy and window.controller.document.original.name == str(blower))
                    notes = texts(window.rows['fan_zero_rpm']['row'])
                    self.assertTrue(any(window.text('fan_stop.blower') == note for note in notes))
                    self.assertTrue(any(note.startswith(window.text('fan_stop.template', donor='X', pairs='Y')[:30])
                                        for note in notes))
                    self.assertIn(window.text('fan_stop.bit4'), notes)
                    self.assertIn(window.text('fan_stop.manual'), notes)
                    self.assertNotIn(window.text('fan_stop.off'), notes)
                    # Its curve starts at 55 C, below the 60 C the template's values start at: the switch and
                    # point 1 are marked.
                    window.entries['fan_zero_rpm'].set_active(True)
                    until(lambda: not window.verifying)
                    self.assertIn(window.text('error.ZERO_RPM_ABOVE_CURVE'), window.status.get_text())
                    for key in ('fan_zero_rpm', 'fan_1_curve_1_temp_c'):
                        self.assertIn('invalid', window.rows[key]['row'].get_css_classes())
                        self.assertEqual(window.rows[key]['delta'].get_text(), window.text('zero_rpm_hint'))
                    window.entries['fan_1_curve_1_temp_c'].set_text('60')
                    until(lambda: not window.verifying and not window.dirty)
                    self.assertEqual(window.controller.document.changes,
                                     {'fan_zero_rpm': '1', 'fan_1_curve_1_temp_c': '60'})
                    # Lowers at or above point 1: turning zero RPM on marks them with their own hint, and the upper
                    # shows the range an edit with the lower allows.
                    window.open_path(stuck)
                    until(lambda: not window.busy and window.controller.document.original.name == str(stuck))
                    self.assertIn(window.text('fan_stop.off'), texts(window.rows['fan_zero_rpm']['row']))
                    window.entries['fan_zero_rpm'].set_active(True)
                    until(lambda: not window.verifying)
                    self.assertIn(window.text('error.ZERO_RPM_ABOVE_CURVE'), window.status.get_text())
                    for key in ('fan_1_zero_rpm_low_temp_c', 'fan_2_zero_rpm_low_temp_c'):
                        self.assertIn('invalid', window.rows[key]['row'].get_css_classes())
                        self.assertEqual(window.rows[key]['delta'].get_text(), window.text('zero_rpm_lower_hint'))
                    self.assertEqual(window.rows['fan_1_zero_rpm_high_temp_c']['delta'].get_text(),
                                     window.text('range_hint', minimum='0.0625', maximum='55', units='°C'))
                    for key, value in (('fan_1_zero_rpm_high_temp_c', '55'), ('fan_1_zero_rpm_low_temp_c', '50'),
                                       ('fan_2_zero_rpm_high_temp_c', '55'), ('fan_2_zero_rpm_low_temp_c', '50')):
                        window.entries[key].set_text(value)
                    until(lambda: not window.verifying and not window.dirty)
                    self.assertEqual(window.controller.document.changes['fan_zero_rpm'], '1')
                    # A larger channel count that enables a stored fan above its curve with zero RPM on: what works.
                    window.open_path(later)
                    until(lambda: not window.busy and window.controller.document.original.name == str(later))
                    window.entries['fan_channels'].set_text('2')
                    until(lambda: not window.verifying)
                    self.assertIn(window.text('zero_rpm_channels_hint'), window.status.get_text())
                    self.assertIn('invalid', window.rows['fan_channels']['row'].get_css_classes())
                    self.assertEqual(window.rows['fan_channels']['delta'].get_text(),
                                     window.text('zero_rpm_channels_hint'))
                finally:
                    window.close()
                    while context.pending():
                        context.iteration(False)

    def test_memory_section_reads_lazily_and_compares_without_touching_the_document(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.gui.app import EditorWindow, texts
        from test_rom_formats import synthetic_rom
        app = Gtk.Application(application_id='org.nvidia_vbios.MemorySmoke', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        with tempfile.TemporaryDirectory() as tmp:
            path, other = Path(tmp) / 'memory.rom', Path(tmp) / 'other.rom'
            blob = synthetic_rom(memory=True)
            path.write_bytes(blob)
            changed = bytearray(blob)
            changed[blob.index(bytes.fromhex('4f fd 6a 1a'))] += 1     # tRC of timing entry 1
            other.write_bytes(bytes(changed))
            for language in ('en', 'es'):
                with self.subTest(language=language):
                    window = EditorWindow(app, path, language)
                    window.present()
                    try:
                        until(lambda: not window.busy and window.controller.document is not None)
                        expander = window.memory_expander
                        self.assertEqual(expander.get_label(), window.text('memory.title'))
                        self.assertFalse(expander.get_expanded())
                        self.assertIsNone(window.memory['report'])          # read only when expanded
                        expander.set_expanded(True)
                        until(lambda: window.memory['report'] is not None)
                        shown = '\n'.join(texts(window.memory_box))
                        self.assertIn(window.text('memory.note'), shown)
                        self.assertIn(window.text('memory.confidence.inferred'), shown)
                        self.assertIn('T01', shown)
                        self.assertIn('253', shown)
                        window.entries['power_max_w'].set_text('150')
                        until(lambda: not window.verifying and not window.dirty)
                        document, preview = window.controller.document, window.preview_text()
                        window.compare_memory_path(other)
                        until(lambda: not window.memory['comparing'])
                        lines = texts(window.memory_compare_box)
                        timings = window.text('memory.section.timings')
                        self.assertIn(window.text('memory.differs_entries', section=timings, count=1), lines)
                        self.assertIs(window.controller.document, document)
                        self.assertEqual(document.changes, {'power_max_w': '150'})
                        self.assertEqual(window.preview_text(), preview)
                        self.assertTrue(window.lookup_action('save').get_enabled())
                        # A re-render keeps the report, the open section and the comparison.
                        report = window.memory['report']
                        window.advanced_toggle.set_active(True)
                        self.assertTrue(window.memory_expander.get_expanded())
                        self.assertIs(window.memory['report'], report)
                        self.assertIn(window.text('memory.differs_entries', section=timings, count=1),
                                      texts(window.memory_compare_box))
                        window.compare_memory_path(Path(tmp) / 'missing.rom')
                        until(lambda: not window.memory['comparing'])
                        self.assertIn('IO_ERROR', '\n'.join(texts(window.memory_compare_box)))
                        self.assertIs(window.controller.document, document)
                        window.open_path(other)
                        until(lambda: not window.busy and window.controller.document.original.name == str(other))
                        self.assertIsNone(window.memory['report'])
                        self.assertFalse(window.memory_expander.get_expanded())
                    finally:
                        window.close()
                        while context.pending():
                            context.iteration(False)

    def test_import_from_another_rom_types_in_pending_changes(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.editor import edit
        from nvidia_vbios.gui.app import IMPORT_SUMMARY_HEIGHT, EditorWindow, texts
        from nvidia_vbios.gui.presentation import row_title
        from nvidia_vbios.rom import from_bytes
        from test_rom_formats import synthetic_blackwell, synthetic_rom
        app = Gtk.Application(application_id='org.nvidia_vbios.ImportSmoke', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        def summary_height(dialog):
            """(height of the summary's scroll area, height that shows its lines up to the cap, natural height)."""
            scroll = dialog.summary.get_ancestor(Gtk.ScrolledWindow)
            natural = dialog.summary.measure(Gtk.Orientation.VERTICAL, scroll.get_width())[1]
            return scroll.get_height(), min(natural, IMPORT_SUMMARY_HEIGHT), natural

        with tempfile.TemporaryDirectory() as tmp:
            path, other, ada = Path(tmp) / 'board.rom', Path(tmp) / 'other.rom', Path(tmp) / 'ada.rom'
            fewer = Path(tmp) / 'fewer.rom'
            blob = synthetic_blackwell(fans=True)
            path.write_bytes(blob)
            other.write_bytes(edit(from_bytes(blob), {'fan_pwm_frequency_hz': 25000, 'fan_zero_rpm': 1,
                                                      'power_max_w': 120, 'fan_1_curve_2_rpm': 2000,
                                                      'fan_1_curve_2_pct': 40}).blob)
            fewer.write_bytes(edit(from_bytes(blob), {'fan_channels': 1}).blob)
            ada.write_bytes(synthetic_rom())
            for language in ('en', 'es'):
                with self.subTest(language=language):
                    window = EditorWindow(app, path, language)
                    window.present()
                    try:
                        until(lambda: not window.busy and window.controller.document is not None)
                        self.assertTrue(window.lookup_action('import').get_enabled())
                        window.entries['power_max_w'].set_text('110')    # another section's pending value stays
                        # A pending value where both ROMs agree gets their value back.
                        window.entries['fan_1_curve_1_temp_c'].set_text('45')
                        until(lambda: not window.verifying and not window.dirty)
                        dialog = window.show_import_dialog(other)
                        self.assertFalse(dialog.accept_button.get_sensitive())
                        dialog.checks['fans'].set_active(True)
                        self.assertTrue(dialog.accept_button.get_sensitive())
                        dialog.accept_button.emit('clicked')
                        until(lambda: window.importing is None and not window.verifying and not window.dirty)
                        # The curve point comes with its level, which stays behind the advanced toggle.
                        curve = {'fan_1_curve_2_rpm': '2000', 'fan_1_curve_2_pct': '40'}
                        self.assertEqual(window.controller.document.changes,
                                         {'power_max_w': '110', 'fan_pwm_frequency_hz': '25000', **curve})
                        self.assertEqual(window.entries['fan_pwm_frequency_hz'].get_text(), '25')
                        self.assertEqual(window.entries['fan_1_curve_1_temp_c'].get_text(), '50')
                        self.assertEqual(window.hidden_text, {'fan_1_curve_2_pct': '40'})
                        level = next(f for f in window.controller.document.report['fields']
                                     if f['key'] == 'fan_1_curve_2_pct')
                        self.assertIn(row_title(level, language)[0], window.preview_text())
                        self.assertIn('changed', window.rows['fan_pwm_frequency_hz']['row'].get_css_classes())
                        shown = texts(dialog.summary)
                        self.assertIn(window.text('import.applied', count=3, file='other.rom'), shown)
                        self.assertIn(window.text('import.reason.opt_in'), '\n'.join(shown))
                        self.assertEqual(dialog.cancel_button.get_label(), window.text('import.close'))
                        self.assertFalse(window.advanced_toggle.get_active())
                        # The dialog grows to show the whole summary.
                        until(lambda: summary_height(dialog)[0] >= summary_height(dialog)[2])
                        dialog.cancel_button.emit('clicked')
                        # Opt-in values open the advanced rows; the earlier values stay pending.
                        self.assertIsNotNone(window.import_path(other, ['fans'], include_opt_in=True))
                        self.assertFalse(window.lookup_action('import').get_enabled())
                        until(lambda: window.importing is None and not window.verifying and not window.dirty)
                        self.assertTrue(window.advanced_toggle.get_active())
                        self.assertTrue(window.entries['fan_zero_rpm'].get_active())
                        self.assertEqual(window.entries['fan_1_curve_2_pct'].get_text(), '40')
                        self.assertEqual(window.controller.document.changes,
                                         {'power_max_w': '110', 'fan_pwm_frequency_hz': '25000', 'fan_zero_rpm': '1',
                                          **curve})
                        self.assertTrue(window.lookup_action('save').get_enabled())
                        # Another family is refused in the summary and changes nothing.
                        document = window.controller.document
                        window.import_path(ada, ['fans'])
                        until(lambda: window.importing is None)
                        self.assertIn('FAMILY_MISMATCH', window.import_lines[0][0])
                        self.assertIs(window.controller.document, document)
                        # A longer summary grows the dialog up to its cap and scrolls beyond it.
                        dialog = window.show_import_dialog(fewer)
                        dialog.checks['fans'].set_active(True)
                        dialog.accept_button.emit('clicked')
                        until(lambda: window.importing is None and not window.verifying and not window.dirty)
                        self.assertGreater(len(window.import_lines), 15)
                        until(lambda: summary_height(dialog)[0] >= summary_height(dialog)[1])
                        self.assertGreater(summary_height(dialog)[2], IMPORT_SUMMARY_HEIGHT)
                        self.assertLessEqual(summary_height(dialog)[0], IMPORT_SUMMARY_HEIGHT)
                        dialog.close()
                        # Closing the dialog before the import ends drops its result.
                        dialog = window.show_import_dialog(other)
                        dialog.checks['power'].set_active(True)
                        dialog.accept_button.emit('clicked')
                        self.assertIsNotNone(window.importing)
                        dialog.close()
                        self.assertIsNone(window.importing)
                        for _ in range(50):
                            while context.pending():
                                context.iteration(False)
                            time.sleep(.01)
                        self.assertEqual(window.entries['power_max_w'].get_text(), '110')
                    finally:
                        window.close()
                        while context.pending():
                            context.iteration(False)

    def test_shunt_multiplier_is_display_only(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, GLib, Gtk
        from nvidia_vbios.gui.app import EditorWindow, texts
        from test_extended_fields import input_fixture
        from test_rom_formats import synthetic_blackwell
        app = Gtk.Application(application_id='org.nvidia_vbios.ShuntSmoke', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.rom'
            path.write_bytes(input_fixture())
            window = EditorWindow(app, path)
            window.present()
            try:
                until(lambda: not window.busy and window.controller.document is not None)

                def note(key):
                    return window.shunt_notes[key][0]
                self.assertFalse(note('power_max_w').get_visible())
                self.assertFalse(window.shunt_help.get_visible())
                self.assertNotIn('nvvdd_output_ocp_rated_ma', window.shunt_notes)
                self.assertNotIn('current_limit_a', window.shunt_notes)
                window.entries['power_max_w'].set_text('150')
                until(lambda: not window.verifying and not window.dirty)
                document, preview, revision = window.controller.document, window.preview_text(), window.input_revision
                entry = window.entries['power_max_w']
                window.shunt_entry.set_text('2')
                self.assertTrue(window.shunt_help.get_visible())
                self.assertTrue(note('power_max_w').get_visible())
                self.assertEqual(note('power_max_w').get_text(), 'About 300 W real with a x2 shunt')
                self.assertEqual(note('input_current_rated_ma').get_text(), 'About 160 A real with a x2 shunt')
                # Nothing is staged, re-rendered or verified.
                self.assertIs(window.controller.document, document)
                self.assertIs(window.entries['power_max_w'], entry)
                self.assertEqual(document.changes, {'power_max_w': '150'})
                self.assertEqual((window.dirty, window.verifying, window.verify_source, window.input_revision),
                                 (False, False, 0, revision))
                self.assertEqual(window.preview_text(), preview)
                self.assertEqual(entry.get_text(), '150')
                self.assertTrue(window.lookup_action('save').get_enabled())
                # The line follows typing; unverified typed text survives a multiplier change.
                entry.set_text('160')
                self.assertIn('320 W', note('power_max_w').get_text())
                window.shunt_entry.set_text('3')
                self.assertIs(window.entries['power_max_w'], entry)
                self.assertEqual(entry.get_text(), '160')
                self.assertIn('480 W', note('power_max_w').get_text())
                entry.set_text('abc')
                self.assertFalse(note('power_max_w').get_visible())
                entry.set_text('150')
                until(lambda: not window.verifying and not window.dirty)
                # '.' decimals as in the fields, whatever the host locale; at most x10.
                window.shunt_entry.set_text('2,67')
                self.assertTrue(window.shunt_entry.has_css_class('error'))
                self.assertFalse(window.shunt_help.get_visible())
                window.shunt_entry.set_text('20')
                self.assertEqual(note('power_max_w').get_text(), 'About 1500 W real with a x10 shunt')
                # 1 hides every line; the multiplier is kept when another ROM is opened.
                window.shunt_entry.set_text('1')
                self.assertFalse(window.shunt_entry.has_css_class('error'))
                self.assertFalse(any(n.get_visible() for n, _ in window.shunt_notes.values()))
                self.assertFalse(window.shunt_help.get_visible())
                window.shunt_entry.set_text('1.33')
                other = Path(tmp) / 'blackwell.rom'
                other.write_bytes(synthetic_blackwell())
                window.open_path(other)
                until(lambda: not window.busy and window.controller.document.original.name == str(other))
                self.assertEqual(window.shunt_entry.get_text(), '1.33')
                self.assertIn('About 133 W real with a x1.33 shunt', texts(window.rows['power_max_w']['row']))
                self.assertTrue(note('power_max_w').get_visible())
            finally:
                window.close()
                while context.pending():
                    context.iteration(False)

    def _exercise_window(self, language):
        import gi
        gi.require_version('Gtk', '4.0')
        gi.require_version('Graphene', '1.0')
        from gi.repository import Gio, GLib, Graphene, Gtk
        from nvidia_vbios.gui.app import EditorWindow
        from test_rom_formats import synthetic_blackwell
        # One application id per language: both subtests run in one process.
        app = Gtk.Application(application_id=f'org.nvidia_vbios.Smoke.{language}', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        Gtk.Settings.get_default().set_property('gtk-enable-animations', False)
        context = GLib.MainContext.default()

        def until(condition):
            deadline = time.monotonic() + 15
            while not condition():
                while context.pending():
                    context.iteration(False)
                if time.monotonic() >= deadline:
                    self.fail('GTK operation did not complete')
                time.sleep(.01)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'synthetic-blackwell.rom'
            path.write_bytes(synthetic_blackwell())
            window = EditorWindow(app, path, language)
            window.present()
            try:
                until(lambda: not window.busy and window.get_mapped())
                self.assertIsNotNone(window.controller.document)
                self.assertTrue(window.lookup_action('stage').get_enabled())
                self.assertTrue(window.reset_button.is_sensitive())
                self.assertFalse(window.lookup_action('save').get_enabled())
                self.assertIn('memory_offset_max_mhz', window.entries)
                self.assertIn('power_min_w', window.entries)
                self.assertNotIn('dram_max_table_mhz', window.entries)
                chooser = window._dialog(window.text('open_dialog'))
                chooser.set_accept_label(window.text('open_accept'))
                self.assertIsInstance(chooser, Gtk.FileDialog)
                self.assertEqual(chooser.get_title(), window.text('open_dialog'))
                self.assertEqual(chooser.get_accept_label(), window.text('open_accept'))
                self.assertNotIn('SHA256', window.integrity.get_text())

                from nvidia_vbios.gui.app import texts
                field_text = '\n'.join(texts(window.field_box))
                # No technical-details section: its evidence belongs to the README and the JSON manifest.
                self.assertFalse(hasattr(window, 'details'))
                self.assertFalse([t for t in texts(window) if 'Technical details' in t or 'Detalles técnicos' in t])
                self.assertIn('Original: 100 W', field_text)
                # Read-only fields are grouped after the editable sections; the generic placeholders
                # without a value (input current, OCP) are not shown.
                self.assertIn('nvvdd_output_ocp_max_ma', window.readonly_rows)
                for key in ('current_limit_a', 'ocp_limit_a'):
                    self.assertNotIn(key, window.readonly_rows)
                    self.assertNotIn(key, window.entries)
                self.assertEqual(window.open_button.get_label(), 'Open ROM…' if language == 'en' else window.text('open'))
                self.assertEqual(window.get_title(), window.text('window_title'))
                self.assertIn(window.text('field.power_min_w'), field_text)
                self.assertNotIn('codificación', field_text)
                self.assertNotIn('encoding:', field_text)
                self.assertNotIn('(tabla)', field_text)
                self.assertFalse(window.dirty)
                # XOC-style opt-in fields appear only after ticking the box; typed values survive.
                self.assertFalse(window.advanced_toggle.get_active())
                self.assertNotIn('board_fixed_rated_w', window.entries)
                window.entries['power_max_w'].set_text('150')
                window.advanced_toggle.set_active(True)
                self.assertIn('board_fixed_rated_w', window.entries)
                self.assertEqual(window.entries['power_max_w'].get_text(), '150')
                window.advanced_toggle.set_active(False)
                self.assertNotIn('board_fixed_rated_w', window.entries)
                # A value typed into a field that is then hidden still reaches the stage.
                window.advanced_toggle.set_active(True)
                window.entries['board_fixed_rated_w'].set_text('90')
                window.advanced_toggle.set_active(False)
                self.assertTrue(window.dirty)
                self.assertIn('90', window.preview_text())
                # Typing updates the row and the change list at once, and verifies after a pause.
                window.entries['power_max_w'].set_text('150')
                window.entries['power_min_w'].set_text('1')
                window.entries['memory_offset_max_mhz'].set_text('10000')
                self.assertTrue(window.verifying)
                self.assertTrue(window.entries['power_max_w'].is_sensitive())
                self.assertIn('changed', window.rows['memory_offset_max_mhz']['row'].get_css_classes())
                self.assertIn('Afterburner: 5000 MHz', window.rows['memory_offset_max_mhz']['delta'].get_text())
                self.assertFalse(window.lookup_action('save').get_enabled())
                until(lambda: not window.verifying and not window.dirty)
                self.assertEqual(window.controller.document.changes['power_max_w'], '150')
                self.assertEqual(window.controller.document.changes['power_min_w'], '1')
                self.assertEqual(window.controller.document.changes['memory_offset_max_mhz'], '10000')
                self.assertEqual(window.controller.document.changes['board_fixed_rated_w'], '90')
                self.assertTrue(window.lookup_action('save').get_enabled())
                self.assertTrue(window.save_button.is_sensitive())
                self.assertIn('6000 → 10000 MHz', window.preview_text())
                self.assertIn(window.text('field.memory_offset_max_mhz'), window.preview_text())
                self.assertTrue(window.status.get_text().startswith(window.text('live_ok', count=0, bytes=0).split(':')[0]))
                self.assertNotIn('(tabla)', window.preview_text())
                # A value out of range marks its row and blocks saving; text that is not a number never reaches the backend.
                window.entries['memory_offset_max_mhz'].set_text('70000')
                until(lambda: not window.verifying)
                self.assertIn('invalid', window.rows['memory_offset_max_mhz']['row'].get_css_classes())
                self.assertIn('65534', window.rows['memory_offset_max_mhz']['delta'].get_text())
                self.assertFalse(window.lookup_action('save').get_enabled())
                window.entries['memory_offset_max_mhz'].set_text('abc')
                until(lambda: not window.verifying)
                self.assertEqual(window.status.get_text(), window.text('fix_fields'))
                self.assertTrue(window.status.has_css_class('error'))
                # Pasted magnitudes no field can hold are refused locally, then the row recovers.
                for text in ('1e29', '-1e-999999999', '9' * 5000):
                    window.entries['memory_offset_max_mhz'].set_text(text)
                    self.assertEqual(window.rows['memory_offset_max_mhz']['delta'].get_text(), window.text('out_of_range'))
                    until(lambda: not window.verifying)
                    self.assertEqual(window.status.get_text(), window.text('fix_fields'))
                    self.assertFalse(window.lookup_action('save').get_enabled())
                window.entries['memory_offset_max_mhz'].set_text('10000')
                until(lambda: not window.verifying and not window.dirty)
                self.assertNotIn('invalid', window.rows['memory_offset_max_mhz']['row'].get_css_classes())
                self.assertFalse(window.status.has_css_class('error'))
                self.assertTrue(window.lookup_action('save').get_enabled())
                # A late result for older inputs never replaces newer typing.
                window.entries['power_max_w'].set_text('160')
                revision = window.input_revision
                window._verified(window.generation, revision - 1, window.controller.document, None)
                self.assertTrue(window.dirty)
                until(lambda: not window.verifying and not window.dirty)
                self.assertEqual(window.controller.document.changes['power_max_w'], '160')
                # A failed open while a check is pending keeps the document and resumes that check quietly.
                window.entries['power_max_w'].set_text('170')
                window.open_path(Path(tmp) / 'missing.rom')
                until(lambda: not window.busy)
                failure = window.status.get_text()
                self.assertTrue(window.status.has_css_class('error'))
                until(lambda: not window.verifying and not window.dirty)
                self.assertEqual(window.controller.document.changes['power_max_w'], '170')
                self.assertTrue(window.lookup_action('save').get_enabled())
                self.assertEqual(window.status.get_text(), failure)
                # Re-verifying with the box unticked keeps the staged opt-in value.
                window.activate_action('win.stage', None)
                until(lambda: not window.verifying and not window.dirty)
                self.assertEqual(window.controller.document.changes['board_fixed_rated_w'], '90')
                screenshot = os.environ.get('VBIOS_GUI_SCREENSHOT')
                if screenshot:
                    if language == 'es':
                        destination = Path(screenshot)
                        screenshot = str(destination.with_name(destination.stem + '_es' + destination.suffix))
                    # Wait for the newly rendered layout before snapshotting.
                    target = time.monotonic() + .5
                    until(lambda: time.monotonic() > target)
                    # Broadway without a browser has no native frame allocation.
                    # Allocate the real widgets explicitly for a content render.
                    window.allocate(760, 920, -1, None)
                    snapshot = Gtk.Snapshot.new()
                    snapshot.render_background(window.get_style_context(), 0, 0, 760, 920)
                    window.snapshot_child(window.get_first_child(), snapshot)
                    window.snapshot_child(window.get_titlebar(), snapshot)
                    node = snapshot.to_node()
                    self.assertIsNotNone(node)
                    bounds = Graphene.Rect().init(0, 0, 760, 920)
                    texture = window.get_renderer().render_texture(node, bounds)
                    Path(screenshot).parent.mkdir(parents=True, exist_ok=True)
                    self.assertTrue(texture.save_to_png(screenshot))
                # Actual save runs on the worker and retains the source.
                from nvidia_vbios.gui.controller import save_document
                doc = window.controller.document
                output = Path(tmp) / 'copy.rom'
                window._run('Smoke save', lambda: save_document(doc, output), saving=True)
                until(lambda: not window.busy)
                self.assertTrue(output.exists())
                self.assertTrue(Path(str(output) + '.json').exists())
                window._reset()
                self.assertEqual(window.controller.document.changes, {})
                self.assertEqual(window.status.get_text(), window.text('reset_done'))
                from nvidia_vbios.editor import VbiosError
                window._run('Smoke failure', lambda: (_ for _ in ()).throw(VbiosError('SOURCE_CHANGED', 'raw backend evidence')))
                until(lambda: not window.busy)
                self.assertIn(window.text('error.SOURCE_CHANGED'), window.status.get_text())
                self.assertIn('[SOURCE_CHANGED]', window.status.get_text())
                # A code without a translation keeps the backend's explanation in the status line.
                window._run('Smoke failure', lambda: (_ for _ in ()).throw(VbiosError('NEW_CODE', 'raw backend evidence')))
                until(lambda: not window.busy)
                self.assertIn('raw backend evidence [NEW_CODE]', window.status.get_text())
                # A delayed old result must not replace a newly opened ROM.
                from threading import Event
                from nvidia_vbios.gui.controller import open_document
                gate = Event()
                window._run('Delayed stale result', lambda: (gate.wait(5), doc)[1])
                other = Path(tmp) / 'unknown.rom'
                other.write_bytes(b'unknown')
                window.open_path(other)
                until(lambda: not window.busy)
                gate.set()
                target = time.monotonic() + .2
                until(lambda: time.monotonic() > target)
                self.assertEqual(window.controller.document.original.name, str(other))
                self.assertEqual(window.entries, {})
            finally:
                window.close()
                while context.pending():
                    context.iteration(False)


if __name__ == '__main__':
    unittest.main()
