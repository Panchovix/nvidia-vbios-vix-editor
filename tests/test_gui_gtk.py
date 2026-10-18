"""Opt-in actual GTK window smoke test; requires a dedicated display.

VBIOS_GUI_SMOKE=1; optional VBIOS_GUI_SCREENSHOT=/ignored/path.png.
Does not use reference ROMs or access GPUs.
"""
import os
from pathlib import Path
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
            for language, title, note in (
                    ('en', 'Connector power channel 1 ceiling', 'Row 11 also caps the sum of connector power channels '
                                                                '1, 2 at 280 W rated / 280 W maximum'),
                    ('es', 'Techo del canal de potencia de conector 1', 'La fila 11 también limita la suma de los '
                                                                        'canales de potencia de conector 1, 2')):
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
                        # Hardware thresholds stay behind the advanced toggle; constant voltages have no entry.
                        self.assertNotIn('input_current_rated_ma', window.entries)
                        self.assertNotIn('nvvdd_rel_equation_max_mv', window.entries)
                        window.entries['connector_1_power_max_w'].set_text('200')
                        until(lambda: not window.verifying and not window.dirty)
                        self.assertEqual(window.controller.document.changes['connector_1_power_max_w'], '200')
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
                # Read-only fields are grouped after the editable sections.
                self.assertIn('current_limit_a', window.readonly_rows)
                self.assertIn('ocp_limit_a', window.readonly_rows)
                self.assertNotIn('current_limit_a', window.entries)
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
